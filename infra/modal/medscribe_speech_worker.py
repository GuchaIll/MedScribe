"""
Modal-hosted Whisper + pyannote worker for MedScribe.

This service matches the existing ``remote_http`` contract used by
``server/app/services/speech_worker_service.py``:

- ``POST /process-audio``
- multipart ``file`` upload
- form fields for session/segment metadata

It is designed for development machines that cannot run heavy speech models
locally. pyannote still provides anonymous diarization labels, so this worker
uses speaker embeddings plus the uploaded clinician/patient reference clips to
map the current utterance to one of those two session roles.
"""

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import os
import tempfile

import modal


APP_NAME = "medscribe-speech-worker"
DEFAULT_GPU = os.getenv("MODAL_GPU", "L4")
DEFAULT_WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
DEFAULT_WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
DEFAULT_WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
DEFAULT_PYANNOTE_MODEL = os.getenv(
    "PYANNOTE_MODEL",
    "pyannote/speaker-diarization-3.1",
)
DEFAULT_EMBEDDING_MODEL = os.getenv("PYANNOTE_EMBEDDING_MODEL", "pyannote/embedding")
HF_CACHE_DIR = "/models/hf"

os.environ.setdefault("HF_HOME", HF_CACHE_DIR)
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", f"{HF_CACHE_DIR}/hub")
os.environ.setdefault("HF_HUB_CACHE", f"{HF_CACHE_DIR}/hub")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "fastapi[standard]",
        "python-multipart",
        "faster-whisper",
        "huggingface_hub",
        "pyannote.audio",
        "torch",
        "torchaudio",
    )
)

app = modal.App(APP_NAME, image=image)

worker_secret = modal.Secret.from_name("medscribe-speech-worker", required_keys=[])
hf_secret = modal.Secret.from_name("huggingface", required_keys=[])
hf_cache_volume = modal.Volume.from_name("medscribe-hf-cache", create_if_missing=True)


@dataclass
class SpeechSegmentResult:
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


@dataclass
class ReferenceSample:
    role: str
    temp_path: Path


def _normalize_role(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"clinician", "doctor", "provider"}:
        return "Clinician"
    if normalized == "patient":
        return "Patient"
    return ""


def _normalize_confidence(avg_logprobs: list[float]) -> float:
    if not avg_logprobs:
        return 0.0
    mean = sum(avg_logprobs) / len(avg_logprobs)
    return max(0.0, min(1.0, (mean + 5.0) / 5.0))


def _resolve_auth_header(authorization: str | None) -> None:
    from fastapi import HTTPException

    expected = os.getenv("SPEECH_REMOTE_API_KEY", "").strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")


@lru_cache(maxsize=1)
def _get_whisper_model():
    from faster_whisper import WhisperModel

    return WhisperModel(
        DEFAULT_WHISPER_MODEL,
        device=DEFAULT_WHISPER_DEVICE,
        compute_type=DEFAULT_WHISPER_COMPUTE_TYPE,
    )


