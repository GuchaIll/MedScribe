"""Retrieval eval runner (#104).

Seeds the synthetic corpus through the production chunk + embed path, runs
every query through ``HybridRetrievalService.search_chunks_for_patient``,
scores the results, and writes an evidence pack.

    cd server
    DATABASE_URL=postgresql://.../medscribe_eval \\
        python -m evals.retrieval --artifacts-dir ../docs/benchmarks/retrieval-accuracy

The run aborts rather than publishing a number when the dataset is invalid,
a dependency is missing, or the retriever silently degraded (one of its legs
caught an exception and returned nothing).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import platform
import re
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from evals.retrieval.dataset import STRATA, ResolvedEvalSet, load_eval_set
from evals.retrieval.errors import (
    DatasetError,
    EvalDependencyError,
    RetrievalEvalError,
    RetrieverDegradedError,
)
from evals.retrieval.metrics import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    bootstrap_mean,
    count_leaks,
    first_hit_rank,
    percentile,
    random_recall_at_k,
    rank_metrics,
)

logger = logging.getLogger("evals.retrieval")

SEED_PREFIX = "evalr1-"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[1] / "datasets" / "retrieval_v1"
REQUIRED_TABLES = ("users", "patients", "sessions", "chunk_embeddings")
WATCHED_LOGGERS = ("app.services.hybrid_retrieval", "app.services.embedding_service")
LEG_K = 10
_VECTOR_LITERAL = re.compile(r"'\[[^\]]*\]'::vector")


@dataclass(frozen=True)
class RunConfig:
    dataset_dir: Path
    artifacts_dir: Path
    database_url: str
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES
    seed: int = DEFAULT_BOOTSTRAP_SEED

    def validate(self) -> None:
        if not self.database_url or not self.database_url.strip():
            raise EvalDependencyError("database_url is empty; set DATABASE_URL or pass --database-url")
        if not self.database_url.startswith("postgresql"):
            raise EvalDependencyError(
                f"database_url scheme must be postgresql (pgvector), got {self.database_url.split(':', 1)[0]!r}"
            )
        if not self.dataset_dir.is_dir():
            raise DatasetError(f"dataset_dir not found: {self.dataset_dir}")
        if self.resamples < 100:
            raise RetrievalEvalError(f"resamples must be >= 100, got {self.resamples}")


@dataclass(frozen=True)
class QueryOutcome:
    """Per-query result. Every field is written to results.json; ranks feed the metrics."""

    query_id: str
    patient_id: str
    stratum: str
    rank_k5: Optional[int]
    rank_k10: Optional[int]
    dense_rank: Optional[int]
    sparse_rank: Optional[int]
    returned_k5: int
    returned_k10: int
    returned_dense: int
    returned_sparse: int
    leaks: int
    latency_ms_k5: float


# ── Degradation capture ──────────────────────────────────────────────────────


class _WarningCapture(logging.Handler):
    """Collects WARNING+ records from the retriever's loggers."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def capture_retriever_warnings() -> Iterator[_WarningCapture]:
    handler = _WarningCapture()
    loggers = [logging.getLogger(name) for name in WATCHED_LOGGERS]
    for lg in loggers:
        lg.addHandler(handler)
    try:
        yield handler
    finally:
        for lg in loggers:
            lg.removeHandler(handler)


def _raise_if_degraded(capture: _WarningCapture, query_id: str) -> None:
    if capture.records:
        first = capture.records[0]
        # Message names the failing leg and exception class; truncated, no query text.
        raise RetrieverDegradedError(
            f"retriever degraded on {query_id}: {len(capture.records)} warning(s) from "
            f"{first.name}; first: {first.getMessage()[:200]!r}"
        )


# ── Preflight ────────────────────────────────────────────────────────────────


