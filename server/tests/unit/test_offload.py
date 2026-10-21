"""
Tests for app.core.offload (#91): OCR and compile run in child processes,
the event loop stays responsive, and every failure path is explicit.
"""

import asyncio
import logging
import pickle
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import OffloadConfig, OffloadConfigError
from app.core import offload
from tests.unit import _offload_helpers as helpers

OCR_FIXTURE = Path(__file__).parent.parent / "ocr_examples" / "discarhege_text_test.pdf"


@pytest.fixture
def pools():
    offload.start(OffloadConfig(ocr_pool_workers=1, compile_pool_workers=1,
                                ocr_job_timeout_s=60, compile_job_timeout_s=60))
    yield offload
    offload.shutdown()


@pytest.fixture
def no_pools():
    offload.shutdown()
    yield
    offload.shutdown()


async def _max_sleep_overshoot_ms(work, ticks: int = 100) -> float:
    """Run ``work`` while ticking 10 ms sleeps; return the worst overshoot."""
    worst = 0.0

    async def ticker():
        nonlocal worst
        for _ in range(ticks):
            t0 = time.perf_counter()
            await asyncio.sleep(0.01)
            worst = max(worst, (time.perf_counter() - t0 - 0.01) * 1000)

    # ticker first, so it is already waiting when work() starts.
    await asyncio.gather(ticker(), work())
    return worst


# ── Event loop stays responsive ────────────────────────────────────────────


async def test_loop_responsive_while_job_runs_in_child(pools):
    # Warm the child so spawn start-up is not part of the measurement.
    await offload._run("ocr", helpers.busy, 0.01, {"session_id": "warm"})

    async def work():
        outcome = await offload._run("ocr", helpers.busy, 2.0, {"session_id": "s1"})
        assert outcome.value == "busy-done"
        assert outcome.mode == "process"

    overshoot = await _max_sleep_overshoot_ms(work, ticks=150)
    assert overshoot < 50, f"event loop stalled {overshoot:.0f} ms while a child job ran"


async def test_inline_job_stalls_loop_baseline():
    """The pre-#91 shape: sync work inside a coroutine blocks the loop."""

    async def work():
        helpers.busy(0.5)

    overshoot = await _max_sleep_overshoot_ms(work, ticks=10)
    assert overshoot > 400


# ── Pickling across the process boundary ───────────────────────────────────


def test_ocr_job_and_result_pickle():
    from app.core.ocr.conflict_detector import ConflictItem, ConflictSeverity, ConflictType
    from app.core.ocr.document_classifier import DocumentClassification, DocumentType
    from app.core.ocr.field_extractor import ExtractedField, FieldCategory
    from app.core.ocr.pipeline import DocumentProcessingResult

    job = offload.OcrJob(file_path="/tmp/x.pdf", session_id="s1", patient_id="p1",
                         patient_history={"allergies": ["x"]}, original_filename="x.pdf")
    assert pickle.loads(pickle.dumps(job)) == job

    result = DocumentProcessingResult(
        classification=DocumentClassification(doc_type=DocumentType.UNKNOWN),
        extracted_fields=[ExtractedField(field_name="bp", value="120/80",
                                         category=list(FieldCategory)[0], confidence=0.9)],
        conflicts=[ConflictItem(field_name="bp", extracted_value="120/80",
                                conflict_type=list(ConflictType)[0],
                                severity=list(ConflictSeverity)[0], message="m")],
        document_artifact={"document_id": "d"},
    )
    back = pickle.loads(pickle.dumps(result))
    assert back.extracted_fields[0].field_name == "bp"
    assert back.conflicts[0].severity == result.conflicts[0].severity


def test_initial_graph_state_pickles():
    from app.core.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(enable_checkpointing=False, enable_interrupts=False)
    state = engine.create_initial_state(
        session_id="s1", patient_id="p1", doctor_id="d1",
        documents=[{"document_id": "d", "fields": []}],
        inputs={"segments": [{"start": 0.0, "end": 1.0, "raw_text": "hi"}]},
    )
    job = offload.CompileJob(state=dict(state), thread_id="s1", enable_checkpointing=False,
                             enable_interrupts=False, use_db=False)
    assert pickle.loads(pickle.dumps(job)).state == dict(state)


# ── Real OCR in the pool ───────────────────────────────────────────────────


@pytest.mark.slow
async def test_run_ocr_on_fixture_pdf(pools, monkeypatch):
    if not OCR_FIXTURE.exists():
        pytest.skip("OCR fixture missing")
    outcome = await offload.run_ocr(
        offload.OcrJob(file_path=str(OCR_FIXTURE), session_id="s1", patient_id="",
                       patient_history=None, original_filename=OCR_FIXTURE.name),
        doc_id="fixture",
    )
    assert outcome.mode == "process"
    assert outcome.value.page_count >= 1
    assert outcome.value.pages == []  # dropped before crossing the pipe


