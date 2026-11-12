"""Error types for the retrieval eval (#104).

Every failure the eval can detect has its own type so a caller (CLI, test,
CI) can tell a bad dataset from a missing dependency from a degraded run.
"""

from __future__ import annotations


class RetrievalEvalError(Exception):
    """Base class for all retrieval eval failures."""


class DatasetError(RetrievalEvalError):
    """The corpus or query file is missing, malformed, or inconsistent."""


class GoldResolutionError(DatasetError):
    """A gold quote does not resolve to exactly one document's chunks."""


class MetricInputError(RetrievalEvalError):
    """A scoring function received inputs outside its contract."""


class EvalDependencyError(RetrievalEvalError):
    """A required service (database, pgvector, embedding model) is unusable."""


class RetrieverDegradedError(RetrievalEvalError):
    """The retriever swallowed a failure and returned partial results.

    ``HybridRetrievalService`` catches exceptions in each leg and returns an
    empty list. A run where that happened would publish a number for a
    retriever that was not the one under test, so the run is aborted.
    """
