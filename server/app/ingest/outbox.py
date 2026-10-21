"""
Transactional outbox (SDD §4.4).

Stages write outbox rows inside their output transaction with write_outbox();
the reconciler's relay publishes them through an OutboxPublisher and sets
sent_at. Delivery is at-least-once; consumers dedupe on event_id.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.logging import get_logger

from .errors import IngestConfigError, IngestInputError

logger = get_logger(__name__)

# Payloads carry ids, counts and states only, so they are small. Anything
# larger is almost certainly document text that must not be here.
MAX_PAYLOAD_BYTES = 16 * 1024

_INSERT_SQL = text(
    """
    insert into ingest_outbox (event_id, topic, key, payload)
    values (:event_id, :topic, :key, cast(:payload as jsonb))
    """
)


def write_outbox(conn: Connection, *, topic: str, key: str, payload: Mapping[str, Any]) -> uuid.UUID:
    """Insert one outbox row in the caller's transaction. Returns its event_id."""
    if not isinstance(topic, str) or not topic.strip():
        raise IngestInputError("topic", topic, "a non-empty string")
    if not isinstance(key, str) or not key:
        raise IngestInputError("key", key, "a non-empty string")
    if not isinstance(payload, Mapping):
        raise IngestInputError("payload", type(payload).__name__, "a mapping of ids, counts, states")
    try:
        body = json.dumps(dict(payload), separators=(",", ":"), default=str)
    except (TypeError, ValueError) as exc:
        raise IngestInputError("payload", type(payload).__name__, f"JSON-serializable ({exc})") from exc
    if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise IngestInputError("payload", f"{len(body)} bytes", f"at most {MAX_PAYLOAD_BYTES} bytes")
    event_id = uuid.uuid4()
    conn.execute(_INSERT_SQL, {"event_id": str(event_id), "topic": topic, "key": key, "payload": body})
    return event_id


class OutboxPublisher(Protocol):
    """Delivers one event. Raises on failure; returning means delivered."""

    def publish(self, *, topic: str, key: str, payload: Dict[str, Any], event_id: uuid.UUID) -> None: ...

    def close(self) -> None: ...


class InMemoryOutboxPublisher:
    """Test publisher: records deliveries; can fail chosen event_ids a set number of times."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.published: List[Tuple[str, str, Dict[str, Any], uuid.UUID]] = []
        self._fail_remaining: Dict[uuid.UUID, int] = {}

    def fail_next(self, event_id: uuid.UUID, times: int = 1) -> None:
        with self._lock:
            self._fail_remaining[event_id] = times

    def publish(self, *, topic: str, key: str, payload: Dict[str, Any], event_id: uuid.UUID) -> None:
        with self._lock:
            left = self._fail_remaining.get(event_id, 0)
            if left > 0:
                self._fail_remaining[event_id] = left - 1
                raise ConnectionError(f"injected publish failure for event_id={event_id}")
            self.published.append((topic, key, payload, event_id))

    def close(self) -> None:
        return None


class LoggingOutboxPublisher:
    """Fallback when no broker is configured: logs ids only, marks rows sent."""

    def publish(self, *, topic: str, key: str, payload: Dict[str, Any], event_id: uuid.UUID) -> None:
        logger.warning(
            "outbox publish without a broker (logging publisher) event_id=%s topic=%s payload_keys=%s",
            event_id,
            topic,
            sorted(payload),
        )

    def close(self) -> None:
        return None


class KafkaOutboxPublisher:
    """confluent-kafka producer; publish() waits for the broker ack."""

    def __init__(self, brokers: str, *, timeout_seconds: float = 5.0, client_id: str = "ingest-reconciler") -> None:
        if not isinstance(brokers, str) or not brokers.strip():
            raise IngestConfigError("KAFKA_BROKERS", brokers, "a comma-separated broker list")
        if timeout_seconds <= 0:
            raise IngestConfigError("timeout_seconds", timeout_seconds, "> 0")
        try:
            from confluent_kafka import Producer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise IngestConfigError(
                "confluent_kafka", None, "the confluent-kafka package installed (server/requirements.txt)"
            ) from exc
        self._timeout = timeout_seconds
        self._producer = Producer(
            {
                "bootstrap.servers": brokers,
                "client.id": client_id,
                "enable.idempotence": True,
                "acks": "all",
                "message.timeout.ms": int(timeout_seconds * 1000),
            }
        )

    def publish(self, *, topic: str, key: str, payload: Dict[str, Any], event_id: uuid.UUID) -> None:
        result: Dict[str, Optional[Any]] = {"err": None, "done": False}

        def _on_delivery(err, _msg) -> None:
            result["err"] = err
            result["done"] = True

        self._producer.produce(
            topic,
            key=key.encode("utf-8"),
            value=json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
            headers={"event_id": str(event_id)},
            on_delivery=_on_delivery,
        )
        self._producer.flush(self._timeout)
        if not result["done"]:
            raise TimeoutError(f"kafka delivery not confirmed within {self._timeout}s event_id={event_id}")
        if result["err"] is not None:
            raise ConnectionError(f"kafka delivery failed event_id={event_id}: {result['err']}")

    def close(self) -> None:
        self._producer.flush(self._timeout)


__all__ = [
    "MAX_PAYLOAD_BYTES",
    "write_outbox",
    "OutboxPublisher",
    "InMemoryOutboxPublisher",
    "LoggingOutboxPublisher",
    "KafkaOutboxPublisher",
]
