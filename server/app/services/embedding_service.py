"""
EmbeddingService — Medical-domain text embeddings with pgvector.

Uses BioLord-2023-M (768-dim) for clinical text embeddings that capture
medical semantics (drug–drug, symptom–diagnosis proximity) far better
than general-purpose models.

Three-layer grounding architecture:
  Layer 1 — Extraction-time span verification
  Layer 2 — Record-time evidence retrieval (cosine search)
  Layer 3 — Persistence-time confidence gating

The service wraps sentence-transformers and provides:
  - embed_text / embed_texts: raw embedding generation
  - store_chunk_embedding: persist chunk vectors for evidence retrieval
  - store_clinical_embedding: persist fact vectors for patient context
  - search_similar_chunks: cosine-distance top-k against chunk_embeddings
  - search_similar_facts: cosine-distance top-k against clinical_embeddings
  - verify_grounding: Layer 1 — check that extracted fact is grounded in source span
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────

# BioLord-2023-M: biomedical / clinical domain, 768-dim
DEFAULT_MODEL_NAME = "FremyCompany/BioLord-2023-M"
EMBEDDING_DIM = 768
DEFAULT_GROUNDING_THRESHOLD = 0.65
DEFAULT_PERSISTENCE_FLOOR = 0.60


class EmbeddingService:
    """
    Manages medical-domain text embeddings and pgvector persistence.

    Usage:
        svc = EmbeddingService(db_session)
        vec = svc.embed_text("patient allergic to penicillin")
        svc.store_clinical_embedding(patient_id, session_id, fact, vec)
        matches = svc.search_similar_chunks(session_id, query_vec, top_k=5)
    """

    def __init__(
        self,
        db: Optional[DBSession] = None,
        model_name: str = DEFAULT_MODEL_NAME,
        grounding_threshold: float = DEFAULT_GROUNDING_THRESHOLD,
        persistence_floor: float = DEFAULT_PERSISTENCE_FLOOR,
    ):
        self.db = db
        self.model_name = model_name
        self.grounding_threshold = grounding_threshold
        self.persistence_floor = persistence_floor
        self._model = None

    # ── Lazy model loading ──────────────────────────────────────────────────

    @property
    def model(self):
        """Lazy-load sentence-transformers model to avoid startup cost."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"Embedding model loaded: dim={self._model.get_sentence_embedding_dimension()}")
            except Exception as e:
                logger.error(f"Failed to load embedding model '{self.model_name}': {e}")
                raise RuntimeError(
                    f"Cannot load embedding model '{self.model_name}'. "
                    "Install sentence-transformers: pip install sentence-transformers"
                ) from e
        return self._model

    # ── Core embedding ──────────────────────────────────────────────────────

    def embed_text(self, text: str) -> np.ndarray:
        """Embed a single text string → numpy array (768,)."""
        return self.model.encode(text, normalize_embeddings=True)

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Embed a batch of texts → numpy array (N, 768)."""
        return self.model.encode(texts, normalize_embeddings=True, batch_size=32)

    # ── Layer 1: Grounding Verification ─────────────────────────────────────

    def verify_grounding(
        self,
        source_span: str,
        extracted_text: str,
    ) -> Tuple[float, bool]:
        """
        Layer 1 — Extraction-time span verification.

        Computes cosine similarity between the original transcript span
        and the extracted fact text. If similarity < threshold, the fact
        is flagged as potentially hallucinated.

        Returns:
            (cosine_similarity, is_grounded)
        """
        vecs = self.embed_texts([source_span, extracted_text])
        cosine_sim = float(np.dot(vecs[0], vecs[1]))
        is_grounded = cosine_sim >= self.grounding_threshold
        return cosine_sim, is_grounded

    # ── Chunk embeddings (for evidence retrieval) ───────────────────────────

    def store_chunk_embedding(
        self,
        session_id: str,
        chunk_id: str,
        source_type: str,
        chunk_text: str,
        embedding: Optional[np.ndarray] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> None:
        """Persist a chunk embedding to chunk_embeddings table."""
        if self.db is None:
            logger.warning("No DB session — skipping chunk embedding storage")
            return

        if embedding is None:
            embedding = self.embed_text(chunk_text)

        from app.database.models import ChunkEmbedding
        record = ChunkEmbedding(
            session_id=session_id,
            chunk_id=chunk_id,
            source_type=source_type,
            chunk_text=chunk_text,
            embedding=embedding.tolist(),
            start_time=start_time,
            end_time=end_time,
        )
        self.db.add(record)
        self.db.flush()

    def store_chunk_embeddings_batch(
        self,
        session_id: str,
        chunks: List[Dict[str, Any]],
    ) -> int:
        """
        Batch-embed and store chunks. Returns count stored.

        Each chunk dict must have: chunk_id, source, text.
        Optional: start, end.
        """
        if not chunks or self.db is None:
            return 0

        texts = [c.get("text", "") for c in chunks]
        embeddings = self.embed_texts(texts)

        from app.database.models import ChunkEmbedding
        for chunk, emb in zip(chunks, embeddings):
            record = ChunkEmbedding(
                session_id=session_id,
                chunk_id=chunk["chunk_id"],
                source_type=chunk.get("source", "transcript"),
                chunk_text=chunk.get("text", ""),
                embedding=emb.tolist(),
                start_time=chunk.get("start"),
                end_time=chunk.get("end"),
            )
            self.db.add(record)

        self.db.flush()
        return len(chunks)

    def search_similar_chunks(
        self,
        session_id: str,
        query_embedding: np.ndarray,
        top_k: int = 5,
        threshold: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Layer 2 — Cosine-distance search against chunk_embeddings.

        Returns top-k chunks ordered by cosine similarity (descending).
        Uses pgvector's <=> (cosine distance) operator.
        """
        if self.db is None:
            return []

        query_list = query_embedding.tolist()

        # pgvector cosine distance: 1 - cosine_similarity
        # So we ORDER BY distance ASC and filter distance < (1 - threshold)
        max_distance = 1.0 - threshold

        result = self.db.execute(
            sql_text("""
                SELECT chunk_id, source_type, chunk_text, start_time, end_time,
                       1 - (embedding <=> :query_vec) AS similarity
                FROM chunk_embeddings
                WHERE session_id = :session_id
                  AND (1 - (embedding <=> :query_vec)) >= :threshold
                ORDER BY embedding <=> :query_vec
                LIMIT :top_k
            """),
            {
                "query_vec": str(query_list),
                "session_id": session_id,
                "threshold": threshold,
                "top_k": top_k,
            },
        )

        return [
            {
                "chunk_id": row.chunk_id,
                "source_type": row.source_type,
                "chunk_text": row.chunk_text,
                "start_time": row.start_time,
                "end_time": row.end_time,
                "similarity": float(row.similarity),
            }
            for row in result
        ]

    # ── Clinical embeddings (for patient context) ───────────────────────────

    def store_clinical_embedding(
        self,
        patient_id: str,
        session_id: str,
        fact: Dict[str, Any],
        embedding: Optional[np.ndarray] = None,
        record_id: Optional[str] = None,
        source_span: Optional[str] = None,
        grounding_score: Optional[float] = None,
        is_final: bool = False,
    ) -> None:
        """
        Persist a clinical fact embedding.

        Layer 3 — Persistence-time confidence gating:
        Facts below persistence_floor are stored with is_final=False.
        """
        if self.db is None:
            logger.warning("No DB session — skipping clinical embedding storage")
            return

        # Build searchable text from fact
        fact_text = self._fact_to_text(fact)
        if embedding is None:
            embedding = self.embed_text(fact_text)

        confidence = fact.get("confidence", 0.5)

        # Layer 3: Confidence gating
        if confidence < self.persistence_floor:
            is_final = False

        from app.database.models import ClinicalEmbedding
        record = ClinicalEmbedding(
            patient_id=patient_id,
            session_id=session_id,
            record_id=record_id,
            fact_type=fact.get("type", fact.get("fact_type", "unknown")),
            fact_key=self._fact_to_key(fact),
            fact_data=fact,
            embedding=embedding.tolist(),
            source_span=source_span,
            grounding_score=grounding_score,
            confidence=confidence,
            is_final=is_final,
        )
        self.db.add(record)
        self.db.flush()

    def search_patient_facts(
        self,
        patient_id: str,
        query_embedding: np.ndarray,
        top_k: int = 10,
        threshold: float = 0.5,
        fact_type: Optional[str] = None,
        only_final: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search clinical_embeddings for a patient by vector similarity.

        Used for:
        - load_patient_context: retrieve prior facts
        - cross-visit contradiction detection
        - evidence augmentation
        """
        if self.db is None:
            return []

        query_list = query_embedding.tolist()

        filters = "patient_id = :patient_id AND (1 - (embedding <=> :query_vec)) >= :threshold"
        params: Dict[str, Any] = {
            "query_vec": str(query_list),
            "patient_id": patient_id,
            "threshold": threshold,
            "top_k": top_k,
        }

        if fact_type:
            filters += " AND fact_type = :fact_type"
            params["fact_type"] = fact_type

        if only_final:
            filters += " AND is_final = true"

        result = self.db.execute(
            sql_text(f"""
                SELECT id, fact_type, fact_key, fact_data, confidence,
                       grounding_score, is_final, session_id,
                       1 - (embedding <=> :query_vec) AS similarity
                FROM clinical_embeddings
                WHERE {filters}
                ORDER BY embedding <=> :query_vec
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
                "similarity": float(row.similarity),
            }
            for row in result
        ]

    def get_patient_facts_by_type(
        self,
        patient_id: str,
        fact_type: str,
        only_final: bool = True,
    ) -> List[Dict[str, Any]]:
        """Retrieve all facts of a given type for a patient (exact match, no vector search)."""
        if self.db is None:
            return []

        from app.database.models import ClinicalEmbedding

        query = (
            self.db.query(ClinicalEmbedding)
            .filter(ClinicalEmbedding.patient_id == patient_id)
            .filter(ClinicalEmbedding.fact_type == fact_type)
        )
        if only_final:
            query = query.filter(ClinicalEmbedding.is_final.is_(True))

        query = query.order_by(ClinicalEmbedding.created_at.desc())

        return [
            {
                "fact_type": row.fact_type,
                "fact_key": row.fact_key,
                "fact_data": row.fact_data,
                "confidence": row.confidence,
                "is_final": row.is_final,
                "session_id": row.session_id,
            }
            for row in query.all()
        ]

    def get_all_patient_facts(
        self,
        patient_id: str,
        only_final: bool = True,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve all facts for a patient, grouped by fact_type."""
        if self.db is None:
            return {}

        from app.database.models import ClinicalEmbedding

        query = (
            self.db.query(ClinicalEmbedding)
            .filter(ClinicalEmbedding.patient_id == patient_id)
        )
        if only_final:
            query = query.filter(ClinicalEmbedding.is_final.is_(True))

        query = query.order_by(ClinicalEmbedding.fact_type, ClinicalEmbedding.created_at.desc())

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in query.all():
            entry = {
                "fact_key": row.fact_key,
                "fact_data": row.fact_data,
                "confidence": row.confidence,
                "session_id": row.session_id,
            }
            grouped.setdefault(row.fact_type, []).append(entry)

        return grouped

    # ── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _fact_to_text(fact: Dict[str, Any]) -> str:
        """Convert a fact dict to a searchable text string for embedding."""
        fact_type = fact.get("type", fact.get("fact_type", ""))
        value = fact.get("value", "")

        if isinstance(value, dict):
            parts = [f"{k}: {v}" for k, v in value.items() if v]
            value_str = ", ".join(parts)
        elif isinstance(value, list):
            value_str = ", ".join(str(v) for v in value)
        else:
            value_str = str(value)

        return f"{fact_type} {value_str}".strip()

    @staticmethod
    def _fact_to_key(fact: Dict[str, Any]) -> str:
        """Extract a canonical key from a fact for deduplication."""
        value = fact.get("value", "")
        fact_type = fact.get("type", fact.get("fact_type", "unknown"))

        if isinstance(value, dict):
            # Use the most identifying field
            for key in ("name", "substance", "code", "test", "mrn"):
                if key in value and value[key]:
                    return str(value[key]).lower().strip()
            return str(list(value.values())[0]).lower().strip() if value else fact_type

        return str(value).lower().strip() if value else fact_type


# ── Singleton (lazy) ────────────────────────────────────────────────────────

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service(db: Optional[DBSession] = None) -> EmbeddingService:
    """Get or create the singleton EmbeddingService (model loaded once)."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(db=db)
    elif db is not None:
        # Update DB session for the current request
        _embedding_service.db = db
    return _embedding_service
