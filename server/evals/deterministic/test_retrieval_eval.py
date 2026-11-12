"""L1 deterministic tests for the retrieval eval (#104). No DB, no model.

Covers the scorer, the dataset loaders and their failure paths, gold
resolution, the committed retrieval_v1 dataset's integrity, and the
runner's guards (config, db-name guard, degraded-retriever abort).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pytest

from evals.retrieval.dataset import (
    STRATA,
    CorpusDocument,
    EvalQuery,
    load_corpus,
    load_eval_set,
    load_queries,
    normalize_text,
    resolve_eval_set,
)
from evals.retrieval.errors import (
    DatasetError,
    EvalDependencyError,
    GoldResolutionError,
    MetricInputError,
    RetrievalEvalError,
    RetrieverDegradedError,
)
from evals.retrieval.metrics import (
    bootstrap_mean,
    count_leaks,
    first_hit_rank,
    percentile,
    random_recall_at_k,
    rank_metrics,
)
from evals.retrieval.runner import (
    DEFAULT_DATASET_DIR,
    QueryOutcome,
    RunConfig,
    build_report,
    preflight_database,
    run_queries,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def one_chunk_per_paragraph(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic fake chunker: split on blank lines."""
    out = []
    for d in docs:
        for i, para in enumerate(p for p in d["extracted_text"].split("\n\n") if p.strip()):
            out.append(
                {
                    "chunk_id": f"{d['document_id']}#{i}",
                    "source": "document",
                    "source_id": d["document_id"],
                    "text": para,
                    "start": None,
                    "end": None,
                    "metadata": {},
                }
            )
    return out


def q(qid: str, pid: str, stratum: str, gold: List[tuple]) -> EvalQuery:
    return EvalQuery(
        query_id=qid,
        patient_id=pid,
        query="some query text",
        stratum=stratum,
        gold=[{"doc_id": d, "quote": t} for d, t in gold],
    )


DOCS = [
    CorpusDocument(doc_id="a_note", patient_id="pa", text="Allergy to penicillin noted.\n\nMetformin 500 mg twice daily."),
    CorpusDocument(doc_id="a_labs", patient_id="pa", text="Hemoglobin A1c 7.6 percent."),
    CorpusDocument(doc_id="b_note", patient_id="pb", text="Warfarin 5 mg daily, INR goal 2.5 to 3.5."),
]


def write_jsonl(path: Path, rows: List[Any]) -> Path:
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n")
    return path


GOOD_ROW = {
    "query_id": "x-q01",
    "patient_id": "pa",
    "query": "metformin dose",
    "stratum": "medication",
    "gold": [{"doc_id": "a_note", "quote": "Metformin 500 mg twice daily"}],
}


# ── Metrics ──────────────────────────────────────────────────────────────────


