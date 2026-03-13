import logging
from functools import lru_cache
from huggingface_hub import login
from unittest import case
from faster_whisper import WhisperModel
from pyannote.audio import Pipeline
from transformers import AutoModelForCausalLM, AutoTokenizer
import os

HUGGINGFACE_TOKEN = (
    os.environ.get("HUGGINGFACE_API_KEY")
    or os.environ.get("HF_TOKEN")
    or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
)
if not HUGGINGFACE_TOKEN:
    raise ValueError("HUGGINGFACE_API_KEY (or HF_TOKEN/HUGGINGFACEHUB_API_TOKEN) environment variable not set")

@lru_cache(maxsize=1)
def get_whisper_model():
    return WhisperModel(
        "large-v3", 
        device="cpu", 
        compute_type="int8"
    )

@lru_cache(maxsize=1)
def get_diarization_pipeline():
    try:
        login(token=HUGGINGFACE_TOKEN, add_to_git_credential=False)
        return Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
        )
    except Exception as exc:  # noqa: BLE001 - want to bubble up any auth/download issue with context
        token_hint = f"{HUGGINGFACE_TOKEN[:4]}..." if HUGGINGFACE_TOKEN else "None"
        logging.exception("Failed to load pyannote/speaker-diarization with token prefix %s", token_hint)
        raise


#update to select LLM model based on environment variable

    
@lru_cache(maxsize=1)
def get_llm_client():
    # Default to "api" placeholder client to avoid loading large local models unless requested.
    llm_model = os.environ.get("LLM_MODEL", "local")

    if llm_model == "local":
        model_name = "microsoft/Phi-3-mini-4k-instruct"

        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto"   # IMPORTANT
        )

        return {
            "type": "local",
            "model": model,
            "tokenizer": tokenizer
        }
    elif llm_model == "api":
        # Placeholder API client; replace with real remote LLM wiring when available.
       
            from groq import Groq
            groq_api_key = os.environ.get("GROQ_API_KEY")
            if not groq_api_key:
                raise ValueError("GROQ_API_KEY environment variable not set for Groq API LLM client")
            client = Groq(
                api_key= groq_api_key
            )

            return {
                "type": "api",
                "model": client,
                "api_key": groq_api_key
            }
    else:
        raise ValueError(f"Unsupported LLM_MODEL: {llm_model}")
