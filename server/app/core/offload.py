"""
Child-process offload for OCR and Lane B compile (#91, SDD T0, D1 + D9).

Both jobs are CPU-heavy and partly synchronous (RapidOCR, sync Groq calls,
the 16-node graph). Run inline they stall the API event loop for every
session. This module owns two spawn-context process pools and runs each job
as a pure function: data in, result out. The parent process keeps writing all
session state (``SessionService._store`` is an in-process dict a child cannot
reach).

Stopgap: T5 (#59) moves OCR into ``ingest-page`` and T15 (#61) moves compile
into ``compile-worker``. Delete this module when both land.

Failure behavior (no silent inline run):
  - pools not started          -> OffloadUnavailableError (routes return 503)
  - child died (BrokenProcessPool) -> recreate the pool, retry once; if that
    breaks too, run the job in a thread, log at warning, bump
    ``medscribe_offload_fallback_total{pool}``, and report
    ``mode="thread_fallback"`` so routes set ``X-MedScribe-Offload``
  - job timeout                -> OffloadTimeoutError; the child keeps its
    slot until it finishes (a process pool cannot cancel a running job)
"""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, Literal, Optional, TypeVar

logger = logging.getLogger(__name__)

OffloadMode = Literal["process", "thread_fallback"]
OFFLOAD_HEADER = "X-MedScribe-Offload"

T = TypeVar("T")

try:
    from prometheus_client import Counter  # type: ignore[import-untyped]

    _FALLBACK_TOTAL: Optional[Any] = Counter(
        "medscribe_offload_fallback_total",
        "Offloaded jobs that fell back to a thread after the process pool broke twice",
        ["pool"],
    )
except ImportError:
    _FALLBACK_TOTAL = None


class OffloadUnavailableError(RuntimeError):
    """The named pool was never started, or failed to start."""


class OffloadJobError(ValueError):
    """A job passed to run_ocr / run_compile is the wrong type or missing a required field."""


class OffloadTimeoutError(TimeoutError):
    """An offloaded job ran past its timeout."""

    def __init__(self, pool: str, job_id: str, timeout_s: int) -> None:
        super().__init__(f"{pool} job {job_id} exceeded {timeout_s}s")
        self.pool = pool
        self.job_id = job_id
        self.timeout_s = timeout_s


# ── Job and result types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class OcrJob:
    """Keyword arguments ``process_document`` already takes."""

    file_path: str
    session_id: str
    patient_id: str
    patient_history: Optional[Dict[str, Any]]
    original_filename: Optional[str]


@dataclass(frozen=True)
class CompileJob:
    """What a child needs to rebuild the caller's WorkflowEngine and run the graph."""

    state: Dict[str, Any]
    thread_id: str
    enable_checkpointing: bool
    enable_interrupts: bool
    use_db: bool


# GraphState keys the compile routes read back (RunPipelineResponse,
# InternalPipelineResponse) plus flags for processing_error.
COMPILE_RESULT_KEYS = (
    "clinical_note",
    "structured_record",
    "clinical_suggestions",
    "validation_report",
    "message",
    "flags",
)


@dataclass(frozen=True)
class OffloadResult(Generic[T]):
    value: T
    mode: OffloadMode


# ── Child entry points (module-level so they pickle by reference) ──────────


def _ocr_child(job: OcrJob):
    from app.core.ocr.pipeline import process_document

    result = asyncio.run(
        process_document(
            file_path=job.file_path,
            session_id=job.session_id,
            patient_id=job.patient_id,
            patient_history=job.patient_history,
            original_filename=job.original_filename,
        )
    )
    # No route reads per-page region details, and they carry page-sized
    # metadata across the pipe. full_text and page_count stay.
    result.pages = []
    return result


