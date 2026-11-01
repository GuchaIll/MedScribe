"""CPU and scheduler guardrails for API and offload processes.

Container runtimes commonly expose the host CPU count even when a pod has a
smaller CFS quota.  ML runtimes use that host count by default and can starve
latency-sensitive work.  These helpers derive a conservative process thread
cap from cgroup quota files and apply it before Torch models are initialized.
"""

from __future__ import annotations

import importlib
import logging
import math
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CGROUP_V2_CPU_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_CPU_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_CPU_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


class RuntimeResourceError(ValueError):
    """A runtime resource control received an invalid value."""


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _parse_v2_cpu_max(value: Optional[str]) -> Optional[int]:
    """Return the cgroup-v2 CPU quota as a whole-thread cap, if finite."""
    if not value:
        return None
    parts = value.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        quota, period = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if quota <= 0 or period <= 0:
        return None
    return max(1, math.ceil(quota / period))


def _parse_v1_cpu_max(
    quota_value: Optional[str], period_value: Optional[str]
) -> Optional[int]:
    """Return the cgroup-v1 CPU quota as a whole-thread cap, if finite."""
    if quota_value is None or period_value is None:
        return None
    try:
        quota, period = int(quota_value), int(period_value)
    except ValueError:
        return None
    # A negative v1 quota means no CPU limit.
    if quota <= 0 or period <= 0:
        return None
    return max(1, math.ceil(quota / period))


def _affinity_cpu_count() -> int:
    try:
        affinity = os.sched_getaffinity(0)
        if affinity:
            return len(affinity)
    except (AttributeError, OSError):
        pass
    return max(1, os.cpu_count() or 1)


def effective_cpu_count() -> int:
    """Return the CPU count available to this process, respecting cgroup quota."""
    visible = _affinity_cpu_count()
    cgroup_limit = _parse_v2_cpu_max(_read_text(_CGROUP_V2_CPU_MAX))
    if cgroup_limit is None:
        cgroup_limit = _parse_v1_cpu_max(
            _read_text(_CGROUP_V1_CPU_QUOTA),
            _read_text(_CGROUP_V1_CPU_PERIOD),
        )
    if cgroup_limit is None:
        return visible
    return max(1, min(visible, cgroup_limit))


def configure_torch_threads(thread_count: int) -> bool:
    """Best-effort cap Torch intra-op and inter-op pools before model work.

    Returns ``True`` when Torch was available and both caps were applied.  A
    late inter-op call is rejected by Torch after parallel work starts; that is
    logged and returned as ``False`` rather than silently ignored.
    """
    if (
        isinstance(thread_count, bool)
        or not isinstance(thread_count, int)
        or thread_count < 1
    ):
        raise RuntimeResourceError(
            f"configure_torch_threads: thread_count must be an int >= 1, got {thread_count!r}"
        )
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        logger.info("runtime resources: Torch unavailable; no Torch thread cap applied")
        return False
    try:
        torch.set_num_threads(thread_count)
        torch.set_num_interop_threads(thread_count)
    except RuntimeError as exc:
        logger.warning(
            "runtime resources: failed to cap Torch threads=%d before model work: %s",
            thread_count,
            exc,
        )
        return False
    logger.info("runtime resources: capped Torch intra/inter-op threads=%d", thread_count)
    return True


def lower_process_priority(target_nice: int) -> bool:
    """Best-effort set a process's non-negative Unix niceness target.

    Niceness is advisory and only improves scheduling fairness within a shared
    CPU cgroup.  The function never tries to raise priority.
    """
    if (
        isinstance(target_nice, bool)
        or not isinstance(target_nice, int)
        or not 0 <= target_nice <= 19
    ):
        raise RuntimeResourceError(
            f"lower_process_priority: target_nice must be an int in [0, 19], got {target_nice!r}"
        )
    if not hasattr(os, "nice"):
        logger.warning("runtime resources: os.nice is unavailable; OCR priority unchanged")
        return False
    try:
        current = os.nice(0)
        increment = max(0, target_nice - current)
        if increment:
            os.nice(increment)
        logger.info(
            "runtime resources: process nice=%d (requested=%d)",
            current + increment,
            target_nice,
        )
        return True
    except OSError as exc:
        logger.warning(
            "runtime resources: could not set process nice=%d: %s",
            target_nice,
            exc,
        )
        return False
