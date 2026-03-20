"""
Performance monitoring and latency tracking.

Provides utilities for:
- Timing operations
- Tracking latencies
- Performance metrics collection
- Alerting on slow operations
"""

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from functools import wraps
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class OperationMetrics:
    """Metrics for a tracked operation."""

    name: str
    total_calls: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    errors: int = 0
    last_error: Optional[str] = None

    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration."""
        if self.total_calls == 0:
            return 0.0
        return self.total_duration_ms / self.total_calls

    def __str__(self) -> str:
        """Pretty print metrics."""
        return (
            f"{self.name}: "
            f"calls={self.total_calls}, "
            f"avg={self.avg_duration_ms:.2f}ms, "
            f"min={self.min_duration_ms:.2f}ms, "
            f"max={self.max_duration_ms:.2f}ms, "
            f"errors={self.errors}"
        )


class PerformanceMonitor:
    """Monitor and track operation performance."""

    def __init__(self, threshold_ms: int = 100):
        """
        Initialize performance monitor.

        Args:
            threshold_ms: Only log operations slower than this (milliseconds)
        """
        self.threshold_ms = threshold_ms
        self.metrics: dict[str, OperationMetrics] = defaultdict(
            lambda: OperationMetrics(name="")
        )

    def track_operation(
        self,
        operation_name: str,
        threshold_ms: Optional[int] = None,
    ) -> "OperationTimer":
        """
        Create a context manager to track an operation.

        Args:
            operation_name: Name of operation being tracked
            threshold_ms: Override class threshold for this operation

        Returns:
            OperationTimer context manager

        Usage:
            monitor = PerformanceMonitor()
            with monitor.track_operation("model_inference") as timer:
                result = model.predict(data)
                print(f"Took {timer.elapsed_ms:.2f}ms")
        """
        threshold = threshold_ms or self.threshold_ms
        return OperationTimer(
            monitor=self,
            operation_name=operation_name,
            threshold_ms=threshold,
        )

    def record_operation(
        self,
        operation_name: str,
        duration_ms: float,
        error: Optional[Exception] = None,
    ) -> None:
        """
        Manually record an operation.

        Args:
            operation_name: Name of operation
            duration_ms: Duration in milliseconds
            error: Optional exception that occurred
        """
        if operation_name not in self.metrics:
            self.metrics[operation_name] = OperationMetrics(name=operation_name)

        metrics = self.metrics[operation_name]
        metrics.total_calls += 1
        metrics.total_duration_ms += duration_ms
        metrics.min_duration_ms = min(metrics.min_duration_ms, duration_ms)
        metrics.max_duration_ms = max(metrics.max_duration_ms, duration_ms)

        if error:
            metrics.errors += 1
            metrics.last_error = str(error)

        if duration_ms >= self.threshold_ms:
            logger.warning(f"{operation_name} took {duration_ms:.2f}ms (threshold: {self.threshold_ms}ms)")

    def get_metrics(self, operation_name: str) -> Optional[OperationMetrics]:
        """Get metrics for a specific operation."""
        return self.metrics.get(operation_name)

    def get_all_metrics(self) -> dict[str, OperationMetrics]:
        """Get all collected metrics."""
        return dict(self.metrics)

    def reset(self, operation_name: Optional[str] = None) -> None:
        """
        Reset metrics.

        Args:
            operation_name: If specified, only reset this operation. Otherwise reset all.
        """
        if operation_name:
            if operation_name in self.metrics:
                del self.metrics[operation_name]
        else:
            self.metrics.clear()

    def print_summary(self) -> None:
        """Print summary of all metrics."""
        logger.info("=== Performance Metrics Summary ===")
        for metrics in self.metrics.values():
            logger.info(str(metrics))
        logger.info("===================================")


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(
        self,
        monitor: PerformanceMonitor,
        operation_name: str,
        threshold_ms: int = 100,
    ):
        """Initialize timer."""
        self.monitor = monitor
        self.operation_name = operation_name
        self.threshold_ms = threshold_ms
        self.start_time: Optional[float] = None
        self.elapsed_ms: float = 0.0
        self.error: Optional[Exception] = None

    def __enter__(self) -> "OperationTimer":
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and record."""
        if self.start_time is None:
            return

        self.elapsed_ms = (time.time() - self.start_time) * 1000

        if exc_type is not None:
            self.error = exc_val

        self.monitor.record_operation(
            self.operation_name,
            self.elapsed_ms,
            self.error,
        )


# Global performance monitor instance
_monitor: Optional[PerformanceMonitor] = None


def get_performance_monitor(threshold_ms: int = 100) -> PerformanceMonitor:
    """Get or create global performance monitor."""
    global _monitor
    if _monitor is None:
        _monitor = PerformanceMonitor(threshold_ms=threshold_ms)
    return _monitor


def reset_performance_monitor() -> None:
    """Reset global performance monitor."""
    global _monitor
    _monitor = None


@contextmanager
def track_performance(
    operation_name: str,
    threshold_ms: int = 100,
):
    """
    Context manager for tracking operation performance.

    Usage:
        with track_performance("model_inference", threshold_ms=100):
            result = model.predict(data)
    """
    monitor = get_performance_monitor(threshold_ms=threshold_ms)
    with monitor.track_operation(operation_name, threshold_ms=threshold_ms):
        yield


def performance_tracked(
    threshold_ms: int = 100,
) -> Callable:
    """
    Decorator to track function performance.

    Usage:
        @performance_tracked(threshold_ms=500)
        async def slow_operation():
            # ...
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            monitor = get_performance_monitor(threshold_ms=threshold_ms)
            with monitor.track_operation(func.__name__, threshold_ms=threshold_ms):
                return func(*args, **kwargs)

        async def async_wrapper(*args, **kwargs) -> Any:
            monitor = get_performance_monitor(threshold_ms=threshold_ms)
            with monitor.track_operation(func.__name__, threshold_ms=threshold_ms):
                return await func(*args, **kwargs)

        # Return appropriate wrapper
        if hasattr(func, "__await__"):
            return async_wrapper
        else:
            return sync_wrapper

        return sync_wrapper if not hasattr(func, "__code__") else sync_wrapper

    return decorator