@lru_cache(maxsize=1)
def _get_diarization_pipeline():
    from pyannote.audio import Pipeline

    token = (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_API_KEY")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    )
    if not token:
        raise RuntimeError("HF_TOKEN or HUGGINGFACE_API_KEY is required for pyannote")

    pipeline = Pipeline.from_pretrained(DEFAULT_PYANNOTE_MODEL, use_auth_token=token)
    try:
        import torch

        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
    except Exception:
        pass
    return pipeline


@lru_cache(maxsize=1)
def _get_embedding_inference():
    from pyannote.audio import Inference, Model

    token = (
        os.getenv("HF_TOKEN")
        or os.getenv("HUGGINGFACE_API_KEY")
        or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    )
    if not token:
        raise RuntimeError("HF_TOKEN or HUGGINGFACE_API_KEY is required for pyannote")

    model = Model.from_pretrained(DEFAULT_EMBEDDING_MODEL, use_auth_token=token)
    return Inference(model, window="whole")


@lru_cache(maxsize=1)
def _preload_models() -> bool:
    print(
        f"[startup] Preloading whisper={DEFAULT_WHISPER_MODEL} "
        f"diarizer={DEFAULT_PYANNOTE_MODEL} embedding={DEFAULT_EMBEDDING_MODEL}"
    )
    _get_whisper_model()
    _get_diarization_pipeline()
    _get_embedding_inference()
    print("[startup] Speech models ready")
    return True


def _flatten_embedding(value: object) -> list[float]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    while isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, list):
        flattened: list[float] = []
        for item in value:
            if isinstance(item, list):
                flattened.extend(float(x) for x in item)
            else:
                flattened.append(float(item))
        return flattened
    return []


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    numerator = sum(left[idx] * right[idx] for idx in range(size))
    left_norm = sum(value * value for value in left[:size]) ** 0.5
    right_norm = sum(value * value for value in right[:size]) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _match_role(audio_path: Path, reference_samples: list[ReferenceSample]) -> tuple[str, float]:
    if not reference_samples:
        return "", 0.0

    inference = _get_embedding_inference()
    utterance_embedding = _flatten_embedding(inference(str(audio_path)))
    if not utterance_embedding:
        return "", 0.0

    scored_roles: list[tuple[str, float]] = []
    for sample in reference_samples:
        role = _normalize_role(sample.role)
        if not role:
            continue
        reference_embedding = _flatten_embedding(inference(str(sample.temp_path)))
        if not reference_embedding:
            continue
        scored_roles.append((role, _cosine_similarity(utterance_embedding, reference_embedding)))

    if not scored_roles:
        return "", 0.0

    scored_roles.sort(key=lambda item: item[1], reverse=True)
    top_role, top_similarity = scored_roles[0]
    runner_up = scored_roles[1][1] if len(scored_roles) > 1 else 0.0
    margin = max(0.0, top_similarity - runner_up)
    confidence = max(0.0, min(1.0, 0.5 + margin / 2.0))
    return top_role, confidence


def _transcribe_and_diarize(
    *,
    session_id: str,
    segment_id: str,
    started_at_ms: int,
    ended_at_ms: int,
    optimistic_text: str,
    optimistic_speaker: str,
    audio_path: Path,
    reference_samples: list[ReferenceSample],
) -> SpeechSegmentResult:
    whisper = _get_whisper_model()
    diarizer = _get_diarization_pipeline()

    segments, _info = whisper.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=False,
    )
    materialized_segments = list(segments)
    text = " ".join(
        seg.text.strip()
        for seg in materialized_segments
        if getattr(seg, "text", "").strip()
    )
    confidences = [
        float(getattr(seg, "avg_logprob", 0.0) or 0.0)
        for seg in materialized_segments
        if hasattr(seg, "avg_logprob")
    ]

    diarization = diarizer(str(audio_path))
    primary_speaker = "SPEAKER_00"
    longest_duration = -1.0
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        duration = float(turn.end - turn.start)
        if duration > longest_duration:
            primary_speaker = speaker
            longest_duration = duration

    speaker_role, role_confidence = _match_role(audio_path, reference_samples)
    if not speaker_role:
        speaker_role = _normalize_role(optimistic_speaker)
        role_confidence = 0.25 if speaker_role else 0.0

    return SpeechSegmentResult(
        session_id=session_id,
        segment_id=segment_id,
        status="completed",
        text=text or optimistic_text or "[No speech recognized]",
        speaker_id=primary_speaker,
        speaker_role=speaker_role,
        role_confidence=role_confidence,
        transcription_confidence=_normalize_confidence(confidences),
        start_ms=started_at_ms,
        end_ms=ended_at_ms,
        source="modal_whisper_pyannote",
    )


