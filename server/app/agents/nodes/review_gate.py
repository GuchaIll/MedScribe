from ..state import GraphState, ValidationReport, ConflictReport
from datetime import datetime
from typing import List


def check_validation_issues(validation_report: ValidationReport) -> tuple[bool, List[str]]:
    """
    Check validation report for issues requiring human review.

    Args:
        validation_report: Validation report from validation node

    Returns:
        Tuple of (needs_review, list of reasons)
    """
    reasons = []

    # Check for schema errors
    if validation_report.get('schema_errors'):
        schema_errors = validation_report['schema_errors']
        if schema_errors:
            reasons.append(f"Schema validation errors: {len(schema_errors)} errors found")

    # Check for missing critical fields
    if validation_report.get('missing_fields'):
        missing_fields = validation_report['missing_fields']
        if missing_fields:
            reasons.append(f"Missing required fields: {', '.join(missing_fields[:5])}")

    # Check for low confidence
    confidence = validation_report.get('confidence')
    if confidence is not None and confidence < 0.7:
        reasons.append(f"Low confidence score: {confidence:.2f}")

    # Check explicit needs_review flag
    if validation_report.get('needs_review'):
        reasons.append("Validation report explicitly flagged for review")

    return len(reasons) > 0, reasons


def check_conflict_issues(conflict_report: ConflictReport) -> tuple[bool, List[str]]:
    """
    Check conflict report for unresolved conflicts.

    Args:
        conflict_report: Conflict report from conflict resolution node

    Returns:
        Tuple of (needs_review, list of reasons)
    """
    reasons = []

    # Check for unresolved conflicts
    if conflict_report.get('unresolved'):
        reasons.append("Unresolved conflicts detected")

    # Check for conflicts list
    conflicts = conflict_report.get('conflicts', [])
    if conflicts:
        reasons.append(f"Found {len(conflicts)} conflicts: {', '.join(conflicts[:3])}")

    return len(reasons) > 0, reasons


def check_state_flags(flags: dict) -> tuple[bool, List[str]]:
    """
    Check state flags for review requirements.

    Args:
        flags: State flags dictionary

    Returns:
        Tuple of (needs_review, list of reasons)
    """
    reasons = []

    # Check explicit needs_review flag
    if flags.get('needs_review'):
        reasons.append("State explicitly flagged for review")

    # Check for errors in processing
    if flags.get('processing_error'):
        reasons.append("Processing error encountered")

    # Check for low quality indicators
    if flags.get('low_quality'):
        reasons.append("Low quality data detected")

    return len(reasons) > 0, reasons


def human_review_gate_node(state: GraphState) -> GraphState:
    """
    Determine if human review is needed and set appropriate flags.

    Checks:
    - validation_report for schema errors, missing fields, low confidence
    - conflict_report for unresolved conflicts
    - state flags for explicit needs_review flag

    If review is needed, sets 'awaiting_human_review' flag to True,
    which will cause LangGraph to interrupt at this node.

    Args:
        state: Current graph state

    Returns:
        Updated state with review flags set
    """
    validation_report = state.get('validation_report')
    conflict_report = state.get('conflict_report')
    flags = state.get('flags', {})

    needs_review = False
    review_reasons = []

    # Check validation report
    if validation_report:
        validation_needs_review, validation_reasons = check_validation_issues(validation_report)
        if validation_needs_review:
            needs_review = True
            review_reasons.extend(validation_reasons)

    # Check conflict report
    if conflict_report:
        conflict_needs_review, conflict_reasons = check_conflict_issues(conflict_report)
        if conflict_needs_review:
            needs_review = True
            review_reasons.extend(conflict_reasons)

    # Check state flags
    flag_needs_review, flag_reasons = check_state_flags(flags)
    if flag_needs_review:
        needs_review = True
        review_reasons.extend(flag_reasons)

    # Update state flags
    if needs_review:
        state['flags']['awaiting_human_review'] = True
        state['flags']['review_reasons'] = review_reasons

        # Log for tracing
        state['controls']['trace_log'].append({
            'node': 'human_review_gate',
            'action': 'paused_for_review',
            'reasons': review_reasons,
            'timestamp': datetime.now().isoformat()
        })

        # Add message for user
        state['message'] = (
            f"Workflow paused for human review. "
            f"Reasons: {'; '.join(review_reasons)}"
        )
    else:
        # No review needed, clear any previous flags
        state['flags']['awaiting_human_review'] = False

        # Log for tracing
        state['controls']['trace_log'].append({
            'node': 'human_review_gate',
            'action': 'approved_automatically',
            'timestamp': datetime.now().isoformat()
        })

    return state
