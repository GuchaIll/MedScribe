import json
import logging
import os
from ..state import GraphState, TranscriptSegment
from ..config import AgentContext

logger = logging.getLogger(__name__)

# ── Prompts ────────────────────────────────────────────────────────────────

_SINGLE_PROMPT = """You are a medical transcription cleaning engine.

Rules:
- Ensure clarity and readability.
- Do not change clinical meaning.
- Do not infer diagnoses or facts.
- Preserve original phrasing where possible.
- Fix grammar, punctuation, and formatting only.
- If a phrase is unclear, mark it as uncertain.

Return JSON:
{
    "cleaned_text": string,
    "uncertainties": string[]
}"""

_BATCH_PROMPT = """You are a medical transcription cleaning engine.

Rules:
- Ensure clarity and readability.
- Do not change clinical meaning.
- Do not infer diagnoses or facts.
- Preserve original phrasing where possible.
- Fix grammar, punctuation, and formatting only.
- If a phrase is unclear, mark it as uncertain.

You will receive multiple segments. Clean each one independently.
Return a JSON object with a "segments" array, one entry per input segment,
in the SAME order:
{
    "segments": [
        {"cleaned_text": string, "uncertainties": string[]},
        ...
    ]
}"""

# Maximum segments per single batched LLM call
_BATCH_SIZE = 5


def clean_transcription_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Clean transcription segments using the LLM.

    Batches up to 5 segments per LLM call to reduce latency.
    Falls back to single-segment calls if batch parsing fails.
    """
    logger.info("Running Cleaning transcription segments")

    state = state.copy()

    if not state["conversation_log"]:
        return state

    latest_segment = state["conversation_log"][-1]
    segments = latest_segment["segments"]

    if not segments:
        return state

    # Get LLM from context singleton
    llm = ctx.llm if ctx and ctx.llm else None
    if llm is None and ctx and ctx.llm_factory:
        llm = ctx.llm_factory()

    # ── Try batched cleaning first ──────────────────────────────────────────
    cleaned_segments = _clean_batch(segments, llm)

    state["conversation_log"][-1] = {
        "timestamp": latest_segment["timestamp"],
        "segments": cleaned_segments,
    }

    # Log to agent actions file
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "agent_actions.log"), "a", encoding="utf-8") as f:
        f.write(
            f"\n[Clean Transcription Node] Cleaned {len(cleaned_segments)} segments "
            f"at timestamp {latest_segment['timestamp']}\n"
        )
        f.write(f"Prior Segments: {latest_segment['segments']}\n")
        f.write(f"Cleaned Segments: {cleaned_segments}\n")

    return state


# ── Internal helpers ────────────────────────────────────────────────────────

def _clean_batch(segments: list, llm=None) -> list:
    """
    Clean segments in batches of up to _BATCH_SIZE per LLM call.

    Falls back to one-by-one cleaning if a batch fails to parse.
    """
    cleaned: list = []

    for i in range(0, len(segments), _BATCH_SIZE):
        batch = segments[i : i + _BATCH_SIZE]

        if len(batch) == 1:
            # Single segment — use the simpler prompt directly
            cleaned.append(_clean_single(batch[0], llm))
            continue

        # Build numbered input for the batch
        numbered_input = "\n".join(
            f"Segment {idx + 1}:\n{seg['raw_text']}"
            for idx, seg in enumerate(batch)
        )

        try:
            if llm is None:
                from ...models.llm import LLMClient
                llm = LLMClient()
            response = llm.generate_response(
                _BATCH_PROMPT + f"\n\n{numbered_input}\n",
                max_tokens=300,
            )
            logger.debug("Batch LLM response: %s", response)

            parsed = json.loads(response)
            results = parsed.get("segments", [])

            if len(results) == len(batch):
                for seg, result in zip(batch, results):
                    cleaned.append({
                        **seg,
                        "cleaned_text": result.get("cleaned_text", seg["raw_text"]),
                        "uncertainties": result.get("uncertainties", []),
                    })
                continue  # success — move to next batch

            # Length mismatch — fall through to single
            logger.warning(
                "Batch LLM returned %d results for %d segments — falling back to single",
                len(results), len(batch),
            )
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Batch clean failed (%s) — falling back to single-segment", e)

        # Fallback: process each segment individually
        for seg in batch:
            cleaned.append(_clean_single(seg, llm))

    return cleaned


def _clean_single(seg: dict, llm=None) -> dict:
    """Clean a single segment via one LLM call."""
    try:
        if llm is None:
            from ...models.llm import LLMClient
            llm = LLMClient()
        response = llm.generate_response(
            _SINGLE_PROMPT + f"\nTranscription Segment:\n{seg['raw_text']}\n",
            max_tokens=200,
        )
        logger.debug("LLM returned response: %s", response)
        result = json.loads(response)
    except (json.JSONDecodeError, Exception):
        result = {
            "cleaned_text": seg["raw_text"],
            "uncertainties": ["LLM response could not be parsed as JSON."],
        }

    return {
        **seg,
        "cleaned_text": result.get("cleaned_text", seg["raw_text"]),
        "uncertainties": result.get("uncertainties", []),
    }


