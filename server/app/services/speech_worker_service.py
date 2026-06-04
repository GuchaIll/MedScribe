"""
Dedicated speech worker service for queued audio segment processing.

This service is designed to run behind the Go gateway's Kafka consumer proxy.
It supports three modes:

- ``noop``: infrastructure-only fallback for environments without Whisper
- ``remote_http``: delegates transcription + diarization to a remote service
- ``local_whisper_pyannote``: runs local faster-whisper + pyannote when available
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
import json
import os
import tempfile
import time

import httpx
import redis


@dataclass
class SpeechSegmentRequest:
    session_id: str
    segment_id: str
    started_at_ms: int = 0
    ended_at_ms: int = 0
    sample_rate_hz: int = 0
    mime_type: str = ""
    optimistic_text: str = ""
    optimistic_speaker: str = ""


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "segment_id": self.segment_id,
            "status": self.status,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "speaker_role": self.speaker_role,
            "role_confidence": self.role_confidence,
            "transcription_confidence": self.transcription_confidence,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "source": self.source,
            "error": self.error,
        }


@dataclass
class ReferenceSample:
    role: str
    file_name: str
    mime_type: str
    temp_path: Path


class SpeechProvider(Protocol):
    def process(
        self,
        request: SpeechSegmentRequest,
        audio_path: Path,
        reference_samples: list[ReferenceSample],
    ) -> SpeechSegmentResult:
        ...


class NoOpSpeechProvider:
    def process(
        self,
        request: SpeechSegmentRequest,
        audio_path: Path,
        reference_samples: list[ReferenceSample],
    ) -> SpeechSegmentResult:
        del audio_path
        del reference_samples
        text = request.optimistic_text or "[Audio received — queued for remote Whisper]"
        role = _normalize_role(request.optimistic_speaker)
        return SpeechSegmentResult(
            session_id=request.session_id,
            segment_id=request.segment_id,
            status="completed",
            text=text,
            speaker_id="SPEAKER_00",
            speaker_role=role,
            role_confidence=0.2 if role else 0.0,
            transcription_confidence=0.0,
            start_ms=request.started_at_ms,
            end_ms=request.ended_at_ms,
            source="noop_speech_provider",
        )


class RemoteHTTPSpeechProvider:
    def __init__(self, base_url: str, api_key: str | None = None, timeout_s: float = 90.0) -> None:
        normalized_base_url = (base_url or "").strip().rstrip("/")
        if not normalized_base_url:
            raise ValueError("SPEECH_REMOTE_URL must be set when SPEECH_PROVIDER=remote_http")
        self.base_url = normalized_base_url
        self.api_key = api_key
        self.timeout_s = timeout_s

    def process(
        self,
        request: SpeechSegmentRequest,
        audio_path: Path,
        reference_samples: list[ReferenceSample],
    ) -> SpeechSegmentResult:
        url = f"{self.base_url}/process-audio"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = {
            "session_id": request.session_id,
            "segment_id": request.segment_id,
            "started_at_ms": str(request.started_at_ms),
            "ended_at_ms": str(request.ended_at_ms),
            "sample_rate_hz": str(request.sample_rate_hz),
            "mime_type": request.mime_type,
            "optimistic_text": request.optimistic_text,
            "optimistic_speaker": request.optimistic_speaker,
        }

        files_payload: list[tuple[str, tuple[str, Any, str]]] = []
        with audio_path.open("rb") as f, httpx.Client(timeout=self.timeout_s) as client:
            files_payload.append(
                ("file", (audio_path.name, f, request.mime_type or "application/octet-stream"))
            )
            opened_reference_files = []
            try:
                for sample in reference_samples:
                    ref_handle = sample.temp_path.open("rb")
                    opened_reference_files.append(ref_handle)
                    files_payload.append(
                        (
                            _reference_field_name(sample.role),
                            (
                                sample.file_name,
                                ref_handle,
                                sample.mime_type or "application/octet-stream",
                            ),
                        )
                    )
                response = client.post(
                    url,
                    data=data,
                    files=files_payload,
                    headers=headers,
                )
            finally:
                for ref_handle in opened_reference_files:
                    ref_handle.close()
        response.raise_for_status()
        payload = response.json()
        return SpeechSegmentResult(
            session_id=payload.get("session_id", request.session_id),
            segment_id=payload.get("segment_id", request.segment_id),
            status=payload.get("status", "completed"),
            text=payload.get("text", request.optimistic_text),
            speaker_id=payload.get("speaker_id", "SPEAKER_00"),
            speaker_role=_normalize_role(payload.get("speaker_role", "")),
            role_confidence=float(payload.get("role_confidence", 0.0) or 0.0),
            transcription_confidence=float(payload.get("transcription_confidence", 0.0) or 0.0),
            start_ms=int(payload.get("start_ms", request.started_at_ms) or 0),
            end_ms=int(payload.get("end_ms", request.ended_at_ms) or 0),
            source=payload.get("source", "remote_http_speech_provider"),
            error=payload.get("error", ""),
        )


class LocalWhisperPyannoteProvider:
    def process(
        self,
        request: SpeechSegmentRequest,
        audio_path: Path,
        reference_samples: list[ReferenceSample],
    ) -> SpeechSegmentResult:
        from app.models.registry import get_diarization_pipeline, get_whisper_model

        whisper = get_whisper_model()
        diarizer = get_diarization_pipeline()
        role_matcher = None
        if reference_samples:
            role_matcher = SpeakerEmbeddingRoleMatcher()

        segments, _info = whisper.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=False,
        )
        materialized_segments = list(segments)
        text = " ".join(seg.text.strip() for seg in materialized_segments if getattr(seg, "text", "").strip())
        confidences = [
            float(getattr(seg, "avg_logprob", 0.0) or 0.0)
            for seg in materialized_segments
            if hasattr(seg, "avg_logprob")
        ]
        confidence = _normalize_confidence(confidences)

        diarization = diarizer(str(audio_path))
        primary_speaker = "SPEAKER_00"
        longest_duration = -1.0
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            duration = float(turn.end - turn.start)
            if duration > longest_duration:
                primary_speaker = speaker
                longest_duration = duration

        speaker_role = ""
        role_confidence = 0.0
        if role_matcher is not None:
            speaker_role, role_confidence = role_matcher.match(audio_path, reference_samples)

        return SpeechSegmentResult(
            session_id=request.session_id,
            segment_id=request.segment_id,
            status="completed",
            text=text or request.optimistic_text or "[No speech recognized]",
            speaker_id=primary_speaker,
            speaker_role=speaker_role,
            role_confidence=role_confidence,
            transcription_confidence=confidence,
            start_ms=request.started_at_ms,
            end_ms=request.ended_at_ms,
            source="local_whisper_pyannote",
        )


class SpeakerEmbeddingRoleMatcher:
    def __init__(self) -> None:
        self._inference = _get_embedding_inference()

    def match(self, audio_path: Path, reference_samples: list[ReferenceSample]) -> tuple[str, float]:
        if not reference_samples:
            return "", 0.0
        utterance_embedding = _flatten_embedding(self._inference(str(audio_path)))
        if not utterance_embedding:
            return "", 0.0

        scored_roles: list[tuple[str, float]] = []
        for sample in reference_samples:
            role = _normalize_role(sample.role)
            if not role:
                continue
            reference_embedding = _flatten_embedding(self._inference(str(sample.temp_path)))
            if not reference_embedding:
                continue
            similarity = _cosine_similarity(utterance_embedding, reference_embedding)
            scored_roles.append((role, similarity))

        if not scored_roles:
            return "", 0.0

        scored_roles.sort(key=lambda item: item[1], reverse=True)
        top_role, top_similarity = scored_roles[0]
        runner_up = scored_roles[1][1] if len(scored_roles) > 1 else 0.0
        margin = max(0.0, top_similarity - runner_up)
        confidence = max(0.0, min(1.0, 0.5 + margin / 2.0))
        return top_role, confidence


class SessionRoleResolver:
    def __init__(self, redis_url: str | None) -> None:
        self._redis = redis.Redis.from_url(redis_url) if redis_url else None

    def resolve_role(self, request: SpeechSegmentRequest, speaker_id: str) -> tuple[str, float]:
        if not self._redis:
            role = _normalize_role(request.optimistic_speaker)
            return role, 0.2 if role else 0.0

        try:
            raw = self._redis.get(f"session:{request.session_id}:active")
        except Exception:
            raw = None

        payload: dict[str, Any] = {}
        captured_roles: set[str] = set()
        assignments: dict[str, str] = {}
        if raw:
            try:
                payload = json.loads(raw)
                samples = (
                    payload.get("speaker_role_check", {})
                    .get("samples", [])
                )
                for sample in samples:
                    role = _normalize_role(sample.get("role", ""))
                    if role:
                        captured_roles.add(role)
                raw_assignments = payload.get("speaker_role_assignments", {})
                if isinstance(raw_assignments, dict):
                    assignments = {
                        str(key): _normalize_role(str(value))
                        for key, value in raw_assignments.items()
                        if _normalize_role(str(value))
                    }
            except Exception:
                payload = {}
                captured_roles = set()
                assignments = {}

        if speaker_id and assignments.get(speaker_id):
            return assignments[speaker_id], 0.85

        if speaker_id and captured_roles:
            assigned_roles = set(assignments.values())
            preferred_order = ["Clinician", "Patient"]
            next_role = ""
            if not assignments and "Clinician" in captured_roles:
                next_role = "Clinician"
            else:
                for role in preferred_order:
                    if role in captured_roles and role not in assigned_roles:
                        next_role = role
                        break
            if next_role:
                assignments[speaker_id] = next_role
                self._persist_assignments(request.session_id, payload, assignments)
                confidence = 0.7 if len(assignments) == 1 and next_role == "Clinician" else 0.6
                return next_role, confidence

        optimistic_role = _normalize_role(request.optimistic_speaker)
        if optimistic_role and optimistic_role in captured_roles:
            return optimistic_role, 0.35
        if optimistic_role:
            return optimistic_role, 0.2
        if len(captured_roles) == 1:
            return next(iter(captured_roles)), 0.15
        return "", 0.0

    def _persist_assignments(
        self,
        session_id: str,
        payload: dict[str, Any],
        assignments: dict[str, str],
    ) -> None:
        if not self._redis:
            return
        try:
            payload["speaker_role_assignments"] = assignments
            payload["last_updated_at_ms"] = int(time.time() * 1000)
            self._redis.set(
                f"session:{session_id}:active",
                json.dumps(payload),
                ex=24 * 60 * 60,
            )
        except Exception:
            pass


class SpeechWorkerService:
    def __init__(self) -> None:
        provider_name = os.getenv("SPEECH_PROVIDER", "noop").strip().lower()
        redis_url = os.getenv("REDIS_URL")
        self.role_resolver = SessionRoleResolver(redis_url)

        if provider_name == "remote_http":
            self.provider: SpeechProvider = RemoteHTTPSpeechProvider(
                base_url=os.getenv("SPEECH_REMOTE_URL", ""),
                api_key=os.getenv("SPEECH_REMOTE_API_KEY"),
                timeout_s=float(os.getenv("SPEECH_REMOTE_TIMEOUT_SECONDS", "90")),
            )
        elif provider_name == "local_whisper_pyannote":
            self.provider = LocalWhisperPyannoteProvider()
        else:
            self.provider = NoOpSpeechProvider()

    def process_upload(
        self,
        request: SpeechSegmentRequest,
        file_name: str,
        payload: bytes,
        reference_samples: list[dict[str, Any]] | None = None,
    ) -> SpeechSegmentResult:
        suffix = Path(file_name).suffix or _suffix_from_mime(request.mime_type)
        with tempfile.NamedTemporaryFile(prefix="speech-segment-", suffix=suffix, delete=False) as tmp:
            tmp.write(payload)
            temp_path = Path(tmp.name)
        temp_references: list[ReferenceSample] = []

        try:
            for sample in reference_samples or []:
                role = _normalize_role(str(sample.get("role", "")))
                if not role:
                    continue
                sample_payload = sample.get("payload")
                if not isinstance(sample_payload, (bytes, bytearray)):
                    continue
                sample_mime = str(sample.get("mime_type", ""))
                sample_name = str(sample.get("file_name", "")) or f"{role.lower()}.wav"
                sample_suffix = Path(sample_name).suffix or _suffix_from_mime(sample_mime)
                with tempfile.NamedTemporaryFile(
                    prefix=f"speech-reference-{role.lower()}-",
                    suffix=sample_suffix,
                    delete=False,
                ) as ref_tmp:
                    ref_tmp.write(bytes(sample_payload))
                    temp_references.append(
                        ReferenceSample(
                            role=role,
                            file_name=sample_name,
                            mime_type=sample_mime,
                            temp_path=Path(ref_tmp.name),
                        )
                    )

            result = self.provider.process(request, temp_path, temp_references)
            if not result.speaker_role:
                result.speaker_role, result.role_confidence = self.role_resolver.resolve_role(
                    request,
                    result.speaker_id,
                )
            if result.status == "":
                result.status = "completed"
            return result
        except Exception as exc:  # noqa: BLE001
            return SpeechSegmentResult(
                session_id=request.session_id,
                segment_id=request.segment_id,
                status="failed",
                text=request.optimistic_text,
                speaker_id="SPEAKER_00",
                speaker_role=_normalize_role(request.optimistic_speaker),
                start_ms=request.started_at_ms,
                end_ms=request.ended_at_ms,
                source="speech_worker_error",
                error=str(exc),
            )
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            for sample in temp_references:
                try:
                    sample.temp_path.unlink(missing_ok=True)
                except Exception:
                    pass


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
    # avg_logprob is typically negative; squeeze into an approximate 0..1 range.
    return max(0.0, min(1.0, (mean + 5.0) / 5.0))


@lru_cache(maxsize=1)
def _get_embedding_inference():
    from app.models.registry import get_embedding_inference

    return get_embedding_inference()


def _flatten_embedding(value: Any) -> list[float]:
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


def _reference_field_name(role: str) -> str:
    normalized = _normalize_role(role)
    if normalized == "Clinician":
        return "reference_clinician"
    if normalized == "Patient":
        return "reference_patient"
    return "reference_unknown"


def _suffix_from_mime(mime_type: str) -> str:
    mime_type = (mime_type or "").lower()
    if "wav" in mime_type:
        return ".wav"
    if "webm" in mime_type:
        return ".webm"
    if "mpeg" in mime_type or "mp3" in mime_type:
        return ".mp3"
    return ".bin"
