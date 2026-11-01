"""Tests for container-aware runtime CPU guardrails."""

from __future__ import annotations

import sys
import types

import pytest

from app.core import runtime_resources


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("max 100000", None),
        ("400000 100000", 4),
        ("150000 100000", 2),
        ("0 100000", None),
        ("bad value", None),
    ],
)
def test_parse_v2_cpu_max(value, expected):
    assert runtime_resources._parse_v2_cpu_max(value) == expected


def test_effective_cpu_count_uses_cgroup_v2_and_affinity(monkeypatch):
    monkeypatch.setattr(runtime_resources, "_affinity_cpu_count", lambda: 8)
    monkeypatch.setattr(
        runtime_resources,
        "_read_text",
        lambda path: "350000 100000" if path == runtime_resources._CGROUP_V2_CPU_MAX else None,
    )
    assert runtime_resources.effective_cpu_count() == 4


def test_effective_cpu_count_uses_cgroup_v1_when_v2_is_absent(monkeypatch):
    monkeypatch.setattr(runtime_resources, "_affinity_cpu_count", lambda: 8)

    def read(path):
        values = {
            runtime_resources._CGROUP_V1_CPU_QUOTA: "200000",
            runtime_resources._CGROUP_V1_CPU_PERIOD: "100000",
        }
        return values.get(path)

    monkeypatch.setattr(runtime_resources, "_read_text", read)
    assert runtime_resources.effective_cpu_count() == 2


def test_effective_cpu_count_falls_back_to_affinity(monkeypatch):
    monkeypatch.setattr(runtime_resources, "_affinity_cpu_count", lambda: 3)
    monkeypatch.setattr(runtime_resources, "_read_text", lambda path: None)
    assert runtime_resources.effective_cpu_count() == 3


def test_configure_torch_threads_caps_both_pools(monkeypatch):
    calls = []
    fake_torch = types.SimpleNamespace(
        set_num_threads=lambda count: calls.append(("intra", count)),
        set_num_interop_threads=lambda count: calls.append(("inter", count)),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    assert runtime_resources.configure_torch_threads(3) is True
    assert calls == [("intra", 3), ("inter", 3)]


@pytest.mark.parametrize("value", [0, True, "2"])
def test_configure_torch_threads_rejects_invalid_count(value):
    with pytest.raises(runtime_resources.RuntimeResourceError, match="thread_count"):
        runtime_resources.configure_torch_threads(value)


def test_lower_process_priority_only_lowers_priority(monkeypatch):
    calls = []

    def nice(value):
        calls.append(value)
        return 2 if value == 0 else 5

    monkeypatch.setattr(runtime_resources.os, "nice", nice)
    assert runtime_resources.lower_process_priority(5) is True
    assert calls == [0, 3]


@pytest.mark.parametrize("value", [-1, 20, True, "5"])
def test_lower_process_priority_rejects_invalid_target(value):
    with pytest.raises(runtime_resources.RuntimeResourceError, match="target_nice"):
        runtime_resources.lower_process_priority(value)
