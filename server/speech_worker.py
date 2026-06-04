"""
Dedicated speech worker service entry point.

Runs only the internal queued-audio speech endpoint used by the Go gateway's
audio proxy consumer. This keeps speech processing isolated from the main
LangGraph API server and makes it easier to point the worker at remote GPU
providers in development.
"""

from pathlib import Path
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn


load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent / "app"))

from app.api.routes.internal_speech import router as internal_speech_router  # noqa: E402


app = FastAPI(title="MedScribe Speech Worker")
app.include_router(internal_speech_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "medscribe-speech-worker"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3002)
