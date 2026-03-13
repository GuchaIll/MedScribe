"""Transcript routes — LLM-based speaker reclassification."""
import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

router = APIRouter()


class TranscriptMessage(BaseModel):
    id: str
    speaker: str
    content: str
    timestamp: str
    type: str  # 'user' | 'system'


class ReclassifyRequest(BaseModel):
    messages: List[TranscriptMessage]


class ReclassifyResponse(BaseModel):
    messages: List[TranscriptMessage]


@router.post("/api/transcript/reclassify", response_model=ReclassifyResponse)
async def reclassify_speakers(body: ReclassifyRequest):
    """
    Use LLM to classify each utterance as 'Clinician' or 'Patient' based on
    clinical conversation patterns. Calls Groq directly to avoid loading the
    ML model registry (which triggers the pyannote/torch DLL conflict).
    """
    if not body.messages:
        return ReclassifyResponse(messages=[])

    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not set — speaker reclassification unavailable",
        )

    transcript_lines = [f"[{i}] {msg.content}" for i, msg in enumerate(body.messages)]
    transcript_text = "\n".join(transcript_lines)

    prompt = f"""You are analyzing a medical consultation transcript to identify who said each utterance.

Classify each utterance as either "Clinician" or "Patient":
- Clinician: asks structured diagnostic questions, uses medical terminology, gives instructions, describes treatment plans, orders tests
- Patient: describes symptoms, answers questions, expresses concerns or fears, describes daily life and history

Transcript:
{transcript_text}

Return ONLY a JSON array with one entry per utterance, in the same order.
Each entry must be: {{"index": 0, "speaker": "Clinician"}}
No explanation. No markdown. Just the raw JSON array."""

    try:
        from groq import Groq

        client = Groq(api_key=groq_api_key)
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown code fences if the model wraps the JSON anyway
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        classifications = json.loads(raw)
        label_map = {item["index"]: item["speaker"] for item in classifications}

        updated = [
            msg.model_copy(update={"speaker": label_map.get(i, msg.speaker)})
            for i, msg in enumerate(body.messages)
        ]
        return ReclassifyResponse(messages=updated)

    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"LLM returned invalid JSON for classification: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Reclassification failed: {exc}",
        )
