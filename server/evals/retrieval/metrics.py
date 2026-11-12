"""Pure scoring for the retrieval eval (#104). No I/O, no DB, no model.

Rank convention: a query's ``rank`` is the 1-based position of the first
retrieved chunk that is a gold hit, or ``None`` when no gold chunk was
returned in that list.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence

from evals.retrieval.errors import MetricInputError

DEFAULT_BOOTSTRAP_RESAMPLES = 2000
DEFAULT_BOOTSTRAP_SEED = 104


def first_hit_rank(retrieved_ids: Sequence[str], gold_ids: FrozenSet[str]) -> Optional[int]:
    """Return the 1-based rank of the first gold id in ``retrieved_ids``, or None."""
    if not isinstance(gold_ids, frozenset):
        raise MetricInputError(f"gold_ids must be a frozenset, got {type(gold_ids).__name__}")
    if not gold_ids:
        raise MetricInputError("gold_ids is empty; negative queries are not rank-scored")
    for i, cid in enumerate(retrieved_ids, start=1):
        if cid in gold_ids:
            return i
    return None


def _check_ranks(ranks: Sequence[Optional[int]], name: str) -> None:
    for r in ranks:
        if r is not None and (not isinstance(r, int) or isinstance(r, bool) or r < 1):
            raise MetricInputError(f"{name} contains invalid rank {r!r}; expected int >= 1 or None")


def hit_at_k(rank: Optional[int], k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def reciprocal(rank: Optional[int]) -> float:
    return 0.0 if rank is None else 1.0 / rank


@dataclass(frozen=True)
class Estimate:
    """A mean with a percentile-bootstrap 95% interval."""

    value: float
    ci_low: float
    ci_high: float

    def as_dict(self) -> Dict[str, float]:
        return {"value": round(self.value, 4), "ci95": [round(self.ci_low, 4), round(self.ci_high, 4)]}


def bootstrap_mean(
    values: Sequence[float],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> Estimate:
    """Mean of ``values`` with a percentile-bootstrap 95% CI (fixed seed, reproducible)."""
    if not values:
        raise MetricInputError("bootstrap_mean got an empty sequence")
    if not isinstance(resamples, int) or resamples < 100:
        raise MetricInputError(f"resamples must be an int >= 100, got {resamples!r}")
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return Estimate(mean, mean, mean)
    rng = random.Random(seed)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[min(resamples - 1, int(0.975 * resamples))]
    return Estimate(mean, lo, hi)


def rank_metrics(
    ranks_k5: Sequence[Optional[int]],
    ranks_k10: Sequence[Optional[int]],
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> Dict[str, object]:
    """Recall@1, Recall@5 (from the k=5 list), Recall@10 and MRR@10 (from the k=10 list).

    The two lists are separate because the hybrid retriever's RRF output is
    not prefix-stable across ``top_k``: top 5 of a k=10 call is not what a
    k=5 caller receives.
    """
    if len(ranks_k5) != len(ranks_k10):
        raise MetricInputError(
            f"ranks_k5 has {len(ranks_k5)} items, ranks_k10 has {len(ranks_k10)}; expected equal"
        )
    if not ranks_k5:
        raise MetricInputError("rank_metrics got no queries")
    _check_ranks(ranks_k5, "ranks_k5")
    _check_ranks(ranks_k10, "ranks_k10")
    for r in ranks_k5:
        if r is not None and r > 5:
            raise MetricInputError(f"ranks_k5 contains rank {r} > 5")
    for r in ranks_k10:
        if r is not None and r > 10:
            raise MetricInputError(f"ranks_k10 contains rank {r} > 10")

    def est(fn: Callable[[Optional[int]], float], ranks: Sequence[Optional[int]]) -> Dict[str, float]:
        return bootstrap_mean([fn(r) for r in ranks], resamples, seed).as_dict()

    return {
        "n": len(ranks_k5),
        "recall_at_1": est(lambda r: hit_at_k(r, 1), ranks_k5),
        "recall_at_5": est(lambda r: hit_at_k(r, 5), ranks_k5),
        "recall_at_10": est(lambda r: hit_at_k(r, 10), ranks_k10),
        "mrr_at_10": est(reciprocal, ranks_k10),
    }


def random_recall_at_k(pool_size: int, gold_count: int, k: int) -> float:
    """Expected Recall@k if k chunks were drawn uniformly at random from the patient's pool.

    The reference point for a small per-patient pool: with 11 chunks and one
    gold chunk, a random draw of 5 already hits 45% of the time.
    """
    for name, v in (("pool_size", pool_size), ("gold_count", gold_count), ("k", k)):
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise MetricInputError(f"{name} must be an int >= 1, got {v!r}")
    if gold_count > pool_size:
        raise MetricInputError(f"gold_count {gold_count} exceeds pool_size {pool_size}")
    draw = min(k, pool_size)
    return 1.0 - math.comb(pool_size - gold_count, draw) / math.comb(pool_size, draw)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile. ``pct`` in (0, 100]."""
    if not values:
        raise MetricInputError("percentile got an empty sequence")
    if not 0 < pct <= 100:
        raise MetricInputError(f"pct must be in (0, 100], got {pct!r}")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def count_leaks(
    retrieved_ids: Sequence[str],
    query_patient: str,
    chunk_patient: Dict[str, str],
) -> int:
    """Chunks returned for ``query_patient`` that belong to someone else, or to no seeded doc."""
    return sum(1 for cid in retrieved_ids if chunk_patient.get(cid) != query_patient)


def group_by(items: Sequence[object], key: Callable[[object], str]) -> Dict[str, List[object]]:
    out: Dict[str, List[object]] = {}
    for item in items:
        out.setdefault(key(item), []).append(item)
    return out