# ── Failure paths ──────────────────────────────────────────────────────────


async def test_pool_not_started_raises(no_pools):
    with pytest.raises(offload.OffloadUnavailableError, match="'ocr'.*not started"):
        await offload.run_ocr(
            offload.OcrJob(file_path="/tmp/x.pdf", session_id="s1", patient_id="",
                           patient_history=None, original_filename=None),
            doc_id="d",
        )


async def test_invalid_job_rejected(pools):
    with pytest.raises(offload.OffloadJobError, match="must be OcrJob"):
        await offload.run_ocr({"file_path": "x"}, doc_id="d")  # type: ignore[arg-type]
    with pytest.raises(offload.OffloadJobError, match="session_id"):
        await offload.run_compile(offload.CompileJob(state={}, thread_id="t",
                                                     enable_checkpointing=False,
                                                     enable_interrupts=False, use_db=False))


async def test_child_exception_reaches_parent(pools):
    with pytest.raises(RuntimeError, match="boom from child"):
        await offload._run("ocr", helpers.raise_in_child, None, {"session_id": "s1"})


async def test_broken_pool_restarts_retries_then_falls_back_to_thread(pools, caplog):
    counted = []
    if offload._FALLBACK_TOTAL is not None:
        before = offload._FALLBACK_TOTAL.labels(pool="ocr")._value.get()
        counted.append(before)

    with caplog.at_level(logging.WARNING, logger="app.core.offload"):
        outcome = await offload._run("ocr", helpers.exit_in_child, None, {"session_id": "s1"})

    assert outcome.value == "thread-ok"
    assert outcome.mode == "thread_fallback"
    assert any("mode=thread_fallback" in r.message and r.levelno == logging.WARNING
               for r in caplog.records)
    assert sum("recreating pool" in r.message for r in caplog.records) == 2
    if counted:
        assert offload._FALLBACK_TOTAL.labels(pool="ocr")._value.get() == counted[0] + 1

    # The recreated pool still serves normal jobs in a child.
    ok = await offload._run("ocr", helpers.which_process, None, {"session_id": "s1"})
    assert ok.mode == "process"


async def test_timeout_raises(no_pools):
    offload.start(OffloadConfig(ocr_job_timeout_s=1, compile_job_timeout_s=1))
    try:
        with pytest.raises(offload.OffloadTimeoutError) as info:
            await offload._run("ocr", helpers.sleep_then_return, 3.0, {"session_id": "s1"})
        assert info.value.pool == "ocr" and info.value.timeout_s == 1
    finally:
        offload.shutdown()


def test_start_requires_config(no_pools):
    with pytest.raises(offload.OffloadUnavailableError, match="config"):
        offload.start(None)


# ── Config validation ──────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", ["0", "abc", "9", "-1"])
def test_pool_workers_env_validation(monkeypatch, raw):
    monkeypatch.setenv("OCR_POOL_WORKERS", raw)
    with pytest.raises(OffloadConfigError, match="OCR_POOL_WORKERS"):
        OffloadConfig.from_env()


def test_offload_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("COMPILE_JOB_TIMEOUT_S", "42")
    cfg = OffloadConfig.from_env({"ocr_pool_workers": 2})
    assert cfg.ocr_pool_workers == 2 and cfg.compile_job_timeout_s == 42


def test_offload_yaml_value_validated():
    with pytest.raises(OffloadConfigError, match="COMPILE_POOL_WORKERS"):
        OffloadConfig(compile_pool_workers=True)  # bool is not an int here


# ── Routes ─────────────────────────────────────────────────────────────────


class _FakeSessionService:
    def __init__(self):
        self.queue, self.docs = [], []

    def get_session(self, session_id):
        return {"patient_id": ""}

    def add_to_queue(self, session_id, items):
        self.queue.extend(items)

    def add_document(self, session_id, doc):
        self.docs.append(doc)

    def get_documents(self, session_id):
        return []

    def merge_structured_record(self, *a, **k):
        pass

    def get_structured_record(self, session_id):
        return None


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.api.dependencies import get_db, get_session_service
    from app.api.routes import session as session_routes

    monkeypatch.setattr(session_routes, "UPLOAD_DIR", tmp_path)
    app = FastAPI()
    app.include_router(session_routes.router)
    fake = _FakeSessionService()
    app.dependency_overrides[get_session_service] = lambda: fake
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_upload_returns_503_without_pool(client, no_pools):
    resp = client.post("/api/session/s1/upload", files={"files": ("a.pdf", b"%PDF-1", "application/pdf")})
    assert resp.status_code == 503
    assert "'ocr'" in resp.json()["detail"]


