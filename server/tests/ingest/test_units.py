"""Ingest queue unit tests: no database."""

from __future__ import annotations

import random
import threading
import uuid
from unittest.mock import ANY, MagicMock

import pytest
from prometheus_client import CollectorRegistry

from app.ingest import claim as q
from app.ingest import engine as engine_mod
from app.ingest.claim import ClaimedTask
from app.ingest.config import IngestQueueConfig
from app.ingest.engine import OUTCOME_FENCE_REJECTED, OUTCOME_LEASE_LOST, Worker
from app.ingest.__main__ import normalize_database_url
from app.ingest.errors import IngestConfigError, IngestInputError, StageContractError, UnknownStageError
from app.ingest.metrics import IngestMetrics
from app.ingest.noop_stage import NoopStage
from app.ingest.outbox import MAX_PAYLOAD_BYTES, InMemoryOutboxPublisher, write_outbox
from app.ingest.progress import TaskProgress
from app.ingest.reconciler import Reconciler
from app.ingest.stage import StageRegistry

pytestmark = pytest.mark.unit


def _task(attempts: int = 1) -> ClaimedTask:
    return ClaimedTask(
        task_id=7,
        lease_token=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        page=None,
        session_id="s0",
        stage="noop",
        attempts=attempts,
        priority="active",
        age_seconds=0.5,
    )


def _metrics():
    reg = CollectorRegistry()
    m = IngestMetrics(registry=reg)
    return m, (lambda name, **labels: reg.get_sample_value(name, labels) or 0.0)


# -- config -------------------------------------------------------------


def test_config_defaults_match_plan():
    cfg = IngestQueueConfig.load()
    assert (cfg.lease_seconds, cfg.aging_step_seconds, cfg.page_task_cap, cfg.max_attempts) == (30, 240, 4, 5)
    assert cfg.renew_interval_seconds == 10


@pytest.mark.parametrize(
    "field,value",
    [("lease_seconds", 4), ("lease_seconds", 601), ("page_task_cap", 0), ("max_attempts", 21), ("batch", 17)],
)
def test_config_out_of_range_names_field(field, value):
    with pytest.raises(IngestConfigError) as ei:
        IngestQueueConfig.load({field: value})
    assert ei.value.field == field
    assert ei.value.value == value
    assert field in str(ei.value)


def test_config_rejects_unknown_key_and_bad_type():
    with pytest.raises(IngestConfigError) as ei:
        IngestQueueConfig.load({"lease_secs": 30})
    assert ei.value.field == "lease_secs"
    with pytest.raises(IngestConfigError) as ei:
        IngestQueueConfig.load({"lease_seconds": "thirty"})
    assert ei.value.field == "lease_seconds"


def test_config_cross_field_backoff():
    with pytest.raises(IngestConfigError, match="backoff_cap_seconds"):
        IngestQueueConfig.load({"backoff_base_seconds": 10, "backoff_cap_seconds": 5})


def test_config_allows_progress_deadline_independent_of_lease_duration():
    cfg = IngestQueueConfig.load({"lease_seconds": 30, "stale_compute_seconds": 5})
    assert cfg.stale_compute_seconds == 5


def test_config_from_env():
    cfg = IngestQueueConfig.from_env({"INGEST_LEASE_SECONDS": "12", "INGEST_PAGE_TASK_CAP": "2", "OTHER": "x"})
    assert cfg.lease_seconds == 12 and cfg.page_task_cap == 2
    with pytest.raises(IngestConfigError):
        IngestQueueConfig.from_env({"INGEST_MAX_ATTEMPTS": "0"})


# -- backoff ------------------------------------------------------------


def test_backoff_doubles_caps_and_jitters_in_range():
    cfg = IngestQueueConfig.load({"backoff_base_seconds": 2, "backoff_cap_seconds": 60, "backoff_jitter": 0.2})
    rng = random.Random(1)
    for attempts, nominal in [(1, 2), (2, 4), (3, 8), (6, 60), (30, 60)]:
        for _ in range(200):
            d = q.backoff_seconds(attempts, cfg, rng)
            assert nominal * 0.8 - 1e-9 <= d <= nominal * 1.2 + 1e-9


@pytest.mark.parametrize("bad", [0, -1, 1.5, None])
def test_backoff_rejects_bad_attempts(bad):
    with pytest.raises(IngestInputError, match="attempts"):
        q.backoff_seconds(bad, IngestQueueConfig.load())


def test_format_error_truncates_and_names_class():
    msg = q.format_error(RuntimeError("x" * 5000))
    assert msg.startswith("RuntimeError: ") and len(msg) == q.MAX_ERROR_CHARS


