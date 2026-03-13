from faster_whisper import WhisperModel

import numpy as np
import soundfile as sf
import spaces
import xxhash
from dataclasses import dataclass, field 
import os
from typing import Any
from pyannote import Pipeline
from .registry import get_whisper_model, get_diarization_pipeline

# api_key = os.environ.get("OPENAI_API_KEY")
# if not api_key:
#     raise ValueError("OPENAI_API_KEY environment variable not set")


class AppState:
    converstation_history: list = field(default_factory=list)
    stopped: bool = False
    model_response: Any = None

class SSTClient:
    def __init__(self):
        self.whisper = get_whisper_model()
        self.diarizer = get_diarization_pipeline()

    def transcribe_audio(self, audio_path: str) -> tuple:

        assert os.path.exists(audio_path), f"Audio file {audio_path} does not exist."

        segments, info = self.whisper.transcribe(
            audio_path, 
            beam_size=5, 
            word_timestamps=True
        )
      
        return segments, info
    
    def whisper_to_verbose_json(self, segments, info) -> dict:
        verbose_json = {
            "language": info.language,
            "duration": info.duration,
            "segments": []
        }
        for segment in segments:
            segment_dict = {
                "id": segment.id,
                "seek": segment.seek,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "tokens": segment.tokens,
                "token_timestamps": [
                    {
                        "token": token.token,
                        "start": token.start,
                        "end": token.end
                    } for token in segment.token_timestamps
                ]
            }
            verbose_json["segments"].append(segment_dict)
        return verbose_json
    
    def diarize_audio(self, audio_path: str) -> dict:
        assert os.path.exists(audio_path), f"Audio file {audio_path} does not exist."
        diarization = self.pipeline(audio_path)
        diarization_result = {}
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            diarization_result.setdefault(speaker, []).append({
                "start": turn.start,
                "end": turn.end
            })
        return diarization_result