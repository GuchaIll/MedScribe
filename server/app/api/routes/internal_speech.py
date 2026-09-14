"""
Internal speech worker route.

This endpoint is intended for the Go gateway's audio proxy consumer only.
It accepts a single voiced segment, runs the configured speech provider, and
returns the authoritative transcript + diarization result.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from app.services.speech_worker_service import SpeechSegmentRequest, SpeechWorkerService


router = APIRouter(tags=["internal"])


class InternalAudioSegmentResponse(BaseModel):
    session_id: str
    segment_id: str
    status: str
    text: str
    speaker_id: str = ""
    speaker_role: str = ""
    role_confidence: float = 0.0
    transcription_confidence: float = 0.0
    start_ms: int = 0
    end_ms: int = 0
    source: str = ""
    error: str = ""


@lru_cache(maxsize=1)
def get_speech_worker_service() -> SpeechWorkerService:
    return SpeechWorkerService()


@router.post("/internal/audio-segment", response_model=InternalAudioSegmentResponse)
async def process_audio_segment(
    session_id: str = Form(...),
    segment_id: str = Form(...),
    started_at_ms: int = Form(default=0),
    ended_at_ms: int = Form(default=0),
    sample_rate_hz: int = Form(default=0),
    mime_type: str = Form(default=""),
    optimistic_text: str = Form(default=""),
    optimistic_speaker: str = Form(default=""),
    file: UploadFile = File(...),
    reference_clinician: UploadFile | None = File(default=None),
    reference_patient: UploadFile | None = File(default=None),
) -> InternalAudioSegmentResponse:
    service = get_speech_worker_service()
    payload = await file.read()
    reference_samples = []
    if reference_clinician is not None:
        reference_samples.append(
            {
                "role": "Clinician",
                "file_name": reference_clinician.filename or "clinician.wav",
                "mime_type": reference_clinician.content_type or "",
                "payload": await reference_clinician.read(),
            }
        )
    if reference_patient is not None:
        reference_samples.append(
            {
                "role": "Patient",
                "file_name": reference_patient.filename or "patient.wav",
                "mime_type": reference_patient.content_type or "",
                "payload": await reference_patient.read(),
            }
        )
    result = service.process_upload(
        SpeechSegmentRequest(
            session_id=session_id,
            segment_id=segment_id,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            sample_rate_hz=sample_rate_hz,
            mime_type=mime_type or (file.content_type or ""),
            optimistic_text=optimistic_text,
            optimistic_speaker=optimistic_speaker,
        ),
        file_name=file.filename or f"{segment_id}.bin",
        payload=payload,
        reference_samples=reference_samples,
    )
    return InternalAudioSegmentResponse(**result.to_dict())
