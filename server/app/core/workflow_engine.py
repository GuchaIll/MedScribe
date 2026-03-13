"""
Workflow Engine Service.

Orchestrates LangGraph workflow execution with:
- Asynchronous execution
- State persistence via checkpointing
- Workflow resumption
- Status tracking
"""

import asyncio
from typing import Dict, Any, Optional, AsyncGenerator
from datetime import datetime
from pathlib import Path

from app.agents.graph import build_graph
from app.agents.config import create_default_context
from app.agents.state import GraphState


class WorkflowEngine:
    """
    Service for executing and managing LangGraph workflows.

    Uses the refactored ``agents/graph.py`` (Anthropic-style dependency
    injection via AgentContext) instead of the legacy ``langgraph_runner``.

    When a ``db_session`` is provided, the pipeline will:
      - Load patient context from the database at the start
      - Store the final structured record and clinical embeddings at the end
    """

    def __init__(
        self,
        enable_checkpointing: bool = True,
        enable_interrupts: bool = True,
        db_session=None,
    ):
        """
        Initialize workflow engine.

        Args:
            enable_checkpointing: Enable persistent state storage
            enable_interrupts: Enable interrupts at human review gates
            db_session: Optional SQLAlchemy Session for full DB integration
        """
        self.enable_checkpointing = enable_checkpointing
        self.enable_interrupts = enable_interrupts

        # Build workflow graph with dependency-injected context
        ctx = create_default_context(db_session=db_session)
        checkpoint_path = str(Path(__file__).parent.parent.parent / "storage" / "checkpoints.db") if enable_checkpointing else None
        self.graph = build_graph(
            ctx=ctx,
            checkpoint_path=checkpoint_path,
            enable_interrupts=enable_interrupts,
        )
        self.checkpointer = enable_checkpointing

    def create_initial_state(
        self,
        session_id: str,
        patient_id: str,
        doctor_id: str,
        **kwargs
    ) -> GraphState:
        """
        Create initial workflow state.

        Args:
            session_id: Unique session identifier
            patient_id: Patient identifier
            doctor_id: Doctor identifier
            **kwargs: Additional state fields

        Returns:
            Initial graph state
        """
        state: GraphState = {
            "session_id": session_id,
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "conversation_log": [],
            "new_segments": [],
            "session_summary": None,
            "patient_record_fields": None,
            "message": None,
            "flags": {},
            "inputs": kwargs.get("inputs", {}),
            "documents": kwargs.get("documents", []),
            "chunks": [],
            "candidate_facts": [],
            "evidence_map": {},
            "structured_record": {},
            "validation_report": None,
            "conflict_report": None,
            "clinical_note": None,
            "controls": {
                "attempts": {},
                "budget": {},
                "trace_log": [],
            },
        }
        return state

    def execute(
        self,
        state: GraphState,
        thread_id: Optional[str] = None
    ) -> GraphState:
        """
        Execute workflow synchronously.

        Args:
            state: Initial or current state
            thread_id: Thread ID for checkpointing (defaults to session_id)

        Returns:
            Final state after execution
        """
        config = self._get_config(thread_id or state["session_id"])

        try:
            final_state = self.graph.invoke(state, config=config)
            return final_state
        except Exception as e:
            # Log error to trace log
            state["controls"]["trace_log"].append({
                "node": "workflow_engine",
                "action": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            state["flags"]["processing_error"] = True
            state["message"] = f"Workflow execution failed: {str(e)}"
            raise

    async def execute_async(
        self,
        state: GraphState,
        thread_id: Optional[str] = None
    ) -> GraphState:
        """
        Execute workflow asynchronously.

        Args:
            state: Initial or current state
            thread_id: Thread ID for checkpointing

        Returns:
            Final state after execution
        """
        config = self._get_config(thread_id or state["session_id"])

        try:
            # Run invoke in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            final_state = await loop.run_in_executor(
                None,
                lambda: self.graph.invoke(state, config=config)
            )
            return final_state
        except Exception as e:
            state["controls"]["trace_log"].append({
                "node": "workflow_engine",
                "action": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            state["flags"]["processing_error"] = True
            state["message"] = f"Workflow execution failed: {str(e)}"
            raise

    async def stream_events(
        self,
        state: GraphState,
        thread_id: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream workflow events as they occur.

        Args:
            state: Initial or current state
            thread_id: Thread ID for checkpointing

        Yields:
            Event dictionaries with node updates
        """
        config = self._get_config(thread_id or state["session_id"])

        try:
            # Stream events from graph
            for event in self.graph.stream(state, config=config):
                # Convert to async generator
                yield {
                    "event": "node_update",
                    "data": event,
                    "timestamp": datetime.now().isoformat()
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": {"error": str(e)},
                "timestamp": datetime.now().isoformat()
            }

    def get_state(self, thread_id: str) -> Optional[GraphState]:
        """
        Get current workflow state from checkpoint.

        Args:
            thread_id: Thread ID to retrieve state for

        Returns:
            Current state or None if not found
        """
        if not self.checkpointer:
            return None

        config = self._get_config(thread_id)

        try:
            # Get state from checkpointer
            checkpoint = self.graph.get_state(config)
            if checkpoint and checkpoint.values:
                return checkpoint.values
            return None
        except Exception as e:
            print(f"[ERROR] Failed to get state: {e}")
            return None

    def update_state(
        self,
        thread_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update workflow state (for human corrections).

        Args:
            thread_id: Thread ID to update
            updates: Dictionary of state updates

        Returns:
            True if successful, False otherwise
        """
        if not self.checkpointer:
            return False

        config = self._get_config(thread_id)

        try:
            # Update state
            self.graph.update_state(config, updates)
            return True
        except Exception as e:
            print(f"[ERROR] Failed to update state: {e}")
            return False

    def resume(
        self,
        thread_id: str,
        updates: Optional[Dict[str, Any]] = None
    ) -> GraphState:
        """
        Resume workflow from checkpoint.

        Args:
            thread_id: Thread ID to resume
            updates: Optional state updates before resuming

        Returns:
            Final state after resumption
        """
        if not self.checkpointer:
            raise RuntimeError("Checkpointing not enabled, cannot resume")

        # Apply updates if provided
        if updates:
            self.update_state(thread_id, updates)

        # Get current state
        current_state = self.get_state(thread_id)
        if not current_state:
            raise ValueError(f"No checkpoint found for thread_id: {thread_id}")

        # Clear review flag to continue
        current_state["flags"]["awaiting_human_review"] = False

        # Resume execution
        config = self._get_config(thread_id)
        final_state = self.graph.invoke(None, config=config)  # None continues from checkpoint

        return final_state

    def get_workflow_status(self, thread_id: str) -> Dict[str, Any]:
        """
        Get workflow execution status.

        Args:
            thread_id: Thread ID to check

        Returns:
            Status dictionary with current state info
        """
        state = self.get_state(thread_id)

        if not state:
            return {
                "thread_id": thread_id,
                "status": "not_found",
                "message": "No workflow found for this thread"
            }

        flags = state.get("flags", {})
        controls = state.get("controls", {})

        # Determine status
        if flags.get("awaiting_human_review"):
            status = "paused_for_review"
        elif flags.get("processing_error"):
            status = "error"
        elif state.get("clinical_note"):
            status = "completed"
        else:
            status = "in_progress"

        return {
            "thread_id": thread_id,
            "status": status,
            "session_id": state.get("session_id"),
            "patient_id": state.get("patient_id"),
            "message": state.get("message"),
            "awaiting_review": flags.get("awaiting_human_review", False),
            "review_reasons": flags.get("review_reasons", []),
            "trace_log_entries": len(controls.get("trace_log", [])),
            "last_updated": datetime.now().isoformat()
        }

    def _get_config(self, thread_id: str) -> Dict[str, Any]:
        """
        Create configuration for workflow execution.

        Args:
            thread_id: Unique thread identifier

        Returns:
            Configuration dictionary
        """
        return {
            "configurable": {
                "thread_id": thread_id
            }
        }


# Singleton instance for global access
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine(
    enable_checkpointing: bool = True,
    enable_interrupts: bool = True,
    db_session=None,
) -> WorkflowEngine:
    """
    Get or create workflow engine singleton.

    Args:
        enable_checkpointing: Enable persistent state storage
        enable_interrupts: Enable interrupts at human review gates
        db_session: Optional SQLAlchemy Session for DB integration

    Returns:
        WorkflowEngine instance
    """
    global _workflow_engine

    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine(
            enable_checkpointing=enable_checkpointing,
            enable_interrupts=enable_interrupts,
            db_session=db_session,
        )

    return _workflow_engine