def preflight_database(database_url: str):
    """Return an engine after checking reachability, db name, pgvector, and schema."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError

    url = make_url(database_url)
    safe = url.render_as_string(hide_password=True)
    if "eval" not in (url.database or ""):
        raise EvalDependencyError(
            f"refusing to seed database {url.database!r}: name must contain 'eval' "
            f"so the eval never writes to a dev or prod database ({safe})"
        )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            ext = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            if ext is None:
                raise EvalDependencyError(f"pgvector extension not installed in {safe}")
            missing = [t for t in REQUIRED_TABLES if not inspect(conn).has_table(t)]
            if missing:
                raise EvalDependencyError(
                    f"tables {missing} missing in {safe}; run `alembic upgrade head` first"
                )
    except SQLAlchemyError as exc:
        engine.dispose()
        raise EvalDependencyError(f"database unreachable at {safe}: {type(exc).__name__}") from exc
    logger.info("preflight ok: db=%s host=%s pgvector=%s", url.database, url.host, ext)
    return engine


def load_embedding_service(db):
    """Construct the production EmbeddingService and force the model load now."""
    from app.services.embedding_service import EmbeddingService

    svc = EmbeddingService(db=db)
    try:
        dim = svc.model.get_sentence_embedding_dimension()
    except Exception as exc:  # model load raises RuntimeError subclasses and OSError
        logger.exception("embedding model failed to load: model=%s", svc.model_name)
        raise EvalDependencyError(
            f"embedding model {svc.model_name!r} failed to load ({type(exc).__name__}); "
            "no sparse-only fallback is used"
        ) from exc
    logger.info("embedding model loaded: model=%s dim=%d", svc.model_name, dim)
    return svc


# ── Seeding ──────────────────────────────────────────────────────────────────


def seeded_id(raw: str) -> str:
    return f"{SEED_PREFIX}{raw}"


def seed_corpus(db, eval_set: ResolvedEvalSet, embedding_service) -> Dict[str, int]:
    """Replace prior eval rows and write users/patients/sessions/chunk_embeddings.

    Chunks are the exact ``eval_set.chunks`` the gold labels resolved
    against, written through ``EmbeddingService.store_chunk_embeddings_batch``.
    """
    from sqlalchemy import text

    like = f"{SEED_PREFIX}%"
    deleted = db.execute(
        text("DELETE FROM chunk_embeddings WHERE session_id LIKE :p"), {"p": like}
    ).rowcount
    db.execute(text("DELETE FROM sessions WHERE id LIKE :p"), {"p": like})
    db.execute(text("DELETE FROM patients WHERE id LIKE :p"), {"p": like})
    db.execute(text("DELETE FROM users WHERE id LIKE :p"), {"p": like})
    if deleted:
        logger.warning("removed %d chunk rows from a previous eval run before reseeding", deleted)

    # Raw SQL, not the ORM: app.database.models binds SQLEnum(UserRole) and
    # SQLEnum(SessionStatus) by enum *name* ('DOCTOR'), while migration
    # 000_initial creates the Postgres enums with lowercase *values*
    # ('doctor'), so ORM inserts of User/Session fail on a migrated database.
    # The chunk rows below still go through the production EmbeddingService.
    doctor_id = seeded_id("doctor")
    db.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password, role, is_active, created_at, updated_at) "
            "VALUES (:id, :id, :email, '!', 'doctor', true, now(), now())"
        ),
        {"id": doctor_id, "email": f"{doctor_id}@example.invalid"},
    )
    patients = sorted({d.patient_id for d in eval_set.documents})
    for pid in patients:
        db.execute(
            text(
                "INSERT INTO patients (id, mrn, full_name, dob, is_active, created_at, updated_at) "
                "VALUES (:id, :mrn, :name, :dob, true, now(), now())"
            ),
            {
                "id": seeded_id(pid),
                "mrn": seeded_id(pid).upper(),
                "name": f"Synthetic Patient {pid.upper()}",
                "dob": datetime(1970, 1, 1),
            },
        )
        db.execute(
            text(
                "INSERT INTO sessions (id, patient_id, doctor_id, status, started_at) "
                "VALUES (:id, :pid, :doc, 'active', now())"
            ),
            {"id": seeded_id(pid), "pid": seeded_id(pid), "doc": doctor_id},
        )

    by_patient: Dict[str, List[Dict[str, Any]]] = {}
    for chunk in eval_set.chunks:
        row = dict(chunk)
        row["document_id"] = chunk["source_id"]
        by_patient.setdefault(eval_set.chunk_patient[chunk["chunk_id"]], []).append(row)

    stored = 0
    for pid in patients:
        t0 = time.perf_counter()
        n = embedding_service.store_chunk_embeddings_batch(seeded_id(pid), by_patient.get(pid, []))
        stored += n
        logger.info("seeded patient=%s chunks=%d ms=%.0f", pid, n, (time.perf_counter() - t0) * 1000)
    if stored != len(eval_set.chunks):
        raise RetrievalEvalError(f"stored {stored} chunks, expected {len(eval_set.chunks)}")
    db.commit()
    db.execute(text("ANALYZE chunk_embeddings"))
    db.commit()
    return {"patients": len(patients), "documents": len(eval_set.documents), "chunks": stored}


def collect_db_diagnostics(db, embedding_service, sample_patient: str) -> Dict[str, str]:
    """Record pgvector settings and the dense-leg query plan for the evidence pack."""
    from sqlalchemy import text

    diag: Dict[str, str] = {}
    diag["postgres_version"] = db.execute(text("SHOW server_version")).scalar() or "unknown"
    diag["pgvector_version"] = (
        db.execute(text("SELECT extversion FROM pg_extension WHERE extname='vector'")).scalar() or "unknown"
    )
    try:
        diag["ivfflat_probes"] = db.execute(text("SHOW ivfflat.probes")).scalar() or "unknown"
    except Exception as exc:
        db.rollback()
        logger.warning("could not read ivfflat.probes (%s); recording 'unavailable'", type(exc).__name__)
        diag["ivfflat_probes"] = "unavailable"

    vec = str(embedding_service.embed_text("diagnostic probe").tolist())
    # Same statement shape as HybridRetrievalService._dense_patient_chunk_search.
    plan = db.execute(
        text(
            """
            EXPLAIN SELECT ce.chunk_id, 1 - (ce.embedding <=> :v) AS similarity
            FROM chunk_embeddings ce JOIN sessions s ON s.id = ce.session_id
            WHERE s.patient_id = :p AND (1 - (ce.embedding <=> :v)) >= 0.30
            ORDER BY ce.embedding <=> :v LIMIT 10
            """
        ),
        {"v": vec, "p": sample_patient},
    ).scalars().all()
    diag["dense_plan_uses_ivfflat"] = str(any("idx_chk_embedding_cosine" in line for line in plan)).lower()
    diag["dense_plan"] = " | ".join(_VECTOR_LITERAL.sub("'<query_vec>'::vector", line.strip()) for line in plan)
    return diag


# ── Query loop ───────────────────────────────────────────────────────────────


def run_queries(hybrid, eval_set: ResolvedEvalSet) -> List[QueryOutcome]:
    outcomes: List[QueryOutcome] = []
    seeded_patient = {d.patient_id: seeded_id(d.patient_id) for d in eval_set.documents}

    with capture_retriever_warnings() as capture:
        for q in eval_set.queries:
            pid = seeded_patient[q.patient_id]
            t0 = time.perf_counter()
            top5 = hybrid.search_chunks_for_patient(pid, q.query, top_k=5)
            latency_ms = (time.perf_counter() - t0) * 1000
            top10 = hybrid.search_chunks_for_patient(pid, q.query, top_k=10)
            dense = hybrid._dense_patient_chunk_search(pid, q.query, LEG_K, hybrid.dense_threshold)
            sparse = hybrid._sparse_patient_chunk_search(pid, q.query, LEG_K)
            _raise_if_degraded(capture, q.query_id)

            ids5 = [r["chunk_id"] for r in top5]
            ids10 = [r["chunk_id"] for r in top10]
            ids_dense = [r["chunk_id"] for r in dense]
            ids_sparse = [r["chunk_id"] for r in sparse]
            gold = eval_set.gold_chunk_ids[q.query_id]
            positive = bool(gold)

            outcomes.append(
                QueryOutcome(
                    query_id=q.query_id,
                    patient_id=q.patient_id,
                    stratum=q.stratum,
                    rank_k5=first_hit_rank(ids5, gold) if positive else None,
                    rank_k10=first_hit_rank(ids10, gold) if positive else None,
                    dense_rank=first_hit_rank(ids_dense, gold) if positive else None,
                    sparse_rank=first_hit_rank(ids_sparse, gold) if positive else None,
                    returned_k5=len(ids5),
                    returned_k10=len(ids10),
                    returned_dense=len(ids_dense),
                    returned_sparse=len(ids_sparse),
                    leaks=count_leaks(
                        set(ids10) | set(ids5) | set(ids_dense) | set(ids_sparse),
                        q.patient_id,
                        eval_set.chunk_patient,
                    ),
                    latency_ms_k5=round(latency_ms, 2),
                )
            )
    return outcomes


# ── Scoring and report ───────────────────────────────────────────────────────


def build_report(
    outcomes: Sequence[QueryOutcome],
    eval_set: ResolvedEvalSet,
    seed_counts: Dict[str, int],
    resamples: int,
    seed: int,
) -> Dict[str, Any]:
    if not outcomes:
        raise RetrievalEvalError("no outcomes to score")
    positives = [o for o in outcomes if o.stratum != "negative"]
    negatives = [o for o in outcomes if o.stratum == "negative"]
    if not positives:
        raise RetrievalEvalError("no positive queries to score")

    def hybrid(rows: Sequence[QueryOutcome]) -> Dict[str, Any]:
        return rank_metrics([o.rank_k5 for o in rows], [o.rank_k10 for o in rows], resamples, seed)

    def leg(rows: Sequence[QueryOutcome], attr: str) -> Dict[str, Any]:
        ranks = [getattr(o, attr) for o in rows]
        # Each leg is a plain ORDER BY ... LIMIT, so its top 5 is a prefix of its top 10.
        top5 = [r if r is not None and r <= 5 else None for r in ranks]
        return rank_metrics(top5, ranks, resamples, seed)

    by_stratum = {
        s: hybrid([o for o in positives if o.stratum == s])
        for s in STRATA
        if s != "negative" and any(o.stratum == s for o in positives)
    }
    latencies = [o.latency_ms_k5 for o in outcomes]
    chunks_per_patient: Dict[str, int] = {}
    for pid in eval_set.chunk_patient.values():
        chunks_per_patient[pid] = chunks_per_patient.get(pid, 0) + 1

    def random_baseline(k: int) -> float:
        vals = [
            random_recall_at_k(
                chunks_per_patient[o.patient_id], len(eval_set.gold_chunk_ids[o.query_id]), k
            )
            for o in positives
        ]
        return round(sum(vals) / len(vals), 4)

    return {
        "dataset_version": eval_set.version,
        "corpus": {
            **seed_counts,
            "chunks_per_patient_min": min(chunks_per_patient.values()),
            "chunks_per_patient_max": max(chunks_per_patient.values()),
            "queries": len(outcomes),
            "positive_queries": len(positives),
            "negative_queries": len(negatives),
        },
        "retriever": {
            "entry_point": "HybridRetrievalService.search_chunks_for_patient",
            "calls_per_query": "top_k=5 (recall@1, recall@5) and top_k=10 (recall@10, mrr@10)",
        },
        "hybrid": {"overall": hybrid(positives), "by_stratum": by_stratum},
        "random_baseline": {
            "recall_at_1": random_baseline(1),
            "recall_at_5": random_baseline(5),
            "recall_at_10": random_baseline(10),
            "note": "expected recall if k chunks were drawn at random from the patient's own pool",
        },
        "dense_leg": leg(positives, "dense_rank"),
        "sparse_leg": leg(positives, "sparse_rank"),
        "dense_leg_empty_on_positives": sum(1 for o in positives if o.returned_dense == 0),
        "sparse_leg_empty_on_positives": sum(1 for o in positives if o.returned_sparse == 0),
        "returned_median_all_queries": {
            "top_k5": statistics.median(o.returned_k5 for o in outcomes),
            "top_k10": statistics.median(o.returned_k10 for o in outcomes),
            "dense_leg_k10": statistics.median(o.returned_dense for o in outcomes),
            "sparse_leg_k10": statistics.median(o.returned_sparse for o in outcomes),
            "note": "the dense leg drops rows below cosine 0.30, so lists are often shorter than k",
        },
        "negatives": {
            "n": len(negatives),
            "nonempty_rate": (
                bootstrap_mean([1.0 if o.returned_k5 > 0 else 0.0 for o in negatives], resamples, seed).as_dict()
                if negatives
                else None
            ),
        },
        "leakage": {"foreign_chunks_returned": sum(o.leaks for o in outcomes)},
        "latency_ms_top_k5": {
            "p50": round(percentile(latencies, 50), 2),
            "p95": round(percentile(latencies, 95), 2),
            "note": "end to end in-process: query embedding + both SQL legs + RRF",
        },
        "bootstrap": {"resamples": resamples, "seed": seed, "method": "percentile, 95%"},
        "per_query": [asdict(o) for o in outcomes],
    }


def write_artifacts(artifacts_dir: Path, report: Dict[str, Any], metadata: Dict[str, str]) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = [f"{k}={v}" for k, v in metadata.items()]
    (artifacts_dir / "run-metadata.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("artifacts written: dir=%s", _display_path(artifacts_dir))


def _display_path(path: Path) -> str:
    """Repo-relative path for logs and metadata, so local home paths are not published."""
    repo_root = Path(__file__).resolve().parents[3]
    try:
        return str(path.resolve().relative_to(repo_root))
    except ValueError:
        return path.name


def format_summary(report: Dict[str, Any]) -> str:
    def fmt(m: Dict[str, Any]) -> str:
        return f"{m['value']:.3f} [{m['ci95'][0]:.3f}, {m['ci95'][1]:.3f}]"

    out = []
    c = report["corpus"]
    out.append(
        f"dataset {report['dataset_version']}: {c['patients']} patients, {c['documents']} docs, "
        f"{c['chunks']} chunks ({c['chunks_per_patient_min']}-{c['chunks_per_patient_max']} per patient), "
        f"{c['queries']} queries ({c['positive_queries']} positive, {c['negative_queries']} negative)"
    )
    out.append(f"{'':16}{'n':>4}  {'recall@1':<22}{'recall@5':<22}{'recall@10':<22}{'mrr@10':<22}")

    def row(name: str, m: Dict[str, Any]) -> str:
        return (
            f"{name:16}{m['n']:>4}  {fmt(m['recall_at_1']):<22}{fmt(m['recall_at_5']):<22}"
            f"{fmt(m['recall_at_10']):<22}{fmt(m['mrr_at_10']):<22}"
        )

    out.append(row("hybrid", report["hybrid"]["overall"]))
    for s, m in report["hybrid"]["by_stratum"].items():
        out.append(row(f"  {s}", m))
    rb = report["random_baseline"]
    out.append(
        f"{'random baseline':16}{'':>4}  {rb['recall_at_1']:<22.3f}{rb['recall_at_5']:<22.3f}{rb['recall_at_10']:<22.3f}"
    )
    out.append(row("dense leg", report["dense_leg"]))
    out.append(row("sparse leg", report["sparse_leg"]))
    neg = report["negatives"]
    if neg["nonempty_rate"]:
        out.append(f"negatives: {neg['n']}, returned >=1 chunk: {fmt(neg['nonempty_rate'])}")
    rm = report["returned_median_all_queries"]
    out.append(
        f"median chunks returned: top_k=5 -> {rm['top_k5']}, top_k=10 -> {rm['top_k10']}, "
        f"dense leg -> {rm['dense_leg_k10']}, sparse leg -> {rm['sparse_leg_k10']}; "
        f"dense leg empty on {report['dense_leg_empty_on_positives']} of {report['corpus']['positive_queries']} positives"
    )
    out.append(f"leakage (foreign chunks returned): {report['leakage']['foreign_chunks_returned']}")
    lat = report["latency_ms_top_k5"]
    out.append(f"latency top_k=5 ms: p50={lat['p50']} p95={lat['p95']}")
    return "\n".join(out)


# ── Entry point ──────────────────────────────────────────────────────────────


def run(config: RunConfig) -> Dict[str, Any]:
    config.validate()
    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    logger.info("retrieval eval start: run_id=%s dataset=%s", run_id, config.dataset_dir.name)

    eval_set = load_eval_set(config.dataset_dir)
    engine = preflight_database(config.database_url)

    from sqlalchemy.orm import sessionmaker

    from app.services.hybrid_retrieval import HybridRetrievalService

    db = sessionmaker(bind=engine)()
    try:
        embedding_service = load_embedding_service(db)
        seed_counts = seed_corpus(db, eval_set, embedding_service)
        diag = collect_db_diagnostics(db, embedding_service, seeded_id(eval_set.queries[0].patient_id))
        hybrid = HybridRetrievalService(db, embedding_service)
        outcomes = run_queries(hybrid, eval_set)
        report = build_report(outcomes, eval_set, seed_counts, config.resamples, config.seed)
    except Exception as exc:
        logger.error("retrieval eval aborted: run_id=%s error=%s", run_id, type(exc).__name__)
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()

    from sqlalchemy.engine import make_url

    import sentence_transformers
    import torch

    url = make_url(config.database_url)
    metadata = {
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_version": eval_set.version,
        "dataset_dir": str(config.dataset_dir.relative_to(Path(__file__).resolve().parents[2])),
        "embedding_model": embedding_service.model_name,
        "rrf_k": str(hybrid.rrf_k),
        "dense_threshold": str(hybrid.dense_threshold),
        "chunker": "app.agents.nodes.segment.chunk_documents (500 chars, 50 overlap)",
        "database": f"{url.host}:{url.port}/{url.database}",
        **diag,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "sentence_transformers": sentence_transformers.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "duration_s": f"{time.perf_counter() - started:.1f}",
    }
    report["run_id"] = run_id
    write_artifacts(config.artifacts_dir, report, metadata)
    logger.info(
        "retrieval eval end: run_id=%s queries=%d duration_s=%s",
        run_id, len(outcomes), metadata["duration_s"],
    )
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.retrieval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--bootstrap-resamples", type=int, default=DEFAULT_BOOTSTRAP_RESAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = RunConfig(
        dataset_dir=args.dataset_dir.resolve(),
        artifacts_dir=args.artifacts_dir.resolve(),
        database_url=args.database_url,
        resamples=args.bootstrap_resamples,
        seed=args.seed,
    )
    try:
        report = run(config)
    except DatasetError as exc:
        logger.error("dataset error: %s", exc)
        return 2
    except EvalDependencyError as exc:
        logger.error("dependency error: %s", exc)
        return 3
    except RetrieverDegradedError as exc:
        logger.error("retriever degraded, no report written: %s", exc)
        return 4
    except RetrievalEvalError as exc:
        logger.error("eval error: %s", exc)
        return 1
    print(format_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
