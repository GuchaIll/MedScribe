"""
Stub tools backed by canned ToolResult fixtures (agent refactor Phase 1A, #51).

Plan §11 Phase 1A item 3: the retrieval store changes in Phase 1B, so real
backends wait. Every contract 1.2 tool id is registered here with a stub that
returns a contract-valid body from ``server/tests/fixtures/tool_results/``.
Receipts flag these calls with ``stub: true`` on the span and the trace log,
so no eval or dashboard mistakes canned data for a real backend.

Real backends replace stubs one tool at a time via ``registry.register(...,
replace=True)``.

Cases per tool: ok, empty, no_source, in_flight_doc, chart_vs_session_conflict
(and not_covered for the safety tools). A tool that has no fixture for the
requested case falls back to ``ok``, logged at debug.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..tool_contracts import TOOL_IDS
from .registry import ToolCall, ToolOutcome, ToolRegistry

logger = logging.getLogger(__name__)

# server/tests/fixtures/tool_results — fixtures live with the tests because
# they are test data, not runtime configuration.
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "tool_results"

DEFAULT_CASE = "ok"
STUB_VERSION = "stub-1.2.0"

# Every case a fixture may define. Tools define the ones that make sense for
# them; the loader falls back to ok for the rest.
STUB_CASES = (
    "ok",
    "empty",
    "no_source",
    "in_flight_doc",
    "chart_vs_session_conflict",
    "not_covered",
)


class StubFixtureError(RuntimeError):
    """A fixture file is missing or malformed."""


@lru_cache(maxsize=None)
def _load_fixture(tool_id: str, fixture_dir: str) -> Dict[str, Any]:
    path = Path(fixture_dir) / f"{tool_id}.json"
    if not path.exists():
        raise StubFixtureError(
            f"no stub fixture for {tool_id!r}: expected {path}. "
            f"Every contract tool id needs one."
        )
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise StubFixtureError(f"stub fixture {path} is not valid JSON: {exc}") from exc
    cases = payload.get("cases")
    if not isinstance(cases, dict) or DEFAULT_CASE not in cases:
        raise StubFixtureError(
            f"stub fixture {path} must define a 'cases' object containing {DEFAULT_CASE!r}"
        )
    unknown = set(cases) - set(STUB_CASES)
    if unknown:
        raise StubFixtureError(f"stub fixture {path} defines unknown cases: {sorted(unknown)}")
    return payload


def load_case(tool_id: str, case: str, *, fixture_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return the canned body for one tool and case, falling back to ok."""
    if case not in STUB_CASES:
        raise ValueError(f"unknown stub case {case!r}; expected one of {list(STUB_CASES)}")
    payload = _load_fixture(tool_id, str(fixture_dir or FIXTURE_DIR))
    cases = payload["cases"]
    body = cases.get(case)
    if body is None:
        logger.debug(
            "stub fixture for %s has no %r case; using %r", tool_id, case, DEFAULT_CASE
        )
        body = cases[DEFAULT_CASE]
    return body


class StubToolSet:
    """Holds the case each stubbed tool should return.

    Tests set a case per tool (or for all of them) so one registry can serve a
    happy path and a failure path without re-registering handlers.
    """

    def __init__(
        self,
        *,
        case: str = DEFAULT_CASE,
        cases: Optional[Dict[str, str]] = None,
        fixture_dir: Optional[Path] = None,
    ) -> None:
        if case not in STUB_CASES:
            raise ValueError(f"unknown stub case {case!r}; expected one of {list(STUB_CASES)}")
        self.default_case = case
        self.cases: Dict[str, str] = dict(cases or {})
        self.fixture_dir = fixture_dir
        self.calls: List[Dict[str, Any]] = []

    def set_case(self, tool_id: str, case: str) -> None:
        if tool_id not in TOOL_IDS:
            raise ValueError(f"{tool_id!r} is not a contract tool id")
        if case not in STUB_CASES:
            raise ValueError(f"unknown stub case {case!r}; expected one of {list(STUB_CASES)}")
        self.cases[tool_id] = case

    def case_for(self, tool_id: str) -> str:
        return self.cases.get(tool_id, self.default_case)

    def handler(self, call: ToolCall) -> ToolOutcome:
        """Return the canned outcome for this tool's current case."""
        case = self.case_for(call.tool_id)
        body = load_case(call.tool_id, case, fixture_dir=self.fixture_dir)
        self.calls.append({
            "tool_id": call.tool_id,
            "case": case,
            "caller": call.caller,
            "caller_ref": call.caller_ref,
            "arg_keys": sorted(call.args),
        })
        return ToolOutcome(
            ok=bool(body["ok"]),
            data=dict(body.get("data") or {}),
            citations=[dict(citation) for citation in body.get("citations") or []],
            error=body.get("error"),
            cache_hit=bool((body.get("data") or {}).get("cache_hit", False)),
        )


def register_stub_tools(
    registry: ToolRegistry,
    *,
    case: str = DEFAULT_CASE,
    cases: Optional[Dict[str, str]] = None,
    only: Optional[List[str]] = None,
    skip: Optional[List[str]] = None,
    fixture_dir: Optional[Path] = None,
    replace: bool = False,
) -> StubToolSet:
    """Register a fixture-backed stub for every contract tool id.

    ``skip`` leaves tools that already have a real backend alone (for example
    ``get_patient_profile``, which runs off the session snapshot).
    """
    stubs = StubToolSet(case=case, cases=cases, fixture_dir=fixture_dir)
    wanted = list(only or TOOL_IDS)
    skipped = set(skip or ())
    for tool_id in wanted:
        if tool_id in skipped:
            continue
        if tool_id not in TOOL_IDS:
            raise ValueError(f"{tool_id!r} is not a contract tool id")
        registry.register(
            tool_id,
            stubs.handler,
            version=STUB_VERSION,
            stub=True,
            replace=replace,
        )
    logger.info(
        "registered %d stub tools (default case=%s, skipped=%d)",
        len(wanted) - len(skipped & set(wanted)), case, len(skipped & set(wanted)),
    )
    return stubs


__all__ = [
    "DEFAULT_CASE",
    "FIXTURE_DIR",
    "STUB_CASES",
    "STUB_VERSION",
    "StubFixtureError",
    "StubToolSet",
    "load_case",
    "register_stub_tools",
]
