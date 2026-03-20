"""
Hybrid Retrieval Service -- combines dense vector search with sparse keyword search.

Provides Reciprocal Rank Fusion (RRF) to merge results from:
  - Dense: pgvector cosine-distance search (BioLord-2023-M embeddings)
  - Sparse: PostgreSQL tsvector/tsquery full-text search (GIN-indexed)

This replaces single-pass dense-only retrieval for both the AssistantService
and the evidence retrieval node, yielding higher recall for exact clinical
terms (drug names, lab codes, ICD codes) that dense models tend to miss.

Usage:
    from app.services.hybrid_retrieval import HybridRetrievalService
    hybrid = HybridRetrievalService(db, embedding_service)
    results = hybrid.search_chunks(session_id, query, top_k=6)
    facts   = hybrid.search_patient_facts(patient_id, query, top_k=10)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)

# Reciprocal Rank Fusion constant (standard value from Cormack et al.)
RRF_K = 60

# Default thresholds
DENSE_THRESHOLD = 0.30      # Minimum cosine similarity for dense results
KEYWORD_MIN_LENGTH = 2      # Minimum token length for keyword search


class HybridRetrievalService:
    """
    Combines dense vector search with sparse keyword search via RRF fusion.

    The service queries both retrieval paths in parallel, then merges
    results using Reciprocal Rank Fusion (RRF), which is robust to
    score-scale differences between retrievers.
    """

    def __init__(
        self,
        db: DBSession,
        embedding_service: Any,  # EmbeddingService (avoid circular import)
        rrf_k: int = RRF_K,
        dense_threshold: float = DENSE_THRESHOLD,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.rrf_k = rrf_k
        self.dense_threshold = dense_threshold
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight

    # ── Public API ───────────────────────────────────────────────────────────

    def search_chunks(
        self,
        session_id: str,
        query: str,
        top_k: int = 6,
        dense_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search against chunk_embeddings for a specific session.

        Returns top-k chunks ranked by RRF fusion of dense + sparse scores.
        """
        threshold = dense_threshold or self.dense_threshold

        # 1. Dense retrieval (pgvector cosine)
        dense_results = self._dense_chunk_search(session_id, query, top_k * 2, threshold)

        # 2. Sparse retrieval (tsvector keyword)
        sparse_results = self._sparse_chunk_search(session_id, query, top_k * 2)

        # 3. RRF fusion
        fused = self._rrf_fuse(dense_results, sparse_results, id_key="chunk_id")

        return fused[:top_k]

    def search_chunks_for_patient(
        self,
        patient_id: str,
        query: str,
        top_k: int = 6,
        dense_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search against chunk_embeddings across all sessions for a patient.
        """
        threshold = dense_threshold or self.dense_threshold

        dense_results = self._dense_patient_chunk_search(
            patient_id, query, top_k * 2, threshold
        )
        sparse_results = self._sparse_patient_chunk_search(
            patient_id, query, top_k * 2
        )

        fused = self._rrf_fuse(dense_results, sparse_results, id_key="chunk_id")
        return fused[:top_k]

    def search_patient_facts(
        self,
        patient_id: str,
        query: str,
        top_k: int = 10,
        fact_type: Optional[str] = None,
        only_final: bool = True,
        dense_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search against clinical_embeddings for a patient.
        """
        threshold = dense_threshold or self.dense_threshold

        dense_results = self._dense_fact_search(
            patient_id, query, top_k * 2, threshold,
            fact_type=fact_type, only_final=only_final,
        )
        sparse_results = self._sparse_fact_search(
            patient_id, query, top_k * 2,
            fact_type=fact_type, only_final=only_final,
        )

        fused = self._rrf_fuse(dense_results, sparse_results, id_key="id")
        return fused[:top_k]

    # ── Dense retrieval (pgvector cosine) ────────────────────────────────────

    def _dense_chunk_search(
        self, session_id: str, query: str, top_k: int, threshold: float
    ) -> List[Dict[str, Any]]:
        """Dense cosine search on chunk_embeddings for a session."""
        try:
            query_vec = self.embedding_service.embed_text(query)
            return self.embedding_service.search_similar_chunks(
                session_id=session_id,
                query_embedding=query_vec,
                top_k=top_k,
                threshold=threshold,
            )
        except Exception as e:
            logger.warning("Dense chunk search failed: %s", e)
            return []

    def _dense_patient_chunk_search(
        self, patient_id: str, query: str, top_k: int, threshold: float
    ) -> List[Dict[str, Any]]:
        """Dense cosine search on chunk_embeddings across patient sessions."""
        try:
            query_vec = self.embedding_service.embed_text(query)
            query_list = query_vec.tolist()

            result = self.db.execute(
                sql_text("""
                    SELECT ce.chunk_id, ce.chunk_text, ce.source_type,
                           ce.start_time, ce.end_time,
                           1 - (ce.embedding <=> :query_vec) AS similarity
                    FROM chunk_embeddings ce
                    JOIN sessions s ON s.id = ce.session_id
                    WHERE s.patient_id = :patient_id
                      AND (1 - (ce.embedding <=> :query_vec)) >= :threshold
                    ORDER BY ce.embedding <=> :query_vec
                    LIMIT :top_k
                """),
                {
                    "query_vec": str(query_list),
                    "patient_id": patient_id,
                    "threshold": threshold,
                    "top_k": top_k,
                },
            )
            return [
                {
                    "chunk_id": row.chunk_id,
                    "chunk_text": row.chunk_text,
                    "source_type": row.source_type,
                    "start_time": row.start_time,
                    "end_time": row.end_time,
                    "similarity": float(row.similarity),
                }
                for row in result
            ]
        except Exception as e:
            logger.warning("Dense patient chunk search failed: %s", e)
            return []

    def _dense_fact_search(
        self,
        patient_id: str,
        query: str,
        top_k: int,
        threshold: float,
        fact_type: Optional[str] = None,
        only_final: bool = True,
    ) -> List[Dict[str, Any]]:
        """Dense cosine search on clinical_embeddings."""
        try:
            query_vec = self.embedding_service.embed_text(query)
            return self.embedding_service.search_patient_facts(
                patient_id=patient_id,
                query_embedding=query_vec,
                top_k=top_k,
                threshold=threshold,
                fact_type=fact_type,
                only_final=only_final,
            )
        except Exception as e:
            logger.warning("Dense fact search failed: %s", e)
            return []

    # ── Sparse retrieval (tsvector/tsquery) ──────────────────────────────────

    def _build_tsquery(self, query: str) -> str:
        """
        Convert a natural-language query into a PostgreSQL tsquery string.

        Strategy:
          1. Tokenize on whitespace and punctuation.
          2. Remove tokens shorter than KEYWORD_MIN_LENGTH.
          3. Join with ' | ' (OR) for recall-oriented matching.
          4. Prefix-match each token with ':*' for partial matches.

        Example: "lisinopril blood pressure" -> "lisinopril:* | blood:* | pressure:*"
        """
        # Strip non-alphanumeric (keep hyphens for drug names like 'co-amoxiclav')
        tokens = re.findall(r"[a-zA-Z0-9][\w\-]*", query.lower())
        tokens = [t for t in tokens if len(t) >= KEYWORD_MIN_LENGTH]

        if not tokens:
            return ""

        # Use OR for broad recall; prefix matching via :*
        return " | ".join(f"{t}:*" for t in tokens)

    def _sparse_chunk_search(
        self, session_id: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """Full-text search on chunk_embeddings.chunk_text for a session."""
        tsquery = self._build_tsquery(query)
        if not tsquery:
            return []

        try:
            result = self.db.execute(
                sql_text("""
                    SELECT chunk_id, chunk_text, source_type, start_time, end_time,
                           ts_rank_cd(
                               to_tsvector('english', chunk_text),
                               to_tsquery('english', :tsquery)
                           ) AS rank
                    FROM chunk_embeddings
                    WHERE session_id = :session_id
                      AND to_tsvector('english', chunk_text) @@
                          to_tsquery('english', :tsquery)
                    ORDER BY rank DESC
                    LIMIT :top_k
                """),
                {
                    "session_id": session_id,
                    "tsquery": tsquery,
                    "top_k": top_k,
                },
            )
            return [
                {
                    "chunk_id": row.chunk_id,
                    "chunk_text": row.chunk_text,
                    "source_type": row.source_type,
                    "start_time": row.start_time,
                    "end_time": row.end_time,
                    "similarity": float(row.rank),  # ts_rank as similarity proxy
                }
                for row in result
            ]
        except Exception as e:
            logger.warning("Sparse chunk search failed: %s", e)
            return []

    def _sparse_patient_chunk_search(
        self, patient_id: str, query: str, top_k: int
    ) -> List[Dict[str, Any]]:
        """Full-text search on chunk_embeddings across patient sessions."""
        tsquery = self._build_tsquery(query)
        if not tsquery:
            return []

        try:
            result = self.db.execute(
                sql_text("""
                    SELECT ce.chunk_id, ce.chunk_text, ce.source_type,
                           ce.start_time, ce.end_time,
                           ts_rank_cd(
                               to_tsvector('english', ce.chunk_text),
                               to_tsquery('english', :tsquery)
                           ) AS rank
                    FROM chunk_embeddings ce
                    JOIN sessions s ON s.id = ce.session_id
                    WHERE s.patient_id = :patient_id
                      AND to_tsvector('english', ce.chunk_text) @@
                          to_tsquery('english', :tsquery)
                    ORDER BY rank DESC
                    LIMIT :top_k
                """),
                {
                    "patient_id": patient_id,
                    "tsquery": tsquery,
                    "top_k": top_k,
                },
            )
            return [
                {
                    "chunk_id": row.chunk_id,
                    "chunk_text": row.chunk_text,
                    "source_type": row.source_type,
                    "start_time": row.start_time,
                    "end_time": row.end_time,
                    "similarity": float(row.rank),
                }
                for row in result
            ]
        except Exception as e:
            logger.warning("Sparse patient chunk search failed: %s", e)
            return []

    def _sparse_fact_search(
        self,
        patient_id: str,
        query: str,
        top_k: int,
        fact_type: Optional[str] = None,
        only_final: bool = True,
    ) -> List[Dict[str, Any]]:
        """Full-text search on clinical_embeddings fact_key/fact_data."""
        tsquery = self._build_tsquery(query)
        if not tsquery:
            return []

        filters = "patient_id = :patient_id"
        params: Dict[str, Any] = {
            "patient_id": patient_id,
            "tsquery": tsquery,
            "top_k": top_k,
        }

        if fact_type:
            filters += " AND fact_type = :fact_type"
            params["fact_type"] = fact_type

        if only_final:
            filters += " AND is_final = true"

        try:
            # Search across both fact_key and a text representation of fact_data
            result = self.db.execute(
                sql_text(f"""
                    SELECT id, fact_type, fact_key, fact_data, confidence,
                           grounding_score, is_final, session_id,
                           ts_rank_cd(
                               to_tsvector('english', fact_key),
                               to_tsquery('english', :tsquery)
                           ) AS rank
                    FROM clinical_embeddings
                    WHERE {filters}
                      AND to_tsvector('english', fact_key) @@
                          to_tsquery('english', :tsquery)
                    ORDER BY rank DESC
                    LIMIT :top_k
                """),
                params,
            )
            return [
                {
                    "id": row.id,
                    "fact_type": row.fact_type,
                    "fact_key": row.fact_key,
                    "fact_data": row.fact_data,
                    "confidence": float(row.confidence) if row.confidence else None,
                    "grounding_score": float(row.grounding_score) if row.grounding_score else None,
                    "is_final": row.is_final,
                    "session_id": row.session_id,
                    "similarity": float(row.rank),
                }
                for row in result
            ]
        except Exception as e:
            logger.warning("Sparse fact search failed: %s", e)
            return []

    # ── Reciprocal Rank Fusion ───────────────────────────────────────────────

    def _rrf_fuse(
        self,
        dense_results: List[Dict[str, Any]],
        sparse_results: List[Dict[str, Any]],
        id_key: str = "chunk_id",
    ) -> List[Dict[str, Any]]:
        """
        Merge dense and sparse results using Reciprocal Rank Fusion (RRF).

        RRF score for document d:
            score(d) = sum over retrievers r:
                weight_r / (k + rank_r(d))

        Where rank is 1-based position in the retriever's result list.
        Documents only in one list get their single-retriever score.

        Args:
            dense_results: Results from vector search (ordered by similarity desc.)
            sparse_results: Results from keyword search (ordered by rank desc.)
            id_key: Key to use as unique identifier for deduplication.

        Returns:
            Merged results sorted by RRF score descending.
        """
        scores: Dict[str, float] = {}
        docs: Dict[str, Dict[str, Any]] = {}

        # Process dense results
        for rank, result in enumerate(dense_results, start=1):
            doc_id = str(result.get(id_key, rank))
            rrf_score = self.dense_weight / (self.rrf_k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in docs:
                docs[doc_id] = result.copy()

        # Process sparse results
        for rank, result in enumerate(sparse_results, start=1):
            doc_id = str(result.get(id_key, rank))
            rrf_score = self.sparse_weight / (self.rrf_k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in docs:
                docs[doc_id] = result.copy()

        # Sort by fused score
        ranked_ids = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)

        fused_results = []
        for doc_id in ranked_ids:
            doc = docs[doc_id]
            doc["rrf_score"] = round(scores[doc_id], 6)
            fused_results.append(doc)

        return fused_results