def _compile_child(job: CompileJob) -> Dict[str, Any]:
    from app.core.pipeline_progress import pipeline_progress_store
    from app.core.workflow_engine import WorkflowEngine

    session_id = job.state.get("session_id", job.thread_id)
    if not pipeline_progress_store._redis_available:
        logger.warning(
            "offload compile: progress store has no Redis; status endpoint "
            "will not see child progress session_id=%s",
            session_id,
        )

    db = None
    if job.use_db:
        from app.database.session import SessionLocal

        db = SessionLocal()
    try:
        engine = WorkflowEngine(
            enable_checkpointing=job.enable_checkpointing,
            enable_interrupts=job.enable_interrupts,
            db_session=db,
        )
        final_state = engine._stream_with_progress(
            job.state, engine._get_config(job.thread_id), session_id
        )
        return {k: final_state.get(k) for k in COMPILE_RESULT_KEYS if k in final_state}
    finally:
        if db is not None:
            db.close()


def _invoke(fn: Callable[[Any], T], job: Any) -> tuple[float, float, T]:
    """Run ``fn`` and report wall-clock start and run seconds for queue-wait logging."""
    started = time.time()
    value = fn(job)
    return started, time.time() - started, value


def _init_child(ocr_threads: Optional[int], log_level: str) -> None:
    from app.logging import configure_logging

    configure_logging(level=log_level)
    if ocr_threads is not None:
        try:
            from app.core.ocr.extractor import _get_paddle_ocr, set_rapid_ocr_threads

            set_rapid_ocr_threads(ocr_threads)
            _get_paddle_ocr()
        except Exception:
            logger.warning("offload: RapidOCR warm-up failed; first job loads it", exc_info=True)


# ── Pools ───────────────────────────────────────────────────────────────────


