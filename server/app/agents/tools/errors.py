"""
Tool runtime error types (agent refactor Phase 1A, #51).

One base class so call sites can catch every registry refusal, plus specific
subclasses so a caller can tell a programming mistake (unknown tool) from a
model trap (scope key in args) from a contract breach (invalid ToolResult).

Contract semantics: docs/copilot_runtime_contract.md §6.
"""

from __future__ import annotations

from typing import List, Optional


class ToolRuntimeError(Exception):
    """Base class for every refusal raised by the tool registry."""

    def __init__(self, message: str, *, tool_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.tool_id = tool_id


class UnknownToolError(ToolRuntimeError):
    """Tool id is not in the contract 1.2 catalogue, or is not registered."""


class ToolPermissionError(ToolRuntimeError):
    """This caller may not call this tool (allowlist, assist flag, Lane B stage)."""

    def __init__(self, message: str, *, tool_id: str, caller: str, caller_ref: str) -> None:
        super().__init__(message, tool_id=tool_id)
        self.caller = caller
        self.caller_ref = caller_ref


class ToolArgumentError(ToolRuntimeError):
    """Args failed contract validation — scope keys, wrong shape, unknown tool."""

    def __init__(self, message: str, *, tool_id: str, violations: List[str]) -> None:
        super().__init__(message, tool_id=tool_id)
        self.violations = violations


class ToolScopeError(ToolRuntimeError):
    """The runtime scope lacks an identifier this tool needs (e.g. patient_id)."""

    def __init__(self, message: str, *, tool_id: str, missing: List[str]) -> None:
        super().__init__(message, tool_id=tool_id)
        self.missing = missing


class ToolResultContractError(ToolRuntimeError):
    """A handler returned something that is not a valid ToolResult."""

    def __init__(self, message: str, *, tool_id: str, violations: List[str]) -> None:
        super().__init__(message, tool_id=tool_id)
        self.violations = violations


__all__ = [
    "ToolRuntimeError",
    "UnknownToolError",
    "ToolPermissionError",
    "ToolArgumentError",
    "ToolScopeError",
    "ToolResultContractError",
]
