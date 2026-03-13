import os
import uuid
from datetime import datetime
from time import time
from ..state import GraphState, TranscriptSegment, DocumentArtifact, ChunkArtifact


def ingest_transcript_node(state: GraphState) -> GraphState:
    """Ingests raw transcript segments into the conversation log if any are present"""
    print("Running Ingest transcription segments")
    state = state.copy()
    new_segments = state.pop("new_segments", None)

    if not new_segments:
        return state
    
    timestamp = time()

    state.setdefault("conversation_log", []).append({
        "timestamp": timestamp,
        "segments": new_segments,
    })

    _log_segments_to_file(state["session_id"], new_segments, timestamp)

    # Log to agent actions file
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "agent_actions.log"), "a", encoding="utf-8") as f:
        f.write(f"\n[Ingest Node] Ingested {len(new_segments)} segments at timestamp {timestamp}\n")
        f.write(f"Segments: {new_segments}\n")

    # ── Document ingestion branch ───────────────────────────────────────
    # If documents have been attached via the OCR pipeline, convert each
    # DocumentArtifact into ChunkArtifact(s) with source="document" so the
    # downstream extract / evidence / fill_record nodes can consume them.
    documents: list = state.get("documents", [])
    if documents:
        chunks = state.setdefault("chunks", [])
        candidate_facts = state.setdefault("candidate_facts", [])

        for doc in documents:
            doc_text = doc.get("extracted_text", "")
            doc_id = doc.get("document_id", str(uuid.uuid4()))
            metadata = doc.get("metadata", {})

            if not doc_text:
                continue

            # Split document text into ~500-char chunks for parity with
            # transcript chunks produced by the segment node.
            for i, start in enumerate(range(0, len(doc_text), 500)):
                chunk_text = doc_text[start : start + 500]
                chunk_id = f"doc_{doc_id}_{i}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "source": "document",
                    "source_id": doc_id,
                    "text": chunk_text,
                    "start": None,
                    "end": None,
                    "metadata": {
                        "original_filename": metadata.get("original_filename", ""),
                        "document_type": metadata.get("document_type", "unknown"),
                        "page_count": metadata.get("page_count", 0),
                        "chunk_index": i,
                    },
                })

            print(f"[Ingest] Ingested document {doc_id}: "
                  f"{len(doc_text)} chars → {len(range(0, len(doc_text), 500))} chunks")

        # Log document ingestion
        with open(os.path.join(log_dir, "agent_actions.log"), "a", encoding="utf-8") as f:
            f.write(f"[Ingest Node] Ingested {len(documents)} documents → {len(chunks)} total chunks\n")

    return state

def _log_segments_to_file(session_id: str, segments: list[TranscriptSegment], timestamp: float):
    """Helper to log ingested segments to a file for auditing/debugging."""
    print(f"Logging segments to file for session {session_id} at {datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')}")

    # Use path relative to server directory
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    filename = os.path.join(log_dir, f"session_{session_id}_transcript.log")
    
    print(f"Writing to: {filename}")
    
    with open(filename, "a", encoding="utf-8") as f:
        dt = datetime.fromtimestamp(timestamp)
        f.write(f"\n{'='*60}\n")
        f.write(f"Timestamp: {dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*60}\n\n")
    
        for seg in segments:
            f.write(f"[{seg['start']:.2f}s - {seg['end']:.2f}s] ")
            if seg.get('speaker'):
                f.write(f"{seg['speaker']}: ")
            f.write(f"{seg['raw_text']}")
            if seg.get('confidence'):
                f.write(f" (confidence: {seg['confidence']})")
            f.write("\n")

    