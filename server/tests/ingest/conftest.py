"""
Fixtures for the ingest queue conformance suite.

Real Postgres only. Set INGEST_TEST_DATABASE_URL to a disposable database
(it is migrated to head and its queue tables are truncated per test), e.g.

    docker compose up -d db
    INGEST_TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/medscribe \
        pytest tests/ingest -o addopts=""
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry

from app.ingest.metrics import IngestMetrics

from .helpers import make_engine, configured_db_url, truncate

SERVER_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def db_url() -> str:
    url = configured_db_url()
    if not url:
        pytest.skip("INGEST_TEST_DATABASE_URL not set; the conformance suite needs real Postgres")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVER_DIR,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )
    return url


@pytest.fixture(scope="session")
def pg(db_url):
    engine = make_engine(db_url, pool_size=24)
    yield engine
    engine.dispose()


@pytest.fixture
def db(pg):
    truncate(pg)
    yield pg


@pytest.fixture
def metrics():
    registry = CollectorRegistry()
    m = IngestMetrics(registry=registry)
    m.read = lambda name, **labels: registry.get_sample_value(name, labels) or 0.0  # type: ignore[attr-defined]
    return m
