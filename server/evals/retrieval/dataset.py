"""Retrieval eval dataset: models, loaders, validation, gold resolution (#104).

Layout of a dataset directory::

    <dataset_dir>/
        corpus/<patient_id>/<doc_id>.txt   one synthetic document per file
        queries.jsonl                      one EvalQuery per line

Gold labels are anchored to source text (``doc_id`` + ``quote``), not to
chunk ids, so the same set stays valid when the chunker changes (#98).
Resolution runs the corpus through the production chunker and maps each
quote to the ids of the chunks that contain it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, FrozenSet, List, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agents.state import ChunkArtifact, DocumentArtifact
from evals.retrieval.errors import DatasetError, GoldResolutionError

logger = logging.getLogger("evals.retrieval")

DATASET_VERSION = "retrieval_v1"

Stratum = Literal["exact_term", "paraphrase", "numeric", "medication", "negative"]
STRATA: tuple[str, ...] = ("exact_term", "paraphrase", "numeric", "medication", "negative")

_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_ID_RE = re.compile(_ID_PATTERN)
MAX_DOCUMENT_CHARS = 200_000
MAX_QUERIES = 10_000

Chunker = Callable[[List[DocumentArtifact]], List[ChunkArtifact]]


# ── Models ───────────────────────────────────────────────────────────────────


class GoldSpan(BaseModel):
    """A passage that answers the query, located by document and quote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=_ID_PATTERN)
    quote: str = Field(min_length=8, max_length=400)


class EvalQuery(BaseModel):
    """One labeled query. Negatives have no gold and are scored separately."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: str = Field(pattern=_ID_PATTERN)
    patient_id: str = Field(pattern=_ID_PATTERN)
    query: str = Field(min_length=3, max_length=500)
    stratum: Stratum
    gold: List[GoldSpan]

    @model_validator(mode="after")
    def _gold_matches_stratum(self) -> "EvalQuery":
        if self.stratum == "negative" and self.gold:
            raise ValueError(
                f"stratum 'negative' must have empty gold, got {len(self.gold)} span(s)"
            )
        if self.stratum != "negative" and not self.gold:
            raise ValueError(f"stratum {self.stratum!r} requires at least one gold span, got none")
        if not self.query.strip():
            raise ValueError("query is whitespace only")
        return self


class CorpusDocument(BaseModel):
    """One synthetic document owned by one patient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: str = Field(pattern=_ID_PATTERN)
    patient_id: str = Field(pattern=_ID_PATTERN)
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)


@dataclass(frozen=True)
class ResolvedEvalSet:
    """Validated dataset plus the chunking run its gold labels resolve against.

    The seeder writes exactly ``chunks``; the scorer tests hits against
    ``gold_chunk_ids``. Both come from one chunking run, so ids agree.
    """

    version: str
    documents: List[CorpusDocument]
    queries: List[EvalQuery]
    chunks: List[ChunkArtifact]
    chunk_patient: Dict[str, str]
    gold_chunk_ids: Dict[str, FrozenSet[str]]


# ── Normalization ────────────────────────────────────────────────────────────


def normalize_text(text: str) -> str:
    """Collapse whitespace and lowercase, for quote containment tests."""
    return " ".join(text.split()).lower()


# ── Loaders ──────────────────────────────────────────────────────────────────


