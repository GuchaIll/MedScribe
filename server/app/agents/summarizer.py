import os
from datetime import datetime
from time import time

from app.models.llm import LLMClient
from .state import GraphState, TranscriptSegment

def summarize_transcript_node(state: GraphState) -> GraphState:
    """Summarizes the entire conversation log into a concise session summary."""
    print("Running Summarization of transcription segments")
    state = state.copy()
    
    if not state["conversation_log"]:
        state["session_summary"] = "No conversation data available."
        return state
    
    full_transcript = ""
    for entry in state["conversation_log"]:
        for seg in entry["segments"]:
            full_transcript += seg.get("cleaned_text", seg["raw_text"]) + " "
    
    prompts = """You are a medical transcription summarization engine.

    Rules:
    - Summarize the key points of the conversation.
    - Do not add any new information.
    - Keep it concise and clinically relevant.
    Return a single string summary."""

    llm = LLMClient()
    response = llm.generate_response(prompts + f"\nFull Transcript:\n{full_transcript}\n")

    state["session_summary"] = response.strip()
    return state