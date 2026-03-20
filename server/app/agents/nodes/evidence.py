"""
Retrieve Evidence Node — Layer 2 evidence retrieval.

Supports two modes:
  1. pgvector cosine search (preferred): O(log n) via embedding_service
  2. SequenceMatcher fuzzy matching (fallback): O(n*m), no DB required

The node automatically selects pgvector when an EmbeddingService is available
in the AgentContext, falling back to SequenceMatcher otherwise.
"""

import logging
from ..config import AgentContext
from ..state import GraphState, CandidateFact, ChunkArtifact, EvidenceItem
from datetime import datetime
from typing import List, Dict, Optional
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


# Fuzzy matching threshold
FUZZY_MATCH_THRESHOLD = 0.6  # 60% similarity


def normalize_text_for_matching(text: str) -> str:
    """
    Normalize text for fuzzy matching.

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    # Convert to lowercase, remove extra spaces
    normalized = text.lower().strip()
    normalized = ' '.join(normalized.split())
    return normalized


def fuzzy_similarity(text1: str, text2: str) -> float:
    """
    Calculate fuzzy similarity between two text strings using SequenceMatcher.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score (0.0 to 1.0)
    """
    norm_text1 = normalize_text_for_matching(text1)
    norm_text2 = normalize_text_for_matching(text2)

    return SequenceMatcher(None, norm_text1, norm_text2).ratio()


def fact_to_search_string(fact: CandidateFact) -> str:
    """
    Convert a candidate fact to a search string.

    Args:
        fact: Candidate fact

    Returns:
        Search string
    """
    fact_type = fact.get('type', '')
    fact_value = fact.get('value', '')

    # Convert value to string
    if isinstance(fact_value, dict):
        # Extract meaningful fields from dict
        value_parts = []
        for key, val in fact_value.items():
            if val:
                value_parts.append(f"{key}: {val}")
        value_str = ', '.join(value_parts)
    elif isinstance(fact_value, list):
        value_str = ', '.join(str(v) for v in fact_value)
    else:
        value_str = str(fact_value)

    # Combine type and value
    search_string = f"{fact_type} {value_str}"
    return search_string


def find_matching_chunks(
    fact: CandidateFact,
    chunks: List[ChunkArtifact],
    threshold: float = FUZZY_MATCH_THRESHOLD
) -> List[tuple]:
    """
    Find chunks that match a candidate fact using fuzzy matching.

    Args:
        fact: Candidate fact
        chunks: List of chunk artifacts
        threshold: Minimum similarity threshold

    Returns:
        List of (chunk, similarity_score) tuples, sorted by score
    """
    search_string = fact_to_search_string(fact)
    matches = []

    for chunk in chunks:
        chunk_text = chunk.get('text', '')

        if not chunk_text.strip():
            continue

        # Calculate similarity
        similarity = fuzzy_similarity(search_string, chunk_text)

        if similarity >= threshold:
            matches.append((chunk, similarity))

        # Also check for exact substring match (case-insensitive)
        if search_string.lower() in chunk_text.lower():
            # Boost score for exact matches
            matches.append((chunk, max(similarity, 0.9)))

    # Remove duplicates and sort by similarity (highest first)
    unique_matches = {}
    for chunk, score in matches:
        chunk_id = chunk['chunk_id']
        if chunk_id not in unique_matches or score > unique_matches[chunk_id][1]:
            unique_matches[chunk_id] = (chunk, score)

    sorted_matches = sorted(unique_matches.values(), key=lambda x: x[1], reverse=True)

    return sorted_matches


def create_evidence_item(chunk: ChunkArtifact, confidence: float) -> EvidenceItem:
    """
    Create an evidence item from a chunk.

    Args:
        chunk: Chunk artifact
        confidence: Confidence score

    Returns:
        Evidence item
    """
    # Extract snippet (limit to 200 characters)
    snippet = chunk['text']
    if len(snippet) > 200:
        snippet = snippet[:197] + "..."

    evidence: EvidenceItem = {
        'source_id': chunk['source_id'],
        'source_type': chunk['source'],
        'snippet': snippet,
        'confidence': confidence,
        'metadata': {
            'chunk_id': chunk['chunk_id'],
            'full_text': chunk['text'],
            'start': chunk.get('start'),
            'end': chunk.get('end'),
            'original_metadata': chunk.get('metadata', {})
        }
    }

    return evidence


def retrieve_evidence_node(state: GraphState, ctx: AgentContext) -> GraphState:
    """
    Retrieve supporting evidence for candidate facts.

    Layer 2 — Record-time evidence check:
      - If EmbeddingService is available, uses pgvector cosine search (O(log n))
      - Otherwise falls back to SequenceMatcher fuzzy matching (O(n*m))

    For each candidate fact:
    - Find source spans in chunks using similarity search
    - Calculate confidence scores based on similarity
    - Store evidence in evidence_map
    - Fall back to full transcript if no specific span found

    Args:
        state: Current graph state
        ctx: AgentContext with optional embedding_service

    Returns:
        Updated state with populated evidence_map
    """
    candidate_facts = state.get('candidate_facts', [])
    chunks = state.get('chunks', [])
    conversation_log = state.get('conversation_log', [])
    session_id = state.get('session_id', '')

    if not candidate_facts:
        state['controls']['trace_log'].append({
            'node': 'retrieve_evidence',
            'action': 'skipped',
            'reason': 'no_candidate_facts',
            'timestamp': datetime.now().isoformat()
        })
        return state

    # Decide strategy: pgvector or fallback
    use_vector_search = (
        ctx is not None
        and ctx.embedding_service is not None
        and session_id
    )

    # Check for hybrid retrieval service on context (RAG enhancement)
    use_hybrid = (
        use_vector_search
        and hasattr(ctx, "hybrid_retrieval_service")
        and ctx.hybrid_retrieval_service is not None
    )

    evidence_map: Dict[str, List[EvidenceItem]] = {}
    facts_with_evidence = 0
    facts_without_evidence = 0

    if use_hybrid:
        logger.info("[Evidence] Using hybrid retrieval (dense + sparse)")
        evidence_map, facts_with_evidence, facts_without_evidence = (
            _retrieve_via_hybrid(
                candidate_facts, chunks, conversation_log,
                session_id, ctx
            )
        )
    elif use_vector_search:
        logger.info("[Evidence] Using pgvector cosine search")
        evidence_map, facts_with_evidence, facts_without_evidence = (
            _retrieve_via_embeddings(
                candidate_facts, chunks, conversation_log,
                session_id, ctx
            )
        )
    else:
        logger.info("[Evidence] Using SequenceMatcher fallback")
        evidence_map, facts_with_evidence, facts_without_evidence = (
            _retrieve_via_fuzzy_match(candidate_facts, chunks, conversation_log)
        )

    # Update state
    state['evidence_map'] = evidence_map

    # Log the operation
    strategy_name = 'hybrid' if use_hybrid else ('pgvector' if use_vector_search else 'fuzzy_match')
    state['controls']['trace_log'].append({
        'node': 'retrieve_evidence',
        'action': 'retrieved',
        'strategy': strategy_name,
        'total_facts': len(candidate_facts),
        'facts_with_evidence': facts_with_evidence,
        'facts_without_evidence': facts_without_evidence,
        'total_evidence_items': sum(len(items) for items in evidence_map.values()),
        'timestamp': datetime.now().isoformat()
    })

    return state


def _retrieve_via_hybrid(
    candidate_facts: List[CandidateFact],
    chunks: List[ChunkArtifact],
    conversation_log: list,
    session_id: str,
    ctx: AgentContext,
) -> tuple:
    """Layer 2 -- hybrid retrieval (dense + sparse) for evidence."""
    evidence_map: Dict[str, List[EvidenceItem]] = {}
    facts_with = 0
    facts_without = 0

    hybrid_service = ctx.hybrid_retrieval_service

    for fact in candidate_facts:
        fact_id = fact['fact_id']
        search_text = fact_to_search_string(fact)

        try:
            matches = hybrid_service.search_chunks(
                session_id=session_id,
                query=search_text,
                top_k=5,
                dense_threshold=0.45,
            )

            if matches:
                evidence_items = []
                for match in matches:
                    snippet = match.get('chunk_text', '')
                    if len(snippet) > 200:
                        snippet = snippet[:197] + "..."

                    evidence_item: EvidenceItem = {
                        'source_id': match.get('chunk_id', ''),
                        'source_type': match.get('source_type', 'unknown'),
                        'snippet': snippet,
                        'confidence': match.get('rrf_score', match.get('similarity', 0.0)),
                        'metadata': {
                            'chunk_id': match.get('chunk_id', ''),
                            'full_text': match.get('chunk_text', ''),
                            'start': match.get('start_time'),
                            'end': match.get('end_time'),
                            'retrieval': 'hybrid',
                            'rrf_score': match.get('rrf_score'),
                        }
                    }
                    evidence_items.append(evidence_item)

                evidence_map[fact_id] = evidence_items
                facts_with += 1
            else:
                evidence_map[fact_id] = _fallback_evidence(conversation_log)
                facts_without += 1

        except Exception as e:
            logger.warning(f"[Evidence] Hybrid search failed for fact {fact_id}: {e}")
            # Fall back to fuzzy matching for this fact
            fm_matches = find_matching_chunks(fact, chunks, threshold=FUZZY_MATCH_THRESHOLD)
            if fm_matches:
                evidence_map[fact_id] = [
                    create_evidence_item(chunk, sim) for chunk, sim in fm_matches[:5]
                ]
                facts_with += 1
            else:
                evidence_map[fact_id] = _fallback_evidence(conversation_log)
                facts_without += 1

    return evidence_map, facts_with, facts_without


def _retrieve_via_embeddings(
    candidate_facts: List[CandidateFact],
    chunks: List[ChunkArtifact],
    conversation_log: list,
    session_id: str,
    ctx: AgentContext,
) -> tuple:
    """Layer 2 — pgvector cosine search for evidence retrieval."""
    evidence_map: Dict[str, List[EvidenceItem]] = {}
    facts_with = 0
    facts_without = 0

    for fact in candidate_facts:
        fact_id = fact['fact_id']
        search_text = fact_to_search_string(fact)

        try:
            query_vec = ctx.embedding_service.embed_text(search_text)
            matches = ctx.embedding_service.search_similar_chunks(
                session_id=session_id,
                query_embedding=query_vec,
                top_k=5,
                threshold=0.45,
            )

            if matches:
                evidence_items = []
                for match in matches:
                    snippet = match['chunk_text']
                    if len(snippet) > 200:
                        snippet = snippet[:197] + "..."

                    evidence_item: EvidenceItem = {
                        'source_id': match['chunk_id'],
                        'source_type': match['source_type'],
                        'snippet': snippet,
                        'confidence': match['similarity'],
                        'metadata': {
                            'chunk_id': match['chunk_id'],
                            'full_text': match['chunk_text'],
                            'start': match.get('start_time'),
                            'end': match.get('end_time'),
                            'retrieval': 'pgvector',
                        }
                    }
                    evidence_items.append(evidence_item)

                evidence_map[fact_id] = evidence_items
                facts_with += 1
            else:
                # Fallback to transcript context
                evidence_map[fact_id] = _fallback_evidence(conversation_log)
                facts_without += 1

        except Exception as e:
            logger.warning(f"[Evidence] pgvector search failed for fact {fact_id}: {e}")
            # Fall back to fuzzy matching for this fact
            fm_matches = find_matching_chunks(fact, chunks, threshold=FUZZY_MATCH_THRESHOLD)
            if fm_matches:
                evidence_map[fact_id] = [
                    create_evidence_item(chunk, sim) for chunk, sim in fm_matches[:5]
                ]
                facts_with += 1
            else:
                evidence_map[fact_id] = _fallback_evidence(conversation_log)
                facts_without += 1

    return evidence_map, facts_with, facts_without


def _retrieve_via_fuzzy_match(
    candidate_facts: List[CandidateFact],
    chunks: List[ChunkArtifact],
    conversation_log: list,
) -> tuple:
    """Original O(n*m) SequenceMatcher evidence retrieval (fallback)."""
    evidence_map: Dict[str, List[EvidenceItem]] = {}
    facts_with = 0
    facts_without = 0

    for fact in candidate_facts:
        fact_id = fact['fact_id']
        matches = find_matching_chunks(fact, chunks, threshold=FUZZY_MATCH_THRESHOLD)

        if matches:
            evidence_items = [
                create_evidence_item(chunk, similarity)
                for chunk, similarity in matches[:5]
            ]
            evidence_map[fact_id] = evidence_items
            facts_with += 1
        else:
            evidence_map[fact_id] = _fallback_evidence(conversation_log)
            facts_without += 1

    return evidence_map, facts_with, facts_without


def _fallback_evidence(conversation_log: list) -> List[EvidenceItem]:
    """Build fallback evidence from conversation log."""
    full_transcript_parts = []
    for turn in conversation_log[:3]:
        for segment in turn.get('segments', []):
            text = segment.get('cleaned_text') or segment.get('raw_text', '')
            if text:
                full_transcript_parts.append(text)

    if full_transcript_parts:
        full_text = ' '.join(full_transcript_parts)
        snippet = full_text[:200] + "..." if len(full_text) > 200 else full_text
        return [{
            'source_id': 'full_transcript',
            'source_type': 'transcript',
            'snippet': snippet,
            'confidence': 0.3,
            'metadata': {
                'fallback': True,
                'reason': 'no_specific_match_found',
                'full_text': full_text
            }
        }]
    return []