def load_corpus(corpus_dir: Path) -> List[CorpusDocument]:
    """Load ``corpus/<patient_id>/<doc_id>.txt`` files.

    Raises:
        DatasetError: directory missing or empty, bad id, non-text file,
            empty or oversized document, or duplicate ``doc_id``.
    """
    if not isinstance(corpus_dir, Path):
        raise DatasetError(f"corpus_dir must be a pathlib.Path, got {type(corpus_dir).__name__}")
    if not corpus_dir.is_dir():
        raise DatasetError(f"corpus directory not found: {corpus_dir}")

    documents: List[CorpusDocument] = []
    seen: Dict[str, Path] = {}
    errors: List[str] = []

    for patient_dir in sorted(p for p in corpus_dir.iterdir() if not p.name.startswith(".")):
        if not patient_dir.is_dir():
            errors.append(f"{patient_dir}: expected a patient directory, found a file")
            continue
        if not _ID_RE.match(patient_dir.name):
            errors.append(f"{patient_dir}: patient_id {patient_dir.name!r} does not match {_ID_PATTERN}")
            continue
        for path in sorted(p for p in patient_dir.iterdir() if not p.name.startswith(".")):
            if path.suffix != ".txt" or not path.is_file():
                errors.append(f"{path}: expected a .txt document")
                continue
            doc_id = path.stem
            if doc_id in seen:
                errors.append(f"{path}: duplicate doc_id {doc_id!r}, also at {seen[doc_id]}")
                continue
            seen[doc_id] = path
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                errors.append(f"{path}: document is empty")
                continue
            try:
                documents.append(
                    CorpusDocument(doc_id=doc_id, patient_id=patient_dir.name, text=text)
                )
            except ValidationError as exc:
                errors.append(f"{path}: {_first_error(exc)}")

    if errors:
        raise DatasetError("corpus invalid:\n  " + "\n  ".join(errors))
    if not documents:
        raise DatasetError(f"corpus directory has no documents: {corpus_dir}")
    return documents


def load_queries(queries_path: Path) -> List[EvalQuery]:
    """Load ``queries.jsonl``. Blank lines are skipped; every other line must parse.

    Raises:
        DatasetError: file missing or empty, bad JSON, schema violation,
            duplicate ``query_id``, or more than ``MAX_QUERIES`` rows.
    """
    if not isinstance(queries_path, Path):
        raise DatasetError(f"queries_path must be a pathlib.Path, got {type(queries_path).__name__}")
    if not queries_path.is_file():
        raise DatasetError(f"queries file not found: {queries_path}")

    queries: List[EvalQuery] = []
    seen: Dict[str, int] = {}
    errors: List[str] = []

    with queries_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{queries_path.name}:{lineno}: invalid JSON ({exc.msg})")
                continue
            try:
                query = EvalQuery.model_validate(raw)
            except ValidationError as exc:
                errors.append(f"{queries_path.name}:{lineno}: {_first_error(exc)}")
                continue
            if query.query_id in seen:
                errors.append(
                    f"{queries_path.name}:{lineno}: duplicate query_id {query.query_id!r}, "
                    f"first at line {seen[query.query_id]}"
                )
                continue
            seen[query.query_id] = lineno
            queries.append(query)

    if errors:
        raise DatasetError("queries invalid:\n  " + "\n  ".join(errors))
    if not queries:
        raise DatasetError(f"queries file has no rows: {queries_path}")
    if len(queries) > MAX_QUERIES:
        raise DatasetError(f"queries file has {len(queries)} rows, limit is {MAX_QUERIES}")
    return queries


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
    return f"field {loc!r}: {err.get('msg')} (received {err.get('input')!r:.80})"


# ── Cross-reference validation and gold resolution ───────────────────────────


def _default_chunker() -> Chunker:
    from app.agents.nodes.segment import chunk_documents

    return chunk_documents


