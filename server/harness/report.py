"""
Baseline report writer (SDD §2.3.3).

A suite produces rows of (scenario, metric, value, unit, note). This writes
them as `<out_dir>/<date>-baseline.md` plus the same data as JSON, so a later
PR that moves a baseline can diff the JSON and say why.
"""

from __future__ import annotations

import json
import math
import platform
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ReportError(ValueError):
    """A report row or output location is invalid."""


@dataclass(frozen=True)
class Row:
    scenario: str
    metric: str
    value: float
    unit: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.scenario or not self.metric:
            raise ReportError(f"row needs scenario and metric, got scenario={self.scenario!r} metric={self.metric!r}")
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool) or math.isnan(self.value):
            raise ReportError(f"row {self.scenario}/{self.metric} value must be a number, got {self.value!r}")


@dataclass
class Report:
    suite: str
    rows: List[Row]
    params: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    environment: Dict[str, str] = field(
        default_factory=lambda: {"python": platform.python_version(), "machine": platform.machine(), "os": platform.system()}
    )


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.3g}"


def render_markdown(report: Report, *, title: Optional[str] = None) -> str:
    lines = [f"# {title or report.suite} baseline", ""]
    lines.append(f"Generated {report.started_at} by `python -m harness.runner {report.suite}`.")
    lines.append("")
    env = ", ".join(f"{k} {v}" for k, v in sorted(report.environment.items()))
    lines.append(f"Environment: {env}.")
    if report.params:
        lines.append("")
        lines.append("Parameters: " + ", ".join(f"`{k}={v}`" for k, v in sorted(report.params.items())) + ".")
    by_scenario: Dict[str, List[Row]] = {}
    for r in report.rows:
        by_scenario.setdefault(r.scenario, []).append(r)
    for scenario, rows in by_scenario.items():
        lines += ["", f"## {scenario}", "", "| Metric | Value | Unit | Note |", "| --- | ---: | --- | --- |"]
        lines += [f"| {r.metric} | {_fmt(r.value)} | {r.unit} | {r.note} |" for r in rows]
    lines.append("")
    return "\n".join(lines)


def write_baseline(report: Report, out_dir: Path, *, title: Optional[str] = None, day: Optional[date] = None) -> Tuple[Path, Path]:
    if not report.rows:
        raise ReportError(f"suite {report.suite!r} produced no rows; refusing to write an empty baseline")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{(day or date.today()).isoformat()}-baseline"
    md = out_dir / f"{stem}.md"
    js = out_dir / f"{stem}.json"
    md.write_text(render_markdown(report, title=title), encoding="utf-8")
    js.write_text(
        json.dumps({**asdict(report), "rows": [asdict(r) for r in report.rows]}, indent=2) + "\n", encoding="utf-8"
    )
    return md, js


__all__ = ["Row", "Report", "ReportError", "render_markdown", "write_baseline"]
