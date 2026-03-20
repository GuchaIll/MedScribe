import logging
from functools import lru_cache
import os

# Heavy ML packages — guarded so the server starts in Docker/CPU environments
# that don't have PyTorch or pyannote installed. Each function checks availability
# before use and raises a clear error.
try:
    from huggingface_hub import login as _hf_login
    _HF_HUB_AVAILABLE = True
except ImportError:
    _HF_HUB_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _FASTER_WHISPER_AVAILABLE = False

try:
    from pyannote.audio import Pipeline as _PyAnnotePipeline
    _PYANNOTE_AVAILABLE = True
except ImportError:
    _PYANNOTE_AVAILABLE = False

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _TRANSFORMERS_AVAILABLE = False


def _get_huggingface_token():
    """Get HuggingFace token from environment variables."""
    return (
        os.environ.get("HUGGINGFACE_API_KEY")
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    )

@lru_cache(maxsize=1)
def get_whisper_model():
    if not _FASTER_WHISPER_AVAILABLE:
        raise ImportError(
            "faster-whisper is not installed. "
            "Install it with: pip install faster-whisper"
        )
    return WhisperModel(
        "large-v3",
        device="cpu",
        compute_type="int8"
    )

@lru_cache(maxsize=1)
def get_diarization_pipeline():
    if not _PYANNOTE_AVAILABLE:
        raise ImportError(
            "pyannote.audio is not installed. "
            "Install it with: pip install pyannote.audio"
        )
    if not _HF_HUB_AVAILABLE:
        raise ImportError("huggingface_hub is not installed.")
    token = _get_huggingface_token()
    if not token:
        raise ValueError(
            "HUGGINGFACE_API_KEY (or HF_TOKEN/HUGGINGFACEHUB_API_TOKEN) environment variable not set. "
            "Required for pyannote speaker diarization. Get a token at: https://huggingface.co/settings/tokens"
        )
    try:
        _hf_login(token=token, add_to_git_credential=False)
        return _PyAnnotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
        )
    except Exception as exc:  # noqa: BLE001 - want to bubble up any auth/download issue with context
        token_hint = f"{token[:4]}..." if token else "None"
        logging.exception("Failed to load pyannote/speaker-diarization with token prefix %s", token_hint)
        raise


# Select LLM model based on environment variable
@lru_cache(maxsize=1)
def get_llm_client():
    # Default to "api" placeholder client to avoid loading large local models unless requested.
    llm_model = os.environ.get("LLM_MODEL", "local")

    if llm_model == "local":
        if not _TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "transformers is not installed. "
                "Set LLM_MODEL=api in your environment and use the Groq API instead."
            )
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
        from groq import Groq
        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable not set for Groq API LLM client")
        client = Groq(api_key=groq_api_key)
        return {
            "type": "api",
            "model": client,
            "api_key": groq_api_key,
        }
    else:
        raise ValueError(f"Unsupported LLM_MODEL: {llm_model}")
