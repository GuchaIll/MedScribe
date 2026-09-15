"""
Intent gate — Stage A decides whether speech is addressed to the patient or to
MedScribe; Stage B extracts the task subtype and slots. The executor owns the
tool plan; the policy decides whether MedScribe responds.

Phase 0 ships the frozen v1 contract only (types, tables, pure policy). Nothing
in the runtime imports this package yet. See docs/copilot_runtime_contract.md.
"""

from app.agents.intent.executor_contract import (
    AGENT_WALL_CLOCK_BUDGET_MS,
    FIXED_TOOL_CHAINS,
    MAX_AGENT_TOOL_CALLS,
    TASK_EXECUTOR_MODE,
    GroundingReport,
    grounding_verdict,
    validate_agent_step,
)
from app.agents.intent.policy import (
    AMBIENT_CHIP_MIN_CONFIDENCE,
    InterventionOutcome,
    resolve_intervention,
)
from app.agents.intent.schemas import (
    ADDRESSEES,
    CHANNELS,
    RUNTIME_CONTRACT_VERSION,
    TASK_SUBTYPES,
    AddresseeDecision,
    IntentDecision,
    IntentDecisionEvent,
    TaskSlots,
    validate_intent_decision,
)

__all__ = [
    "AGENT_WALL_CLOCK_BUDGET_MS",
    "FIXED_TOOL_CHAINS",
    "MAX_AGENT_TOOL_CALLS",
    "TASK_EXECUTOR_MODE",
    "GroundingReport",
    "grounding_verdict",
    "validate_agent_step",
    "AMBIENT_CHIP_MIN_CONFIDENCE",
    "InterventionOutcome",
    "resolve_intervention",
    "ADDRESSEES",
    "CHANNELS",
    "RUNTIME_CONTRACT_VERSION",
    "TASK_SUBTYPES",
    "AddresseeDecision",
    "IntentDecision",
    "IntentDecisionEvent",
    "TaskSlots",
    "validate_intent_decision",
]
