"""Conditional routing logic and loop-bound enforcement for the investigation graph."""

from typing import Literal

from app.agents.state import InvestigationState


def route_after_hypotheses(
    state: InvestigationState,
) -> Literal["execute_diagnostics", "produce_rca_report"]:
    """Decide whether to run planned diagnostics or jump straight to report generation."""
    if state.step_count >= state.max_steps or state.retry_count > state.max_retries:
        return "produce_rca_report"

    if state.needs_deeper_diagnostics and state.diagnostics_Queue:
        return "execute_diagnostics"

    return "produce_rca_report"


def route_after_reassessment(
    state: InvestigationState,
) -> Literal["execute_diagnostics", "produce_rca_report"]:
    """Route to report generation or additional bounded diagnostics if within step limits."""
    if state.step_count >= state.max_steps or state.retry_count > state.max_retries:
        return "produce_rca_report"

    if state.needs_deeper_diagnostics and state.diagnostics_Queue:
        return "execute_diagnostics"

    return "produce_rca_report"