"""
Shared test helpers for creating mock AgentContext instances.

Usage:
    from tests.helpers import make_test_context
    ctx = make_test_context()
"""

from unittest.mock import MagicMock
from app.agents.config import AgentContext


def make_test_context(**overrides) -> AgentContext:
    """
    Create an AgentContext with all dependencies set to None (no-DB mode).

    This mirrors how the pipeline behaves when ``db_session`` is not provided:
    all DB-dependent features gracefully degrade and nodes use their
    in-memory-only code paths.

    Pass keyword arguments to override specific fields, e.g.:
        ctx = make_test_context(embedding_service=mock_embed_svc)
    """
    defaults = dict(
        patient_service=None,
        clinical_engine=None,
        llm_factory=None,
        embedding_service=None,
        patient_repo=None,
        record_repo=None,
        session_repo=None,
        db_session_factory=None,
        max_llm_calls=30,
        grounding_threshold=0.65,
        persistence_floor=0.60,
        trace_enabled=True,
    )
    defaults.update(overrides)
    return AgentContext(**defaults)
