"""
Medical Transcription API — application entry point.

This file ONLY handles:
  - FastAPI app creation & middleware
  - Router mounting
  - Startup configuration

All business logic lives in app/services/, app/agents/, and app/core/.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import uvicorn

# Load environment variables — root .env first, then server/.env
# (server/.env values take precedence so local overrides work)
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')  # project root
load_dotenv(dotenv_path=Path(__file__).parent / '.env', override=True)  # server/

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

app = FastAPI(title="Medical Transcription API")

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


@app.get("/")
async def read_root():
    return {"status": "ok", "service": "Medical Transcription API"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3001)