class TestMetrics:
    def test_first_hit_rank_found_and_missing(self):
        assert first_hit_rank(["c1", "c2", "c3"], frozenset({"c2"})) == 2
        assert first_hit_rank(["c1"], frozenset({"c9"})) is None
        assert first_hit_rank([], frozenset({"c9"})) is None

    def test_first_hit_rank_rejects_empty_or_wrong_type_gold(self):
        with pytest.raises(MetricInputError, match="empty"):
            first_hit_rank(["c1"], frozenset())
        with pytest.raises(MetricInputError, match="frozenset"):
            first_hit_rank(["c1"], {"c1"})  # type: ignore[arg-type]

    def test_rank_metrics_values(self):
        m = rank_metrics([1, 3, None, None], [1, 3, 7, None], resamples=200)
        assert m["n"] == 4
        assert m["recall_at_1"]["value"] == 0.25
        assert m["recall_at_5"]["value"] == 0.5
        assert m["recall_at_10"]["value"] == 0.75
        assert m["mrr_at_10"]["value"] == pytest.approx((1 + 1 / 3 + 1 / 7) / 4, abs=1e-4)

    @pytest.mark.parametrize(
        "k5,k10,match",
        [
            ([1], [1, 2], "expected equal"),
            ([], [], "no queries"),
            ([6], [6], "> 5"),
            ([1], [11], "> 10"),
            ([0], [1], "invalid rank"),
            ([True], [1], "invalid rank"),
        ],
    )
    def test_rank_metrics_rejects_bad_input(self, k5, k10, match):
        with pytest.raises(MetricInputError, match=match):
            rank_metrics(k5, k10, resamples=200)

    def test_bootstrap_is_deterministic_and_brackets_mean(self):
        vals = [1.0] * 70 + [0.0] * 30
        a = bootstrap_mean(vals, resamples=500, seed=7)
        b = bootstrap_mean(vals, resamples=500, seed=7)
        assert a == b
        assert a.ci_low <= a.value <= a.ci_high
        assert a.value == pytest.approx(0.7)

    def test_bootstrap_single_and_empty(self):
        e = bootstrap_mean([1.0], resamples=200)
        assert (e.value, e.ci_low, e.ci_high) == (1.0, 1.0, 1.0)
        with pytest.raises(MetricInputError):
            bootstrap_mean([])
        with pytest.raises(MetricInputError, match="resamples"):
            bootstrap_mean([1.0, 0.0], resamples=10)

    def test_random_recall(self):
        assert random_recall_at_k(11, 1, 5) == pytest.approx(5 / 11)
        assert random_recall_at_k(4, 1, 10) == 1.0  # k larger than pool
        with pytest.raises(MetricInputError, match="exceeds"):
            random_recall_at_k(3, 4, 5)
        with pytest.raises(MetricInputError, match="pool_size"):
            random_recall_at_k(0, 1, 5)

    def test_percentile_nearest_rank(self):
        assert percentile([5.0, 1.0, 3.0, 2.0, 4.0], 50) == 3.0
        assert percentile(list(map(float, range(1, 101))), 95) == 95.0
        with pytest.raises(MetricInputError):
            percentile([], 50)
        with pytest.raises(MetricInputError):
            percentile([1.0], 0)

    def test_count_leaks_counts_foreign_and_unknown(self):
        owner = {"c1": "pa", "c2": "pb"}
        assert count_leaks(["c1"], "pa", owner) == 0
        assert count_leaks(["c1", "c2", "c-unknown"], "pa", owner) == 2


# ── Loaders ──────────────────────────────────────────────────────────────────


class TestLoadQueries:
    def test_good_row_and_blank_lines(self, tmp_path):
        p = write_jsonl(tmp_path / "q.jsonl", [GOOD_ROW, ""])
        assert [x.query_id for x in load_queries(p)] == ["x-q01"]

    @pytest.mark.parametrize(
        "row,match",
        [
            ("{not json", "invalid JSON"),
            ({**GOOD_ROW, "query": ""}, "query"),
            ({k: v for k, v in GOOD_ROW.items() if k != "gold"}, "gold"),
            ({**GOOD_ROW, "stratum": "vibes"}, "stratum"),
            ({**GOOD_ROW, "stratum": "negative"}, "must have empty gold"),
            ({**GOOD_ROW, "gold": []}, "requires at least one gold"),
            ({**GOOD_ROW, "extra": 1}, "extra"),
            ({**GOOD_ROW, "query_id": "Has Spaces"}, "query_id"),
            ({**GOOD_ROW, "gold": [{"doc_id": "a_note", "quote": "short"}]}, "quote"),
        ],
    )
    def test_malformed_rows_raise_with_line_number(self, tmp_path, row, match):
        p = write_jsonl(tmp_path / "q.jsonl", [GOOD_ROW | {"query_id": "x-q00"}, row])
        with pytest.raises(DatasetError, match=match) as exc:
            load_queries(p)
        assert "q.jsonl:2" in str(exc.value)

    def test_duplicate_query_id(self, tmp_path):
        p = write_jsonl(tmp_path / "q.jsonl", [GOOD_ROW, GOOD_ROW])
        with pytest.raises(DatasetError, match="duplicate query_id"):
            load_queries(p)

    def test_missing_empty_and_wrong_type(self, tmp_path):
        with pytest.raises(DatasetError, match="not found"):
            load_queries(tmp_path / "nope.jsonl")
        (tmp_path / "empty.jsonl").write_text("\n\n")
        with pytest.raises(DatasetError, match="no rows"):
            load_queries(tmp_path / "empty.jsonl")
        with pytest.raises(DatasetError, match="pathlib.Path"):
            load_queries("q.jsonl")  # type: ignore[arg-type]


