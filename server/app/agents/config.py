"""
AgentContext — Dependency Injection for LangGraph Nodes.

Follows Anthropic's agent pattern: nodes receive capabilities via context,
they don't reach out and grab their own dependencies. This makes nodes
testable, composable, and decoupled from infrastructure.

Usage:
    ctx = AgentContext(
        patient_service=my_patient_svc,
        clinical_engine=my_engine,
        embedding_service=my_embed_svc,
        llm_factory=lambda: LLMClient(),
        db_session_factory=SessionLocal,
    )
    graph = build_graph(ctx)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from app.core.clinical_suggestions import ClinicalSuggestionEngine
    from app.core.patient_service import PatientService
    from app.database.repositories.patient_repo import PatientRepository
    from app.database.repositories.record_repo import RecordRepository
    from app.database.repositories.session_repo import SessionRepository
    from app.models.llm import LLMClient
    from app.services.embedding_service import EmbeddingService
    from sqlalchemy.orm import Session as DBSession


@dataclass(frozen=True)
class AgentContext:
    """
    Injected context available to every agent node.

    Attributes:
        patient_service:       Database-backed patient lookup (legacy).
        clinical_engine:       Clinical suggestion engine.
        llm_factory:           Callable that returns a fresh LLMClient.
        embedding_service:     Medical-domain embedding + pgvector ops.
        patient_repo:          PatientRepository for patient CRUD.
        record_repo:           RecordRepository for medical record CRUD.
        session_repo:          SessionRepository for session CRUD.
        db_session_factory:    Callable that returns a new SQLAlchemy Session.
        max_llm_calls:         Budget cap on total LLM invocations per run.
        grounding_threshold:   Min cosine sim for span grounding (Layer 1).
        persistence_floor:     Min confidence for is_final=True (Layer 3).
        trace_enabled:         Enable trace logging in controls.trace_log.
    """
    patient_service: Optional[PatientService] = None
    clinical_engine: Optional[ClinicalSuggestionEngine] = None
    llm_factory: Optional[Callable[[], LLMClient]] = None

    # ── New: DB-aware dependencies ──────────────────────────────────────────
    embedding_service: Optional[EmbeddingService] = None
    patient_repo: Optional[PatientRepository] = None
    record_repo: Optional[RecordRepository] = None
    session_repo: Optional[SessionRepository] = None
    db_session_factory: Optional[Callable[[], DBSession]] = None

    # ── Tuning knobs ────────────────────────────────────────────────────────
    max_llm_calls: int = 30
    grounding_threshold: float = 0.65
    persistence_floor: float = 0.60
    trace_enabled: bool = True


def make_node(node_fn: Callable, context: AgentContext) -> Callable:
    """
    Bind an AgentContext to a node function.

    Supports two signatures:
        (state: GraphState) -> GraphState              — context-free node
        (state: GraphState, ctx: AgentContext) -> GraphState — context-aware node

    Returns a LangGraph-compatible ``(state) -> state`` callable.
    """
    import inspect
    sig = inspect.signature(node_fn)
    needs_ctx = len(sig.parameters) >= 2

    def wrapped(state: Dict[str, Any]) -> Dict[str, Any]:
        if needs_ctx:
            return node_fn(state, context)
        return node_fn(state)

    # Preserve original name for graph visualisation
    wrapped.__name__ = node_fn.__name__
    wrapped.__qualname__ = node_fn.__qualname__
    return wrapped


def create_default_context(
    db_session=None,
) -> AgentContext:
    """
    Build an AgentContext with live production dependencies.

    Lazily imports heavy modules so the context can be created without
    triggering torch/pyannote DLL issues at import time.

    Args:
        db_session: Optional SQLAlchemy Session.  When provided, the
                    repositories and embedding service are wired up for
                    full DB integration.  When ``None`` (e.g. in tests),
                    the pipeline still runs but without persistence.
    """
    clinical_engine = None
    patient_service = None
    embedding_service = None
    patient_repo = None
    record_repo = None
    session_repo = None
    db_session_factory = None

    try:
        from app.core.clinical_suggestions import get_clinical_suggestion_engine
        clinical_engine = get_clinical_suggestion_engine()
    except Exception:
        pass

    def _llm_factory():
        from app.models.llm import LLMClient
        return LLMClient()

    # Wire up DB-backed services if a session is provided
    if db_session is not None:
        # Quick connectivity check — if DB is unreachable, skip all repos/services
        # so every downstream node doesn't individually timeout.
        _db_reachable = False
        try:
            from sqlalchemy import text as sa_text
            db_session.execute(sa_text("SELECT 1"))
            _db_reachable = True
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "[AgentContext] DB connection check failed — running without persistence: %s", e
            )

        if _db_reachable:
            try:
                from app.core.patient_service import PatientService
                patient_service = PatientService(db_session)
            except Exception:
                pass

            try:
                from app.database.repositories.patient_repo import PatientRepository
                from app.database.repositories.record_repo import RecordRepository
                from app.database.repositories.session_repo import SessionRepository
                patient_repo = PatientRepository(db_session)
                record_repo = RecordRepository(db_session)
                session_repo = SessionRepository(db_session)
            except Exception:
                pass

            try:
                from app.services.embedding_service import get_embedding_service
                embedding_service = get_embedding_service(db=db_session)
            except Exception:
                pass

            # Factory for fresh sessions (e.g. persist_results commits independently)
            try:
                from app.database.session import SessionLocal
                db_session_factory = SessionLocal
            except Exception:
                pass

    return AgentContext(
        clinical_engine=clinical_engine,
        patient_service=patient_service,
        llm_factory=_llm_factory,
        embedding_service=embedding_service,
        patient_repo=patient_repo,
        record_repo=record_repo,
        session_repo=session_repo,
        db_session_factory=db_session_factory,
        max_llm_calls=30,
        grounding_threshold=0.65,
        persistence_floor=0.60,
        trace_enabled=True,
    )
