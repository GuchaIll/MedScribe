"""
Medical Transcription API — application entry point.

This file ONLY handles:
  - FastAPI app creation & middleware
  - Router mounting
  - Startup configuration

All business logic lives in app/services/, app/agents/, and app/core/.
"""

import logging
import logging.handlers
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

# Load environment variables — root .env first, then server/.env
# override=False ensures actual environment variables (e.g. from Docker Compose)
# always take precedence over .env file values. For local dev, neither file is
# pre-set so the .env values are still used.
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')   # project root
load_dotenv(dotenv_path=Path(__file__).parent / '.env')          # server/ (no override)

# Add app directory to Python path
sys.path.insert(0, str(Path(__file__).parent / 'app'))

# NOTE: authenticate_user import removed — the legacy hardcoded endpoint
# that used it has been commented out.  Auth is applied per-router now.
from app.api.routes.records import router as records_router
from app.api.routes.clinical import router as clinical_router
from app.api.routes.transcript import router as transcript_router
from app.api.routes.tts import router as tts_router
from app.api.routes.session import router as session_router
from app.api.routes.patient import router as patient_router
from app.api.routes.assistant import router as assistant_router
from app.api.routes.llm_config import router as llm_config_router


# ---------------------------------------------------------------------------
# Service startup logging — written to logs/service.log
# ---------------------------------------------------------------------------

def _configure_service_logger() -> logging.Logger:
    """Set up a dedicated logger that writes to logs/service.log."""
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "service.log"

    logger = logging.getLogger("medscribe.startup")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — 5 MB, keep 3 backups
    fh = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # Also echo startup checks to console
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(ch)

    return logger


def _check_database(log: logging.Logger) -> bool:
    """Attempt a real connection to PostgreSQL and return True on success."""
    try:
        from app.config.settings import get_settings
        from sqlalchemy import create_engine, text

        url = get_settings().database.url
        engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        # Mask password in logged URL
        safe_url = url.split("@")[-1] if "@" in url else url
        log.info(f"  [OK]  Database         — connected to {safe_url}")
        return True
    except Exception as exc:
        log.error(f"  [FAIL] Database        — {exc}")
        return False


def _check_env_key(log: logging.Logger, var: str, label: str) -> bool:
    """Check that an environment variable is set and non-empty."""
    val = os.getenv(var, "").strip()
    if val:
        masked = val[:6] + "***" + val[-3:] if len(val) > 12 else "***"
        log.info(f"  [OK]  {label:<20} — {var}={masked}")
        return True
    else:
        log.warning(f"  [WARN] {label:<19} — {var} not set")
        return False


def _check_storage(log: logging.Logger) -> bool:
    """Verify that the storage directories are accessible."""
    try:
        from app.config.settings import get_settings
        base = Path(get_settings().storage.base_dir)
        subdirs = ["audio", "transcripts", "outputs"]
        for sub in subdirs:
            (base / sub).mkdir(parents=True, exist_ok=True)
        log.info(f"  [OK]  Storage            — base_dir='{base}' (audio, transcripts, outputs)")
        return True
    except Exception as exc:
        log.error(f"  [FAIL] Storage          — {exc}")
        return False


def _check_embedding_model(log: logging.Logger) -> bool:
    """Verify the embedding model name is configured (does not download)."""
    try:
        from app.config.settings import get_settings
        model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        log.info(f"  [OK]  Embedding model   — {model_name} (lazy-loaded on first use)")
        return True
    except Exception as exc:
        log.error(f"  [FAIL] Embedding model — {exc}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — runs startup health checks and logs results."""
    log = _configure_service_logger()
    start = time.perf_counter()

    log.info("=" * 60)
    log.info("  MedScribe API — service startup")
    log.info("=" * 60)

    # Check for at least one LLM provider
    from app.config.settings import get_settings
    settings = get_settings()
    llm_providers_available = []
    if settings.groq_api_key:
        llm_providers_available.append("groq")
    if settings.openai_api_key:
        llm_providers_available.append("openai")
    if settings.anthropic_api_key:
        llm_providers_available.append("anthropic")
    if settings.google_api_key:
        llm_providers_available.append("google")
    if settings.openrouter_api_key:
        llm_providers_available.append("openrouter")

    llm_check = bool(llm_providers_available)
    if llm_providers_available:
        providers_str = ", ".join(llm_providers_available)
        log.info(f"  [OK]  LLM Providers     — {providers_str}")
    else:
        log.warning(
            "  [WARN] LLM Providers     — No LLM API keys configured. "
            "Set one of: GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "GOOGLE_API_KEY, or OPENROUTER_API_KEY"
        )

    results = {
        "database":        _check_database(log),
        "llm_provider":    llm_check,
        "elevenlabs_key":  _check_env_key(log, "ELEVEN_LABS_API_KEY", "ElevenLabs TTS"),
        "secret_key":      _check_env_key(log, "SECRET_KEY", "JWT secret key"),
        "storage":         _check_storage(log),
        "embedding_model": _check_embedding_model(log),
    }

    elapsed = (time.perf_counter() - start) * 1000
    ok_count = sum(results.values())
    total = len(results)

    log.info("-" * 60)
    log.info(
        f"  Startup checks: {ok_count}/{total} passed  "
        f"({elapsed:.0f}ms)  "
        f"— {'READY' if results['database'] and llm_check else 'DEGRADED'}"
    )
    log.info("=" * 60)

    yield  # application runs here

    log.info("  MedScribe API — shutdown")


# ---------------------------------------------------------------------------

app = FastAPI(title="Medical Transcription API", lifespan=lifespan)

# Allow the React dev server (port 3000) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3002"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(session_router)
app.include_router(records_router)
app.include_router(clinical_router)
app.include_router(transcript_router)
app.include_router(tts_router)
app.include_router(patient_router)
app.include_router(assistant_router)
app.include_router(llm_config_router)


@app.get("/")
async def read_root():
    return {"status": "ok", "service": "Medical Transcription API"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3001)
