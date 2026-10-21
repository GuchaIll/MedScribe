"""
Ingest queue configuration.

All timing is in seconds unless the field name says otherwise. Lease expiry
and backoff deadlines are always computed by Postgres (`clock_timestamp()`),
never from the worker's clock; these values are only the intervals.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import IngestConfigError

ENV_PREFIX = "INGEST_"


class IngestQueueConfig(BaseModel):
    """Validated queue settings shared by the worker and the reconciler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Lease length; the worker renews every lease_seconds / 3.
    lease_seconds: int = Field(30, ge=5, le=600)
    # Claim order is rank * aging_step - age: a backfill task overtakes fresh
    # active work once it is aging_step seconds older.
    aging_step_seconds: int = Field(240, gt=0, le=86400)
    # Soft cap on leased page-stage tasks per session; blocking is exempt.
    page_task_cap: int = Field(4, ge=1, le=64)
    # attempts counts claims; at this many, a failure is terminal.
    max_attempts: int = Field(5, ge=1, le=20)
    # Tasks per claim. The worker processes a batch one task at a time and
    # renews only the current task, so batch * task time must stay under the
    # lease; the fence still rejects any task whose lease ran out.
    batch: int = Field(1, ge=1, le=16)
    # Retry delay = min(base * 2^(attempts-1), cap), +/- jitter fraction.
    backoff_base_seconds: float = Field(2.0, gt=0, le=60)
    backoff_cap_seconds: float = Field(60.0, gt=0, le=3600)
    backoff_jitter: float = Field(0.2, ge=0, lt=1)
    # Idle polling: poll_interval, then idle_poll_interval after
    # idle_polls_before_backoff empty polls in a row.
    poll_interval_seconds: float = Field(0.25, gt=0, le=60)
    idle_poll_interval_seconds: float = Field(2.0, gt=0, le=300)
    idle_polls_before_backoff: int = Field(10, ge=1, le=10000)
    # Bound on how long a fenced output transaction can hold the task row lock
    # (Postgres 15 has no transaction_timeout; see #96).
    output_statement_timeout_ms: int = Field(5000, ge=100, le=600000)
    output_idle_in_tx_timeout_ms: int = Field(5000, ge=100, le=600000)

    @model_validator(mode="after")
    def _cross_field(self) -> "IngestQueueConfig":
        if self.backoff_cap_seconds < self.backoff_base_seconds:
            raise ValueError(
                f"backoff_cap_seconds ({self.backoff_cap_seconds}) must be >= "
                f"backoff_base_seconds ({self.backoff_base_seconds})"
            )
        if self.idle_poll_interval_seconds < self.poll_interval_seconds:
            raise ValueError(
                f"idle_poll_interval_seconds ({self.idle_poll_interval_seconds}) must be >= "
                f"poll_interval_seconds ({self.poll_interval_seconds})"
            )
        return self

    @property
    def renew_interval_seconds(self) -> float:
        return self.lease_seconds / 3.0

    @classmethod
    def load(cls, values: Optional[Mapping[str, Any]] = None) -> "IngestQueueConfig":
        """Build a config, converting pydantic errors into IngestConfigError."""
        try:
            return cls(**dict(values or {}))
        except ValidationError as exc:
            err = exc.errors()[0]
            loc = err.get("loc") or ()
            field = str(loc[0]) if loc else "config"
            value = (values or {}).get(field, err.get("input"))
            raise IngestConfigError(field, value, err.get("msg", "a valid value")) from exc

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "IngestQueueConfig":
        """Read INGEST_<FIELD> variables (e.g. INGEST_LEASE_SECONDS)."""
        env = os.environ if environ is None else environ
        values: Dict[str, Any] = {}
        for name in cls.model_fields:
            raw = env.get(ENV_PREFIX + name.upper())
            if raw is not None and raw != "":
                values[name] = raw
        return cls.load(values)


__all__ = ["IngestQueueConfig", "ENV_PREFIX"]
