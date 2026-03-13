from ..state import GraphState, ChunkArtifact, ConversationTurn, DocumentArtifact
from datetime import datetime
from typing import List
import uuid


# Chunk configuration
CHUNK_SIZE = 500  # characters (roughly 100-125 tokens)
CHUNK_OVERLAP = 50  # characters


def create_chunk_id() -> str:
    """Generate unique chunk ID."""
    return f"chunk_{uuid.uuid4().hex[:12]}"


def recursive_text_splitter(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Recursively split text into chunks, attempting to preserve sentence boundaries.

    Args:
        text: Input text to chunk
        chunk_size: Maximum chunk size in characters
        overlap: Number of overlapping characters between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0

    # Separators to try in order (preserve semantic boundaries)
    separators = ['\n\n', '\n', '. ', '? ', '! ', '; ', ', ', ' ']

    while start < len(text):
        end = start + chunk_size

        if end >= len(text):
            # Last chunk
            chunks.append(text[start:].strip())
            break

        # Try to find a good split point using separators
        split_point = None
        for separator in separators:
            # Look for separator within the chunk
            search_end = min(end, len(text))
            last_sep = text[start:search_end].rfind(separator)

            if last_sep != -1 and last_sep > chunk_size // 2:  # At least halfway through
                split_point = start + last_sep + len(separator)
                break

        if split_point is None:
            # No good separator found, split at chunk_size
            split_point = end

        # Extract chunk
        chunk_text = text[start:split_point].strip()
        if chunk_text:
            chunks.append(chunk_text)

        # Move start forward with overlap
        start = split_point - overlap

    return chunks


def chunk_conversation_log(conversation_log: List[ConversationTurn]) -> List[ChunkArtifact]:
    """
    Create semantic chunks from conversation log.

    Args:
        conversation_log: List of conversation turns

    Returns:
        List of chunk artifacts
    """
    chunks: List[ChunkArtifact] = []

    for turn in conversation_log:
        timestamp = turn['timestamp']
        segments = turn['segments']

        # Combine all segments in this turn
        for segment in segments:
            text = segment.get('cleaned_text') or segment.get('raw_text', '')
            speaker = segment.get('speaker', 'Unknown')

            if not text.strip():
                continue

            # Split text into chunks
            text_chunks = recursive_text_splitter(text, CHUNK_SIZE, CHUNK_OVERLAP)

            for chunk_text in text_chunks:
                chunk: ChunkArtifact = {
                    'chunk_id': create_chunk_id(),
                    'source': 'transcript',
                    'source_id': f"turn_{timestamp}_{speaker}",
                    'text': chunk_text,
                    'start': segment.get('start'),
                    'end': segment.get('end'),
                    'metadata': {
                        'speaker': speaker,
                        'timestamp': timestamp,
                        'confidence': segment.get('confidence'),
                        'uncertainties': segment.get('uncertainties', [])
                    }
                }
                chunks.append(chunk)

    return chunks


def chunk_documents(documents: List[DocumentArtifact]) -> List[ChunkArtifact]:
    """
    Create semantic chunks from document artifacts.

    Args:
        documents: List of document artifacts

    Returns:
        List of chunk artifacts
    """
    chunks: List[ChunkArtifact] = []

    for doc in documents:
        extracted_text = doc.get('extracted_text', '')

        if not extracted_text.strip():
            continue

        # Split text into chunks
        text_chunks = recursive_text_splitter(extracted_text, CHUNK_SIZE, CHUNK_OVERLAP)

        for idx, chunk_text in enumerate(text_chunks):
            chunk: ChunkArtifact = {
                'chunk_id': create_chunk_id(),
                'source': 'document',
                'source_id': doc['document_id'],
                'text': chunk_text,
                'start': None,
                'end': None,
                'metadata': {
                    'document_id': doc['document_id'],
                    'source_type': doc['source_type'],
                    'chunk_index': idx,
                    'total_chunks': len(text_chunks),
                    'has_tables': len(doc.get('tables', [])) > 0,
                    'original_metadata': doc.get('metadata', {})
                }
            }
            chunks.append(chunk)

    return chunks


def segment_and_chunk_node(state: GraphState) -> GraphState:
    """
    Create semantic chunks from transcript and document artifacts.

    Uses recursive character text splitting with:
    - Chunk size: 500 characters (~100-125 tokens)
    - Overlap: 50 characters
    - Preserves conversation context boundaries
    - Tags chunks with speaker and timestamp metadata

    Args:
        state: Current graph state

    Returns:
        Updated state with populated chunks
    """
    conversation_log = state.get('conversation_log', [])
    documents = state.get('documents', [])

    all_chunks: List[ChunkArtifact] = []

    # Process conversation log
    if conversation_log:
        transcript_chunks = chunk_conversation_log(conversation_log)
        all_chunks.extend(transcript_chunks)

    # Process documents
    if documents:
        document_chunks = chunk_documents(documents)
        all_chunks.extend(document_chunks)

    # Update state
    state['chunks'] = all_chunks

    # Log the operation
    state['controls']['trace_log'].append({
        'node': 'segment_and_chunk',
        'action': 'chunked',
        'transcript_chunks': len([c for c in all_chunks if c['source'] == 'transcript']),
        'document_chunks': len([c for c in all_chunks if c['source'] == 'document']),
        'total_chunks': len(all_chunks),
        'timestamp': datetime.now().isoformat()
    })

    return state