def test_upload_timeout_and_empty_file_marked_failed(client, monkeypatch):
    async def fake_run_ocr(job, *, doc_id):
        raise offload.OffloadTimeoutError("ocr", "j1", 1)

    monkeypatch.setattr(offload, "require_pool", lambda name: None)
    monkeypatch.setattr(offload, "run_ocr", fake_run_ocr)
    resp = client.post("/api/session/s1/upload", files=[
        ("files", ("a.pdf", b"%PDF-1", "application/pdf")),
        ("files", ("empty.pdf", b"", "application/pdf")),
    ])
    assert resp.status_code == 200
    errors = [f["error"] for f in resp.json()["files"]]
    assert errors == ["ocr_timeout", "empty_file"]
    assert offload.OFFLOAD_HEADER not in resp.headers  # no job completed


def test_upload_sets_offload_header(client, monkeypatch):
    from app.core.ocr.pipeline import DocumentProcessingResult

    async def fake_run_ocr(job, *, doc_id):
        return offload.OffloadResult(value=DocumentProcessingResult(page_count=1), mode="thread_fallback")

    monkeypatch.setattr(offload, "require_pool", lambda name: None)
    monkeypatch.setattr(offload, "run_ocr", fake_run_ocr)
    monkeypatch.setattr(
        "app.api.routes.session._build_document_agent_summary", lambda **kw: "summary"
    )
    resp = client.post("/api/session/s1/upload", files={"files": ("a.pdf", b"%PDF-1", "application/pdf")})
    assert resp.status_code == 200
    assert resp.headers[offload.OFFLOAD_HEADER] == "thread_fallback"
    assert resp.json()["files"][0]["agent_summary"] == "summary"


_PIPELINE_BODY = {"session_id": "s1", "patient_id": "p1", "doctor_id": "d1", "segments": []}


def test_pipeline_503_without_pool(client, no_pools):
    resp = client.post("/api/session/s1/pipeline", json=_PIPELINE_BODY)
    assert resp.status_code == 503


def test_pipeline_timeout_returns_504_and_marks_progress_failed(client, monkeypatch):
    from app.core.pipeline_progress import pipeline_progress_store

    async def fake_run_compile(job):
        raise offload.OffloadTimeoutError("compile", "j1", 1)

    monkeypatch.setattr(offload, "run_compile", fake_run_compile)
    resp = client.post("/api/session/s1/pipeline", json=_PIPELINE_BODY)
    assert resp.status_code == 504
    assert pipeline_progress_store.get_dict("s1")["status"] == "failed"


def test_pipeline_returns_child_result_and_header(client, monkeypatch):
    seen = {}

    async def fake_run_compile(job):
        seen["job"] = job
        return offload.OffloadResult(
            value={"clinical_note": "note", "message": "ok", "flags": {}}, mode="process"
        )

    monkeypatch.setattr(offload, "run_compile", fake_run_compile)
    resp = client.post("/api/session/s1/pipeline", json=_PIPELINE_BODY)
    assert resp.status_code == 200
    assert resp.json()["clinical_note"] == "note"
    assert resp.headers[offload.OFFLOAD_HEADER] == "process"
    # get_db is overridden to None, so the child must not open a DB session.
    assert seen["job"].use_db is False and seen["job"].enable_checkpointing is True


# ── Regression: children spawned from the real API process ─────────────────


@pytest.mark.slow
def test_child_starts_from_process_that_imported_main():
    """main.py once put server/app on sys.path; spawn children inherited it and
    app/logging.py shadowed stdlib logging, so every OCR job broke the pool."""
    import subprocess
    import sys

    server_dir = Path(__file__).resolve().parents[2]
    script = (
        "import asyncio, main\n"
        "from app.config.settings import OffloadConfig\n"
        "from app.core import offload\n"
        "from tests.unit import _offload_helpers as h\n"
        "offload.start(OffloadConfig())\n"
        "r = asyncio.run(offload._run('ocr', h.which_process, None, {'session_id': 's'}))\n"
        "offload.shutdown()\n"
        "print('MODE', r.mode)\n"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=server_dir,
                         capture_output=True, text=True, timeout=120)
    assert "MODE process" in out.stdout, out.stderr[-2000:]


def test_ocr_child_threads_validated_and_passed_to_rapidocr(monkeypatch):
    import sys
    import types

    from app.core.ocr import extractor

    monkeypatch.setenv("OCR_CHILD_THREADS", "17")
    with pytest.raises(OffloadConfigError, match="OCR_CHILD_THREADS"):
        OffloadConfig.from_env()
    with pytest.raises(ValueError, match="threads"):
        extractor.set_rapid_ocr_threads(0)

    seen = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=FakeRapidOCR))
    monkeypatch.setattr(extractor, "_rapid_ocr_instance", None)
    monkeypatch.setattr(extractor, "_rapid_ocr_threads", None)
    extractor.set_rapid_ocr_threads(2)
    extractor._get_paddle_ocr()
    assert seen == {"intra_op_num_threads": 2, "inter_op_num_threads": 1}