# -- registry -----------------------------------------------------------


def test_registry_unknown_stage_names_registered():
    reg = StageRegistry([NoopStage()])
    with pytest.raises(UnknownStageError, match="noop"):
        reg.get("page")


def test_registry_rejects_duplicates_and_bad_stages():
    reg = StageRegistry([NoopStage()])
    with pytest.raises(StageContractError, match="already registered"):
        reg.register(NoopStage())
    with pytest.raises(StageContractError, match="lease_seconds"):
        reg.register(NoopStage(name="slow", lease_seconds=4))
    with pytest.raises(StageContractError, match="name"):
        reg.register(NoopStage(name=""))
    with pytest.raises(StageContractError, match="subclass"):
        reg.register(object())  # type: ignore[arg-type]


# -- input validation ---------------------------------------------------


@pytest.mark.parametrize(
    "kwargs,field",
    [
        (dict(doc_id="not-a-uuid", session_id="s", stage="noop", priority="active"), "doc_id"),
        (dict(doc_id=uuid.uuid4(), session_id="", stage="noop", priority="active"), "session_id"),
        (dict(doc_id=uuid.uuid4(), session_id="s", stage="noop", priority="urgent"), "priority"),
        (dict(doc_id=uuid.uuid4(), session_id="s", stage="page", priority="active"), "page"),
        (dict(doc_id=uuid.uuid4(), session_id="s", stage="page", priority="active", page=-1), "page"),
        (dict(doc_id=uuid.uuid4(), session_id="s", stage="noop", priority="active", page=3), "page"),
    ],
)
def test_enqueue_validates_before_touching_db(kwargs, field):
    conn = MagicMock()
    with pytest.raises(IngestInputError) as ei:
        q.enqueue(conn, **kwargs)
    assert ei.value.field == field
    conn.execute.assert_not_called()


def test_write_outbox_validates_payload():
    conn = MagicMock()
    with pytest.raises(IngestInputError, match="topic"):
        write_outbox(conn, topic="", key="k", payload={})
    with pytest.raises(IngestInputError, match="payload"):
        write_outbox(conn, topic="t", key="k", payload=["not", "a", "mapping"])  # type: ignore[arg-type]
    with pytest.raises(IngestInputError, match="bytes"):
        write_outbox(conn, topic="t", key="k", payload={"blob": "x" * (MAX_PAYLOAD_BYTES + 1)})
    conn.execute.assert_not_called()


