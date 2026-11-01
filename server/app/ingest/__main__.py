"""
Entry points:

    python -m app.ingest worker --stage noop
    python -m app.ingest reconciler
    python -m app.ingest migrate

Config comes from INGEST_* env vars (see config.py), DATABASE_URL, and
KAFKA_BROKERS (reconciler; unset = logging publisher, with a warning).
Exits non-zero on invalid config or if the DB is unreachable for 30 s.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.logging import configure_logging, get_logger

from .config import IngestQueueConfig
from .engine import Worker
from .errors import IngestConfigError, IngestError
from .metrics import default_metrics
from .noop_stage import NoopStage
from .outbox import KafkaOutboxPublisher, LoggingOutboxPublisher, OutboxPublisher
from .reconciler import Reconciler
from .stage import StageRegistry

logger = get_logger("app.ingest")

DB_CONNECT_DEADLINE_SECONDS = 30.0


def normalize_database_url(url: object) -> str:
    """
    Accept the cluster secret's lib/pq `postgres://` URL and the compose
    `postgresql://` URL. SQLAlchemy 2 has no `postgres` dialect.

    The returned URL is for create_engine / Alembic only. Never log it.
    """
    if not isinstance(url, str) or not url.strip():
        raise IngestConfigError("DATABASE_URL", url, "a postgres:// or postgresql:// URL")
    raw = url.strip()
    scheme, sep, rest = raw.partition("://")
    if sep != "://" or not rest:
        raise IngestConfigError("DATABASE_URL", "<redacted>", "a postgres:// or postgresql:// URL")
    scheme_l = scheme.lower()
    if scheme_l == "sqlite" or scheme_l.startswith("sqlite+"):
        raise IngestConfigError("DATABASE_URL", "<redacted>", "a postgres:// or postgresql:// URL, not sqlite")
    if scheme_l == "postgres":
        logger.info("rewrote DATABASE_URL scheme from postgres:// to postgresql+psycopg2://")
        return "postgresql+psycopg2://" + rest
    if scheme_l == "postgresql":
        return "postgresql+psycopg2://" + rest
    if scheme_l.startswith("postgresql+"):
        return raw
    raise IngestConfigError(
        "DATABASE_URL",
        "<redacted>",
        f"a postgres:// or postgresql:// URL, got scheme {scheme_l!r}",
    )


def build_registry() -> StageRegistry:
    """Stages this build can run. #93 / #59 / #54 add split, page, finalize."""
    return StageRegistry([NoopStage()])


def connect_engine(url: str, *, pool_size: int) -> Engine:
    url = normalize_database_url(url)
    engine = create_engine(
        url, pool_size=pool_size, max_overflow=2, pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )
    deadline = time.monotonic() + DB_CONNECT_DEADLINE_SECONDS
    delay = 0.5
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("select 1 from ingest_tasks limit 1"))
            logger.info("database reachable attempt=%d", attempt)
            return engine
        except SQLAlchemyError as exc:
            if time.monotonic() + delay > deadline:
                raise IngestConfigError(
                    "DATABASE_URL", "<redacted>", f"a reachable, migrated database (last error {type(exc).__name__})"
                ) from exc
            logger.warning(
                "database not ready, retrying attempt=%d delay_s=%.1f error=%s", attempt, delay, type(exc).__name__
            )
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    from app.config.settings import get_settings

    return get_settings().database.url


def _publisher() -> OutboxPublisher:
    brokers = os.environ.get("KAFKA_BROKERS", "").strip()
    if not brokers:
        logger.warning("KAFKA_BROKERS not set; outbox relay uses the logging publisher (events are not delivered)")
        return LoggingOutboxPublisher()
    return KafkaOutboxPublisher(brokers)


def _start_metrics(port: int) -> None:
    if port <= 0:
        return
    try:
        from prometheus_client import start_http_server  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("prometheus_client not installed; /metrics not served port=%d", port)
        return
    start_http_server(port)
    logger.info("metrics served port=%d path=/metrics", port)


def _stop_event() -> threading.Event:
    stop = threading.Event()

    def _handle(signum, _frame) -> None:
        logger.info("signal received, stopping after the current task signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    return stop


def migrate() -> None:
    """Apply Alembic head. Used by the k8s initContainer; cwd must be server/."""
    raw = os.environ.get("DATABASE_URL") or _database_url()
    os.environ["DATABASE_URL"] = normalize_database_url(raw)
    # Alembic reads get_settings(), which caches the URL from before the rewrite.
    from app.config import settings as settings_mod

    settings_mod._settings = None
    from alembic import command
    from alembic.config import Config

    logger.info("applying alembic migrations to head")
    command.upgrade(Config("alembic.ini"), "head")
    logger.info("alembic migrations at head")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest")
    sub = parser.add_subparsers(dest="role", required=True)
    w = sub.add_parser("worker", help="run a batch worker for one stage")
    w.add_argument("--stage", required=True)
    r = sub.add_parser("reconciler", help="run the reconciler loops")
    sub.add_parser("migrate", help="apply Alembic migrations to head")
    for p in (w, r):
        p.add_argument("--metrics-port", type=int, default=int(os.environ.get("INGEST_METRICS_PORT", "8080")))
        p.add_argument("--pod", default=os.environ.get("POD_NAME") or socket.gethostname())
    args = parser.parse_args(argv)

    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
    try:
        if args.role == "migrate":
            migrate()
            return 0
        cfg = IngestQueueConfig.from_env()
        registry = build_registry()
        metrics = default_metrics()
        if args.role == "worker":
            stage = registry.get(args.stage)
            engine = connect_engine(_database_url(), pool_size=2 + cfg.batch)
            _start_metrics(args.metrics_port)
            Worker(engine, stage, cfg, pod=args.pod, metrics=metrics).run_forever(_stop_event())
        else:
            engine = connect_engine(_database_url(), pool_size=3)
            publisher = _publisher()
            _start_metrics(args.metrics_port)
            try:
                Reconciler(engine, registry, cfg, publisher, metrics=metrics, name=args.pod).run_forever(_stop_event())
            finally:
                publisher.close()
    except IngestError as exc:
        logger.error("ingest %s exiting: %s", args.role, exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
