"""
L1 deterministic tests — PHI scanner.

PHI rule (§19.2 rule 3): a scanner test must fail the build if a fixture
patient name, MRN, or lab value appears in production-mode trace output.

This test suite:
1. Defines a minimal PHI scanner that searches span dicts for known fixtures.
2. ASSERTS THAT THE SCANNER RAISES on planted PHI — i.e., the test proves
   the scanner is capable of catching leaks.
3. Asserts clean spans pass without raising.

When TRACE_CAPTURE_PAYLOADS=true spans may contain payloads (dev/eval only);
the scanner exempts that env var by design — these tests run without it.

In CI: pytest server/evals/deterministic/test_phi_scanner.py
Expected: all tests pass (including the ones that prove the scanner fires).
"""

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.agents.trace_contracts import make_span
from app.agents.tracing.sinks import JsonlTraceSink
from app.agents.tracing.spans import new_span_id, new_trace_id, utcnow_iso

# ---------------------------------------------------------------------------
# Planted PHI fixtures — do NOT use real patient data here
# ---------------------------------------------------------------------------

PLANTED_NAME = "Jane Doe"
PLANTED_MRN = "MRN-12345"
PLANTED_LAB = "Hemoglobin 8.2 g/dL"

_PHI_PATTERNS: List[re.Pattern] = [
    re.compile(re.escape(PLANTED_NAME), re.IGNORECASE),
    re.compile(re.escape(PLANTED_MRN), re.IGNORECASE),
    re.compile(re.escape(PLANTED_LAB), re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# PHI scanner
# ---------------------------------------------------------------------------


class PhiLeakError(AssertionError):
    pass


def scan_span_for_phi(span: Dict[str, Any]) -> List[str]:
    """
    Return a list of PHI matches found anywhere in the span dict.

    Serialises to JSON so nested structures are covered.
    """
    text = json.dumps(span)
    matches = []
    for pattern in _PHI_PATTERNS:
        found = pattern.findall(text)
        if found:
            matches.append(f"pattern {pattern.pattern!r} matched {len(found)} time(s)")
    return matches


def assert_no_phi(span: Dict[str, Any]) -> None:
    matches = scan_span_for_phi(span)
    if matches:
        raise PhiLeakError(
            f"PHI detected in production-mode span:\n" + "\n".join(f"  {m}" for m in matches)
        )


def scan_jsonl_file_for_phi(path: Path) -> List[str]:
    all_matches: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        span = json.loads(line)
        all_matches.extend(scan_span_for_phi(span))
    return all_matches


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_span(**attrs_override) -> Dict[str, Any]:
    return make_span(
        trace_id=new_trace_id(),
        span_id=new_span_id(),
        kind="route",
        name="dispatch_assist",
        session_id="sess-phi-test",
        started_at=utcnow_iso(),
        duration_ms=5.0,
        status="ok",
        attributes={"dispatch": "workflow", "reason_codes": [], **attrs_override},
    )


# ---------------------------------------------------------------------------
# Tests that prove the scanner fires on planted data
# (these tests PASS because they assert the scanner RAISES)
# ---------------------------------------------------------------------------


def test_scanner_detects_planted_name_in_attributes():
    span = _clean_span(debug_note=PLANTED_NAME)
    matches = scan_span_for_phi(span)
    assert matches, (
        f"Scanner did not detect planted name {PLANTED_NAME!r} — "
        "the scanner is broken or the fixture was not embedded correctly"
    )


def test_scanner_detects_planted_mrn_in_attributes():
    span = _clean_span(debug_note=PLANTED_MRN)
    matches = scan_span_for_phi(span)
    assert matches, (
        f"Scanner did not detect planted MRN {PLANTED_MRN!r}"
    )


def test_scanner_detects_planted_lab_in_attributes():
    span = _clean_span(debug_note=PLANTED_LAB)
    matches = scan_span_for_phi(span)
    assert matches, (
        f"Scanner did not detect planted lab value {PLANTED_LAB!r}"
    )


def test_assert_no_phi_raises_on_planted_name():
    span = _clean_span(utterance_text=PLANTED_NAME)
    with pytest.raises(PhiLeakError, match="PHI detected"):
        assert_no_phi(span)


def test_assert_no_phi_raises_on_planted_mrn():
    span = _clean_span(patient_id_raw=PLANTED_MRN)
    with pytest.raises(PhiLeakError, match="PHI detected"):
        assert_no_phi(span)


def test_assert_no_phi_raises_on_planted_lab():
    span = _clean_span(completion_text=PLANTED_LAB)
    with pytest.raises(PhiLeakError, match="PHI detected"):
        assert_no_phi(span)


def test_scanner_detects_phi_in_jsonl_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "traces.jsonl"
        sink = JsonlTraceSink(path)
        sink.emit(_clean_span(leaked_value=PLANTED_MRN))
        sink.close()

        matches = scan_jsonl_file_for_phi(path)
        assert matches, (
            f"Scanner did not detect PHI in JSONL file — "
            "the scanner is broken or the fixture was not written correctly"
        )


# ---------------------------------------------------------------------------
# Tests that prove clean spans pass
# ---------------------------------------------------------------------------


def test_clean_span_passes_phi_check():
    span = _clean_span()
    assert_no_phi(span)


def test_clean_span_with_ids_passes_phi_check():
    span = _clean_span(
        trace_id="abc123",
        tool_id="retrieve_labs_v1",
        args_hash="deadbeef1234",
        source_refs=["chunk-001", "lab-row-42"],
    )
    assert_no_phi(span)


def test_clean_jsonl_file_passes_phi_scan():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "traces.jsonl"
        sink = JsonlTraceSink(path)
        sink.emit(_clean_span())
        sink.emit(_clean_span(kind="tool_call"))
        sink.close()

        matches = scan_jsonl_file_for_phi(path)
        assert matches == [], f"False positive PHI matches: {matches}"


def test_phi_scanner_not_active_when_capture_payloads_set(monkeypatch):
    """
    When TRACE_CAPTURE_PAYLOADS=true (dev/eval runs on synthetic data),
    payload capture is allowed.  The scanner is still able to find matches —
    this test documents that the env var does NOT suppress the scanner itself;
    only the runtime decides not to call assert_no_phi in that mode.
    """
    monkeypatch.setenv("TRACE_CAPTURE_PAYLOADS", "true")
    span = _clean_span(synthetic_utterance=PLANTED_NAME)
    matches = scan_span_for_phi(span)
    assert matches, "Scanner must still find PHI even when capture payloads env is set"