def test_database_url_rewrites_libpq_scheme_without_logging_secret(caplog):
    raw = "postgres://medscribe:s3cret@postgres:5432/medscribe?sslmode=disable"
    with caplog.at_level("INFO"):
        rewritten = normalize_database_url(raw)
    assert rewritten == "postgresql+psycopg2://medscribe:s3cret@postgres:5432/medscribe?sslmode=disable"
    assert "s3cret" not in caplog.text
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
    assert normalize_database_url("postgresql+psycopg2://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_database_url_rejects_non_postgres_without_leaking_secret():
    with pytest.raises(IngestConfigError, match="mysql") as exc:
        normalize_database_url("mysql://user:s3cret@db/medscribe")
    assert "s3cret" not in str(exc.value)
    with pytest.raises(IngestConfigError, match="sqlite"):
        normalize_database_url("sqlite:///./medscribe.db")
    with pytest.raises(IngestConfigError, match="DATABASE_URL"):
        normalize_database_url("")


def test_lease_expiry_runs_while_relay_is_blocked():
    cfg = IngestQueueConfig.load()
    rec = Reconciler(MagicMock(), StageRegistry([NoopStage()]), cfg, InMemoryOutboxPublisher(), name="r")
    publish_entered = threading.Event()
    release = threading.Event()
    expired = threading.Event()

    def blocking_relay():
        publish_entered.set()
        assert release.wait(5), "relay was not released"

    rec.relay_outbox = blocking_relay  # type: ignore[method-assign]
    rec._expiry_tick = expired.set  # type: ignore[method-assign]
    rec.repair = lambda: None  # type: ignore[method-assign]
    stop = threading.Event()
    thread = threading.Thread(target=lambda: rec.run_forever(stop), daemon=True)
    thread.start()
    try:
        assert publish_entered.wait(2), "relay did not start"
        assert expired.wait(2), "lease expiry did not run while outbox relay was blocked"
    finally:
        release.set()
        stop.set()
        thread.join(3)
    assert not thread.is_alive()


def test_worker_and_reconciler_validate_dependencies():
    cfg = IngestQueueConfig.load()
    with pytest.raises(IngestInputError, match="engine"):
        Worker(None, NoopStage(), cfg, pod="p")  # type: ignore[arg-type]
    with pytest.raises(IngestInputError, match="pod"):
        Worker(MagicMock(), NoopStage(), cfg, pod=" ")
    with pytest.raises(IngestInputError, match="publisher"):
        Reconciler(MagicMock(), StageRegistry(), cfg, None)  # type: ignore[arg-type]
    with pytest.raises(IngestInputError, match="registry"):
        Reconciler(MagicMock(), {}, cfg, InMemoryOutboxPublisher())  # type: ignore[arg-type]


# -- engine paths with a fake connection --------------------------------


class _LostHeartbeat:
    def __init__(self, *a, **k):
        self.lost = threading.Event()
        self.lost.set()

    def start(self):
        pass

    def stop(self):
        pass


def test_lease_lost_discards_output_and_writes_nothing(monkeypatch):
    stage = NoopStage()
    stage.commit = MagicMock()  # type: ignore[method-assign]
    fence = MagicMock(return_value=True)
    monkeypatch.setattr(engine_mod, "_Heartbeat", _LostHeartbeat)
    monkeypatch.setattr(q, "fence", fence)
    eng = MagicMock()
    w = Worker(eng, stage, IngestQueueConfig.load(), pod="p")
    res = w.process(_task())
    assert res.outcome == OUTCOME_LEASE_LOST
    fence.assert_not_called()
    stage.commit.assert_not_called()
    eng.connect.assert_not_called()
    eng.begin.assert_not_called()


def test_fence_zero_rows_rolls_back_and_counts(monkeypatch):
    stage = NoopStage()
    stage.commit = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(q, "fence", MagicMock(return_value=False))
    m, read = _metrics()
    w = Worker(MagicMock(), stage, IngestQueueConfig.load(), pod="p", metrics=m, heartbeat=False)
    res = w.process(_task())
    assert res.outcome == OUTCOME_FENCE_REJECTED
    stage.commit.assert_not_called()
    assert read("ingest_fence_rejections_total", stage="noop") == 1


def test_heartbeat_marks_lost_on_zero_rows(monkeypatch):
    monkeypatch.setattr(q, "renew", MagicMock(return_value=False))
    m, read = _metrics()
    hb = engine_mod._Heartbeat(MagicMock(), _task(), 30, 0.01, m)
    hb.start()
    assert hb.lost.wait(2.0)
    hb.stop()
    assert read("ingest_lease_lost_total", stage="noop") == 1


def test_noop_stage_reports_compute_progress():
    reports = []

    class Progress:
        def report(self):
            reports.append("safe_unit")

    assert NoopStage().compute(_task(), Progress()) is None  # type: ignore[arg-type]
    assert reports == ["safe_unit"]


def test_progress_watchdog_hard_exits_only_after_stale_report_gap():
    task = _task()
    progress = TaskProgress(task)
    stale_transition = threading.Event()
    exits = []
    watchdog = engine_mod._ProgressWatchdog(
        progress,
        5,
        stale_transition.set,
        lambda code: exits.append(code),
    )
    # Avoid a timing-dependent five-second test: this simulates a report gap
    # beyond the validated threshold, not a delayed lease renewal.
    progress.seconds_since_report = lambda: 5.0  # type: ignore[method-assign]
    watchdog.start()
    watchdog._thread.join(2)
    assert stale_transition.is_set()
    assert watchdog.stale.is_set()
    assert exits == [75]


def test_worker_stale_watchdog_records_attempt_before_hard_exit(monkeypatch):
    exits = []

    class ImmediateStaleWatchdog:
        def __init__(self, progress, stale_seconds, on_stale, hard_exit):
            self.stale = threading.Event()
            self._on_stale = on_stale
            self._hard_exit = hard_exit

        def start(self):
            self.stale.set()
            self._on_stale()
            self._hard_exit(75)

        def stop(self):
            pass

    monkeypatch.setattr(engine_mod, "_ProgressWatchdog", ImmediateStaleWatchdog)
    worker = Worker(
        MagicMock(),
        NoopStage(),
        IngestQueueConfig.load(),
        pod="p",
        heartbeat=False,
        hard_exit=lambda code: exits.append(code),
    )
    fail_attempt = MagicMock()
    monkeypatch.setattr(worker, "_fail_attempt", fail_attempt)

    task = _task()
    result = worker.process(task)
    assert result.outcome == engine_mod.OUTCOME_ABANDONED
    fail_attempt.assert_called_once_with(
        task,
        ANY,
        reason="stale_progress",
    )
    assert exits == [75]