def resolve_eval_set(
    documents: Sequence[CorpusDocument],
    queries: Sequence[EvalQuery],
    chunker: Chunker | None = None,
) -> ResolvedEvalSet:
    """Validate cross references and resolve every gold quote to chunk ids.

    Rules:
      - every query's patient owns at least one document
      - every gold ``doc_id`` exists and belongs to the query's patient
      - the quote appears in that document (normalized)
      - the quote does not appear in any other document of the same patient
      - the quote is contained in at least one chunk of that document

    Raises:
        DatasetError: unknown patient or document, cross-patient gold.
        GoldResolutionError: quote missing, ambiguous, or split across chunks.
    """
    if not documents:
        raise DatasetError("documents is empty")
    if not queries:
        raise DatasetError("queries is empty")
    chunker = chunker or _default_chunker()

    docs_by_id: Dict[str, CorpusDocument] = {d.doc_id: d for d in documents}
    if len(docs_by_id) != len(documents):
        raise DatasetError("documents contain a duplicate doc_id")
    docs_by_patient: Dict[str, List[CorpusDocument]] = {}
    for doc in documents:
        docs_by_patient.setdefault(doc.patient_id, []).append(doc)

    artifacts: List[DocumentArtifact] = [
        {
            "document_id": d.doc_id,
            "source_type": "text",
            "extracted_text": d.text,
            "tables": [],
            "metadata": {},
        }
        for d in documents
    ]
    chunks = chunker(artifacts)
    if not chunks:
        raise GoldResolutionError("chunker returned no chunks for a non-empty corpus")

    chunk_patient: Dict[str, str] = {}
    chunks_by_doc: Dict[str, List[ChunkArtifact]] = {}
    for chunk in chunks:
        doc_id = chunk["source_id"]
        if doc_id not in docs_by_id:
            raise GoldResolutionError(f"chunker returned chunk for unknown doc_id {doc_id!r}")
        if chunk["chunk_id"] in chunk_patient:
            raise GoldResolutionError(f"chunker returned duplicate chunk_id {chunk['chunk_id']!r}")
        chunk_patient[chunk["chunk_id"]] = docs_by_id[doc_id].patient_id
        chunks_by_doc.setdefault(doc_id, []).append(chunk)

    norm_doc = {d.doc_id: normalize_text(d.text) for d in documents}
    ref_errors: List[str] = []
    gold_errors: List[str] = []
    gold_chunk_ids: Dict[str, FrozenSet[str]] = {}

    for q in queries:
        if q.patient_id not in docs_by_patient:
            ref_errors.append(f"{q.query_id}: patient_id {q.patient_id!r} has no documents")
            continue
        ids: set[str] = set()
        for span in q.gold:
            doc = docs_by_id.get(span.doc_id)
            if doc is None:
                ref_errors.append(f"{q.query_id}: gold doc_id {span.doc_id!r} not in corpus")
                continue
            if doc.patient_id != q.patient_id:
                ref_errors.append(
                    f"{q.query_id}: gold doc_id {span.doc_id!r} belongs to {doc.patient_id!r}, "
                    f"query patient is {q.patient_id!r}"
                )
                continue
            nq = normalize_text(span.quote)
            if nq not in norm_doc[span.doc_id]:
                gold_errors.append(f"{q.query_id}: quote not found in {span.doc_id!r}: {span.quote!r:.60}")
                continue
            others = [
                o.doc_id
                for o in docs_by_patient[q.patient_id]
                if o.doc_id != span.doc_id and nq in norm_doc[o.doc_id]
            ]
            if others:
                gold_errors.append(
                    f"{q.query_id}: quote is ambiguous, also in {others}: {span.quote!r:.60}"
                )
                continue
            hits = [
                c["chunk_id"]
                for c in chunks_by_doc.get(span.doc_id, [])
                if nq in normalize_text(c["text"])
            ]
            if not hits:
                gold_errors.append(
                    f"{q.query_id}: quote straddles a chunk boundary in {span.doc_id!r}: {span.quote!r:.60}"
                )
                continue
            ids.update(hits)
        gold_chunk_ids[q.query_id] = frozenset(ids)

    if ref_errors:
        raise DatasetError("query references invalid:\n  " + "\n  ".join(ref_errors))
    if gold_errors:
        raise GoldResolutionError("gold resolution failed:\n  " + "\n  ".join(gold_errors))

    logger.info(
        "eval set resolved: version=%s patients=%d documents=%d chunks=%d queries=%d",
        DATASET_VERSION, len(docs_by_patient), len(documents), len(chunks), len(queries),
    )
    return ResolvedEvalSet(
        version=DATASET_VERSION,
        documents=list(documents),
        queries=list(queries),
        chunks=list(chunks),
        chunk_patient=chunk_patient,
        gold_chunk_ids=gold_chunk_ids,
    )


def load_eval_set(dataset_dir: Path, chunker: Chunker | None = None) -> ResolvedEvalSet:
    """Load, validate, and resolve a dataset directory."""
    if not isinstance(dataset_dir, Path):
        raise DatasetError(f"dataset_dir must be a pathlib.Path, got {type(dataset_dir).__name__}")
    documents = load_corpus(dataset_dir / "corpus")
    queries = load_queries(dataset_dir / "queries.jsonl")
    return resolve_eval_set(documents, queries, chunker=chunker)
