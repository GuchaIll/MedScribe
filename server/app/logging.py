"""
Centralized logging configuration for the application.

Usage:
    from app.logging import get_logger
    logger = get_logger(__name__)
    logger.info("Application started")
"""

import logging
import logging.config
from pathlib import Path
from typing import Optional


def configure_logging(
    level: str = "INFO",
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_file: Optional[str] = None,
    log_level_file: Optional[str] = None,
) -> None:
    """
    Configure logging for the entire application.

    Args:
        level: Console logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Log message format string
        log_file: Path to log file (optional). If None, only console logging.
        log_level_file: File logging level (can differ from console)
    """
    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "level": level,
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
    }

    # Add file handler if log_file is specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level_file or level,
            "formatter": "standard",
            "filename": str(log_path),
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
        }

    config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": log_format,
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "detailed": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": handlers,
        "root": {
            "level": level,
            "handlers": list(handlers.keys()),
        },
        "loggers": {
            # Reduce noise from third-party libraries
            "urllib3": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "transformers": {"level": "INFO"},
        },
    }

    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        logging.Logger instance
    """
    return logging.getLogger(name)


class PerformanceLogger:
    """Context manager for logging operation performance."""

    def __init__(
        self,
        logger: logging.Logger,
        operation: str,
        threshold_ms: int = 100,
    ):
        """
        Initialize performance logger.

        Args:
            logger: Logger instance
            operation: Name of operation being timed
            threshold_ms: Only log if operation exceeds this duration
        """
        self.logger = logger
        self.operation = operation
        self.threshold_ms = threshold_ms
        self.start_time: Optional[float] = None

    def __enter__(self) -> "PerformanceLogger":
        """Start timing."""
        import time

        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """End timing and log if threshold exceeded."""
        import time

        if self.start_time is None:
            return

        elapsed_ms = (time.time() - self.start_time) * 1000

        if elapsed_ms >= self.threshold_ms:
            self.logger.info(f"{self.operation} took {elapsed_ms:.2f}ms")

        if exc_type is not None:
            self.logger.error(
                f"{self.operation} failed after {elapsed_ms:.2f}ms: {exc_type.__name__}: {exc_val}"
            )


def log_performance(
    logger: logging.Logger,
    operation: str,
    threshold_ms: int = 100,
) -> PerformanceLogger:
    """
    Create a performance logger context manager.

    Usage:
        with log_performance(logger, "Model inference"):
            result = model.predict(data)
    """
    return PerformanceLogger(logger, operation, threshold_ms)