class TestLoadCorpus:
    def _corpus(self, tmp_path: Path) -> Path:
        root = tmp_path / "corpus"
        (root / "pa").mkdir(parents=True)
        (root / "pa" / "a_note.txt").write_text("Some text.")
        return root

    def test_good(self, tmp_path):
        docs = load_corpus(self._corpus(tmp_path))
        assert [(d.patient_id, d.doc_id) for d in docs] == [("pa", "a_note")]

    def test_empty_doc_bad_id_non_txt_duplicate(self, tmp_path):
        root = self._corpus(tmp_path)
        (root / "pa" / "blank.txt").write_text("   \n")
        (root / "pa" / "notes.md").write_text("x")
        (root / "Bad Patient").mkdir()
        (root / "pb").mkdir()
        (root / "pb" / "a_note.txt").write_text("dup id")
        with pytest.raises(DatasetError) as exc:
            load_corpus(root)
        msg = str(exc.value)
        assert "document is empty" in msg
        assert "expected a .txt document" in msg
        assert "does not match" in msg
        assert "duplicate doc_id 'a_note'" in msg

    def test_missing_and_empty_dir(self, tmp_path):
        with pytest.raises(DatasetError, match="not found"):
            load_corpus(tmp_path / "missing")
        (tmp_path / "empty").mkdir()
        with pytest.raises(DatasetError, match="no documents"):
            load_corpus(tmp_path / "empty")


# ── Gold resolution ──────────────────────────────────────────────────────────


class TestResolve:
    def test_resolves_to_chunk_ids_and_owner(self):
        s = resolve_eval_set(
            DOCS,
            [q("q1", "pa", "medication", [("a_note", "metformin 500 MG   twice daily")]), q("q2", "pa", "negative", [])],
            chunker=one_chunk_per_paragraph,
        )
        assert s.gold_chunk_ids == {"q1": frozenset({"a_note#1"}), "q2": frozenset()}
        assert s.chunk_patient["b_note#0"] == "pb"

    @pytest.mark.parametrize(
        "query,err,match",
        [
            (q("q1", "pz", "medication", [("a_note", "Metformin 500 mg")]), DatasetError, "has no documents"),
            (q("q1", "pa", "medication", [("zz_doc", "Metformin 500 mg")]), DatasetError, "not in corpus"),
            (q("q1", "pa", "medication", [("b_note", "Warfarin 5 mg daily")]), DatasetError, "belongs to 'pb'"),
            (q("q1", "pa", "medication", [("a_note", "Lisinopril 20 mg")]), GoldResolutionError, "not found"),
            (
                q("q1", "pa", "medication", [("a_note", "penicillin noted.\n\nMetformin")]),
                GoldResolutionError,
                "straddles a chunk boundary",
            ),
        ],
    )
    def test_bad_gold(self, query, err, match):
        with pytest.raises(err, match=match):
            resolve_eval_set(DOCS, [query], chunker=one_chunk_per_paragraph)

    def test_ambiguous_quote_across_documents(self):
        docs = DOCS + [CorpusDocument(doc_id="a_dup", patient_id="pa", text="Metformin 500 mg twice daily.")]
        with pytest.raises(GoldResolutionError, match="ambiguous"):
            resolve_eval_set(
                docs,
                [q("q1", "pa", "medication", [("a_note", "Metformin 500 mg twice daily")])],
                chunker=one_chunk_per_paragraph,
            )

    def test_empty_inputs_and_bad_chunker_output(self):
        good = [q("q1", "pa", "medication", [("a_note", "Metformin 500 mg")])]
        with pytest.raises(DatasetError, match="documents is empty"):
            resolve_eval_set([], good, chunker=one_chunk_per_paragraph)
        with pytest.raises(DatasetError, match="queries is empty"):
            resolve_eval_set(DOCS, [], chunker=one_chunk_per_paragraph)
        with pytest.raises(GoldResolutionError, match="no chunks"):
            resolve_eval_set(DOCS, good, chunker=lambda docs: [])

    def test_normalize(self):
        assert normalize_text("  A1c:\n7.6  %") == "a1c: 7.6 %"


# ── Committed dataset integrity ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def v1_set():
    return load_eval_set(DEFAULT_DATASET_DIR)


class TestRetrievalV1Dataset:
    @pytest.fixture()
    def eval_set(self, v1_set):
        return v1_set

    def test_size_and_strata(self, eval_set):
        assert len(eval_set.queries) == 100
        counts = {s: sum(1 for x in eval_set.queries if x.stratum == s) for s in STRATA}
        assert counts == {"exact_term": 22, "paraphrase": 22, "numeric": 22, "medication": 22, "negative": 12}

    def test_patients_and_resolution(self, eval_set):
        patients = {d.patient_id for d in eval_set.documents}
        assert 8 <= len(patients) <= 12
        for x in eval_set.queries:
            assert bool(eval_set.gold_chunk_ids[x.query_id]) == (x.stratum != "negative"), x.query_id

    def test_every_patient_has_queries_in_each_positive_stratum(self, eval_set):
        for pid in {d.patient_id for d in eval_set.documents}:
            strata = {x.stratum for x in eval_set.queries if x.patient_id == pid}
            assert {"exact_term", "paraphrase", "numeric", "medication", "negative"} <= strata, pid


