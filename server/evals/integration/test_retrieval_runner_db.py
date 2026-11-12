"""Retrieval eval runner against a real Postgres + pgvector (#104).

Skipped unless RETRIEVAL_EVAL_DATABASE_URL points at a migrated database
whose name contains 'eval'. Loads the real BioLord model.

    docker run -d --rm --name medscribe-eval-pg -e POSTGRES_PASSWORD=postgres \\
        -e POSTGRES_DB=medscribe_eval -p 55432:5432 pgvector/pgvector:pg15
    DATABASE_URL=postgresql://postgres:postgres@localhost:55432/medscribe_eval alembic upgrade head
    RETRIEVAL_EVAL_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/medscribe_eval \\
        python -m pytest evals/integration -o addopts=""
"""

from __future__ import annotations

import json
import os

import pytest

from evals.retrieval.errors import RetrieverDegradedError
from evals.retrieval.runner import DEFAULT_DATASET_DIR, RunConfig, run

DB_URL = os.getenv("RETRIEVAL_EVAL_DATABASE_URL", "")

pytestmark = [
    pytest.mark.db,
    pytest.mark.slow,
    pytest.mark.skipif(not DB_URL, reason="RETRIEVAL_EVAL_DATABASE_URL not set"),
]


def _config(tmp_path):
    return RunConfig(
        dataset_dir=DEFAULT_DATASET_DIR,
        artifacts_dir=tmp_path,
        database_url=DB_URL,
        resamples=200,
    )


def test_full_run_writes_evidence_and_is_idempotent(tmp_path, caplog):
    first = run(_config(tmp_path / "a"))
    assert first["corpus"]["queries"] == 100
    assert first["leakage"]["foreign_chunks_returned"] == 0
    assert (tmp_path / "a" / "results.json").is_file()
    meta = (tmp_path / "a" / "run-metadata.txt").read_text()
    assert "embedding_model=FremyCompany/BioLord-2023-M" in meta
    assert "[0." not in meta, "query vector leaked into run metadata"

    caplog.set_level("WARNING", logger="evals.retrieval")
    second = run(_config(tmp_path / "b"))
    assert any("previous eval run" in r.getMessage() for r in caplog.records)
    assert second["corpus"]["chunks"] == first["corpus"]["chunks"]
    on_disk = json.loads((tmp_path / "b" / "results.json").read_text())
    assert on_disk["hybrid"]["overall"]["n"] == 88


def test_sql_failure_in_a_leg_aborts_without_report(tmp_path, monkeypatch):
    from app.services.hybrid_retrieval import HybridRetrievalService

    # Invalid tsquery syntax makes the sparse leg's SQL fail inside the
    # service, which catches it and returns []. The runner must not publish.
    monkeypatch.setattr(HybridRetrievalService, "_build_tsquery", lambda self, q: "((( broken")
    with pytest.raises(RetrieverDegradedError, match="Sparse"):
        run(_config(tmp_path))
    assert not (tmp_path / "results.json").exists()
