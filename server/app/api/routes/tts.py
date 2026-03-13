"""Text-to-speech route — ElevenLabs audio synthesis."""
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# Rachel: clear, professional voice that suits clinical alerts.
# Override by setting ELEVENLABS_VOICE_ID in the environment.
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel
_DEFAULT_MODEL_ID = "eleven_turbo_v2"        # Lowest latency model


class TTSRequest(BaseModel):
    text: str


@router.post("/api/tts")
async def text_to_speech(body: TTSRequest):
    """
    Synthesise speech via ElevenLabs and stream the MP3 back to the caller.
    Requires ELEVENLABS_API_KEY to be set in the environment.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY not configured — TTS unavailable",
        )

    voice_id = os.getenv("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)
    model_id = os.getenv("ELEVENLABS_MODEL_ID", _DEFAULT_MODEL_ID)

    try:
        from elevenlabs import ElevenLabs

        client = ElevenLabs(api_key=api_key)
        audio = client.text_to_speech.convert(
            text=body.text,
            voice_id=voice_id,
            model_id=model_id,
            output_format="mp3_44100_128",
        )
        return StreamingResponse(audio, media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {exc}")