# ── Runner guards (no DB) ────────────────────────────────────────────────────


class TestRunnerGuards:
    def test_config_validation(self, tmp_path):
        with pytest.raises(EvalDependencyError, match="DATABASE_URL"):
            RunConfig(DEFAULT_DATASET_DIR, tmp_path, "").validate()
        with pytest.raises(EvalDependencyError, match="scheme"):
            RunConfig(DEFAULT_DATASET_DIR, tmp_path, "sqlite:///x.db").validate()
        with pytest.raises(DatasetError, match="dataset_dir"):
            RunConfig(tmp_path / "missing", tmp_path, "postgresql://u@h/medscribe_eval").validate()

    def test_refuses_database_without_eval_in_name(self):
        with pytest.raises(EvalDependencyError, match="must contain 'eval'") as exc:
            preflight_database("postgresql://user:s3cret@db.internal:5432/medscribe")
        assert "s3cret" not in str(exc.value)

    def test_unreachable_database_is_dependency_error(self):
        with pytest.raises(EvalDependencyError, match="unreachable") as exc:
            preflight_database("postgresql://user:s3cret@127.0.0.1:1/medscribe_eval?connect_timeout=1")
        assert "s3cret" not in str(exc.value)


class _FakeHybrid:
    """Mimics HybridRetrievalService's surface; optionally degrades like the real one."""

    dense_threshold = 0.30

    def __init__(self, chunk_ids: List[str], degrade: bool = False):
        self._ids = chunk_ids
        self._degrade = degrade

    def search_chunks_for_patient(self, patient_id, query, top_k=6):
        return [{"chunk_id": c} for c in self._ids[:top_k]]

    def _dense_patient_chunk_search(self, patient_id, query, top_k, threshold):
        if self._degrade:
            logging.getLogger("app.services.hybrid_retrieval").warning(
                "Dense patient chunk search failed: %s", "OperationalError"
            )
            return []
        return [{"chunk_id": c} for c in self._ids[:top_k]]

    def _sparse_patient_chunk_search(self, patient_id, query, top_k):
        return [{"chunk_id": c} for c in self._ids[:top_k]]


class TestRunnerQueryLoop:
    @pytest.fixture()
    def eval_set(self):
        return resolve_eval_set(
            DOCS,
            [
                q("q1", "pa", "medication", [("a_note", "Metformin 500 mg")]),
                q("q2", "pa", "negative", []),
            ],
            chunker=one_chunk_per_paragraph,
        )

    def test_scores_and_reports(self, eval_set):
        outcomes = run_queries(_FakeHybrid(["a_labs#0", "a_note#1", "a_note#0"]), eval_set)
        assert [o.rank_k5 for o in outcomes] == [2, None]
        assert all(o.leaks == 0 for o in outcomes)
        report = build_report(outcomes, eval_set, {"patients": 2, "documents": 3, "chunks": 4}, 200, 1)
        assert report["hybrid"]["overall"]["recall_at_5"]["value"] == 1.0
        assert report["negatives"]["n"] == 1
        assert report["leakage"]["foreign_chunks_returned"] == 0

    def test_foreign_chunk_counts_as_leak(self, eval_set):
        outcomes = run_queries(_FakeHybrid(["b_note#0", "a_note#1"]), eval_set)
        assert outcomes[0].leaks == 1

    def test_degraded_leg_aborts_run(self, eval_set):
        with pytest.raises(RetrieverDegradedError, match="q1"):
            run_queries(_FakeHybrid(["a_note#1"], degrade=True), eval_set)

    def test_build_report_rejects_empty_and_all_negative(self, eval_set):
        neg = QueryOutcome("q2", "pa", "negative", None, None, None, None, 0, 0, 0, 0, 0, 1.0)
        with pytest.raises(RetrievalEvalError, match="no outcomes"):
            build_report([], eval_set, {}, 200, 1)
        with pytest.raises(RetrievalEvalError, match="no positive"):
            build_report([neg], eval_set, {}, 200, 1)