def _persist_reference_file(upload, label: str) -> Path:
    suffix = Path(upload.filename or f"{label}.bin").suffix or ".bin"
    payload = upload.file.read()
    with tempfile.NamedTemporaryFile(
        prefix=f"medscribe-modal-reference-{label}-",
        suffix=suffix,
        delete=False,
    ) as tmp:
        tmp.write(payload)
        return Path(tmp.name)


def _build_web_app():
    from fastapi import FastAPI, HTTPException, Request

    web_app = FastAPI(title="MedScribe Modal Speech Worker")

    @web_app.on_event("startup")
    async def preload_on_startup() -> None:
        _preload_models()

    @web_app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @web_app.post("/process-audio")
    async def process_audio(
        request: Request,
    ) -> dict[str, object]:
        _resolve_auth_header(request.headers.get("authorization"))

        form = await request.form()
        session_id = str(form.get("session_id") or "").strip()
        segment_id = str(form.get("segment_id") or "").strip()
        if not session_id or not segment_id:
            raise HTTPException(status_code=400, detail="session_id and segment_id are required")

        started_at_ms = _parse_int(form.get("started_at_ms"), default=0)
        ended_at_ms = _parse_int(form.get("ended_at_ms"), default=0)
        _sample_rate_hz = _parse_int(form.get("sample_rate_hz"), default=0)
        mime_type = str(form.get("mime_type") or "").strip()
        optimistic_text = str(form.get("optimistic_text") or "")
        optimistic_speaker = str(form.get("optimistic_speaker") or "")

        file = form.get("file")
        if file is None or not hasattr(file, "read") or not hasattr(file, "filename"):
            raise HTTPException(status_code=400, detail="file upload is required")

        suffix = Path(file.filename or f"{segment_id}.bin").suffix or ".bin"
        payload = await file.read()
        with tempfile.NamedTemporaryFile(
            prefix="medscribe-modal-segment-",
            suffix=suffix,
            delete=False,
        ) as tmp:
            tmp.write(payload)
            temp_path = Path(tmp.name)
        reference_samples: list[ReferenceSample] = []

        try:
            reference_clinician = form.get("reference_clinician")
            if reference_clinician is not None:
                reference_samples.append(
                    ReferenceSample(
                        role="Clinician",
                        temp_path=_persist_reference_file(reference_clinician, "clinician"),
                    )
                )
            reference_patient = form.get("reference_patient")
            if reference_patient is not None:
                reference_samples.append(
                    ReferenceSample(
                        role="Patient",
                        temp_path=_persist_reference_file(reference_patient, "patient"),
                    )
                )
            result = _transcribe_and_diarize(
                session_id=session_id,
                segment_id=segment_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                optimistic_text=optimistic_text,
                optimistic_speaker=optimistic_speaker,
                audio_path=temp_path,
                reference_samples=reference_samples,
            )
            return asdict(result)
        except Exception as exc:  # noqa: BLE001
            failed = SpeechSegmentResult(
                session_id=session_id,
                segment_id=segment_id,
                status="failed",
                text=optimistic_text,
                speaker_id="SPEAKER_00",
                speaker_role=_normalize_role(optimistic_speaker),
                start_ms=started_at_ms,
                end_ms=ended_at_ms,
                source="modal_whisper_pyannote_error",
                error=str(exc),
            )
            return asdict(failed)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            for sample in reference_samples:
                try:
                    sample.temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    return web_app


def _parse_int(value, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(str(value))
    except (TypeError, ValueError):
        return default


@app.function(
    gpu=DEFAULT_GPU,
    cpu=4,
    memory=32768,
    timeout=900,
    scaledown_window=300,
    min_containers=1,
    max_containers=4,
    secrets=[worker_secret, hf_secret],
    volumes={HF_CACHE_DIR: hf_cache_volume},
)
@modal.asgi_app(label="medscribe-speech-worker")
def modal_entrypoint():
    return _build_web_app()
