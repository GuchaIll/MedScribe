"""Module-level job functions for test_offload.py (spawn children import them by name)."""

import multiprocessing
import os
import time


def busy(seconds: float) -> str:
    """Hold the CPU (and, when run inline, the GIL) for ``seconds``."""
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end:
        n += 1
    return "busy-done"


def sleep_then_return(seconds: float) -> str:
    time.sleep(seconds)
    return "slept"


def raise_in_child(_job) -> None:
    raise RuntimeError("boom from child")


def exit_in_child(_job) -> str:
    """Kill the worker when run in a child; return normally in a thread."""
    if multiprocessing.parent_process() is not None:
        os._exit(1)
    return "thread-ok"


def which_process(_job) -> int:
    return os.getpid()