class _Pool:
    def __init__(self, name: str, workers: int, timeout_s: int,
                 ocr_threads: Optional[int], log_level: str) -> None:
        self.name = name
        self.workers = workers
        self.timeout_s = timeout_s
        self._ocr_threads = ocr_threads
        self._log_level = log_level
        self.executor: Optional[ProcessPoolExecutor] = None

    def start(self) -> None:
        self.executor = ProcessPoolExecutor(
            max_workers=self.workers,
            # spawn, not fork: fork would copy the parent's DB connections,
            # Redis clients, and threads into the child.
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_init_child,
            initargs=(self._ocr_threads, self._log_level),
        )

    def restart(self) -> None:
        self.shutdown()
        self.start()

    def shutdown(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
            self.executor = None


_pools: Dict[str, _Pool] = {}
_start_error: Optional[BaseException] = None


def start(config, log_level: str = "INFO") -> None:
    """Create both pools. ``config`` is ``Settings.offload`` (an OffloadConfig)."""
    global _start_error
    if config is None:
        raise OffloadUnavailableError("offload.start: config (Settings.offload) is required")
    shutdown()
    _start_error = None
    try:
        for pool in (
            _Pool("ocr", config.ocr_pool_workers, config.ocr_job_timeout_s,
                  ocr_threads=config.ocr_child_threads, log_level=log_level),
            _Pool("compile", config.compile_pool_workers, config.compile_job_timeout_s,
                  ocr_threads=None, log_level=log_level),
        ):
            pool.start()
            _pools[pool.name] = pool
            logger.info(
                "offload: %s pool started workers=%d timeout_s=%d ocr_threads=%s",
                pool.name, pool.workers, pool.timeout_s, pool._ocr_threads,
            )
    except Exception as exc:
        _start_error = exc
        logger.error("offload: pool startup failed: %s", exc, exc_info=True)
        shutdown()
        raise


def shutdown() -> None:
    for pool in list(_pools.values()):
        pool.shutdown()
        logger.info("offload: %s pool shut down", pool.name)
    _pools.clear()


def require_pool(name: str) -> None:
    """Raise OffloadUnavailableError unless pool ``name`` is running."""
    _get_pool(name)


def _get_pool(name: str) -> _Pool:
    pool = _pools.get(name)
    if pool is None or pool.executor is None:
        reason = f"startup failed: {_start_error}" if _start_error else "not started"
        raise OffloadUnavailableError(f"offload pool '{name}' is unavailable ({reason})")
    return pool


async def _run(pool_name: str, fn: Callable[[Any], T], job: Any, ids: Dict[str, str]) -> OffloadResult[T]:
    pool = _get_pool(pool_name)
    job_id = uuid.uuid4().hex[:12]
    ctx = " ".join(f"{k}={v}" for k, v in ids.items())
    loop = asyncio.get_running_loop()
    logger.info("offload: %s job start job_id=%s %s", pool_name, job_id, ctx)

    for attempt in (1, 2):
        submitted = time.time()
        executor = pool.executor
        try:
            started, run_s, value = await asyncio.wait_for(
                loop.run_in_executor(executor, _invoke, fn, job),
                timeout=pool.timeout_s,
            )
        except BrokenProcessPool as exc:
            logger.error(
                "offload: %s pool broke job_id=%s attempt=%d %s: %s; recreating pool",
                pool_name, job_id, attempt, ctx, exc,
            )
            # Concurrent jobs see the same broken executor; restart it once.
            if pool.executor is executor:
                pool.restart()
            continue
        except asyncio.TimeoutError:
            logger.error(
                "offload: %s job timed out job_id=%s timeout_s=%d %s; child keeps its slot until it finishes",
                pool_name, job_id, pool.timeout_s, ctx,
            )
            raise OffloadTimeoutError(pool_name, job_id, pool.timeout_s) from None
        except Exception as exc:
            logger.error(
                "offload: %s job failed in child job_id=%s %s: %s: %s",
                pool_name, job_id, ctx, type(exc).__name__, exc,
            )
            raise
        logger.info(
            "offload: %s job done job_id=%s %s mode=process queue_wait_ms=%d run_ms=%d",
            pool_name, job_id, ctx,
            max(0, (started - submitted) * 1000), run_s * 1000,
        )
        return OffloadResult(value=value, mode="process")

    logger.warning(
        "offload: %s pool broke twice job_id=%s %s; expected a child process, "
        "running the job in a thread instead mode=thread_fallback",
        pool_name, job_id, ctx,
    )
    if _FALLBACK_TOTAL is not None:
        _FALLBACK_TOTAL.labels(pool=pool_name).inc()
    t0 = time.monotonic()
    try:
        value = await asyncio.wait_for(asyncio.to_thread(fn, job), timeout=pool.timeout_s)
    except asyncio.TimeoutError:
        logger.error(
            "offload: %s thread fallback timed out job_id=%s timeout_s=%d %s",
            pool_name, job_id, pool.timeout_s, ctx,
        )
        raise OffloadTimeoutError(pool_name, job_id, pool.timeout_s) from None
    logger.info(
        "offload: %s job done job_id=%s %s mode=thread_fallback run_ms=%d",
        pool_name, job_id, ctx, (time.monotonic() - t0) * 1000,
    )
    return OffloadResult(value=value, mode="thread_fallback")


async def run_ocr(job: OcrJob, *, doc_id: str) -> OffloadResult:
    """Run ``process_document`` in the OCR pool. ``doc_id`` is the stored upload name."""
    if not isinstance(job, OcrJob):
        raise OffloadJobError(f"run_ocr: job must be OcrJob, got {type(job).__name__}")
    if not job.file_path or not job.session_id:
        raise OffloadJobError(
            f"run_ocr: file_path and session_id are required, got "
            f"file_path={job.file_path!r} session_id={job.session_id!r}"
        )
    return await _run("ocr", _ocr_child, job, {"session_id": job.session_id, "doc_id": doc_id})


async def run_compile(job: CompileJob) -> OffloadResult[Dict[str, Any]]:
    """Run the Lane B graph in the compile pool; returns COMPILE_RESULT_KEYS only."""
    if not isinstance(job, CompileJob):
        raise OffloadJobError(f"run_compile: job must be CompileJob, got {type(job).__name__}")
    if not job.thread_id or not isinstance(job.state, dict) or not job.state.get("session_id"):
        raise OffloadJobError(
            f"run_compile: thread_id and state.session_id are required, got "
            f"thread_id={job.thread_id!r} session_id={job.state.get('session_id') if isinstance(job.state, dict) else None!r}"
        )
    return await _run("compile", _compile_child, job, {"session_id": job.state["session_id"]})
