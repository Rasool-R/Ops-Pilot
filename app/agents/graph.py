"""Stateful investigation graph orchestrating the end-to-end RCA workflow."""

from app.agents.nodes import (
    collect_initial_evidence_node,
    formulate_hypotheses_node,
    normalize_incident_node,
    plan_and_execute_diagnostics_node,
    produce_rca_report_node,
    reassess_evidence_node,
)
from app.agents.routing import route_after_hypotheses, route_after_reassessment
from app.agents.state import InvestigationState
from app.integrations.telemetry import MockTelemetryAdapter, TelemetryAdapter


class InvestigationGraph:
    """Compiled stateful workflow executing bounded RCA investigations."""

    def __init__(self, adapter: TelemetryAdapter | None = None) -> None:
        self._adapter: TelemetryAdapter = adapter or MockTelemetryAdapter(fault_injected=True)

    def invoke(self, initial_state: InvestigationState) -> InvestigationState:
        """Execute the investigation state machine from normalization to final RCA report."""
        state = normalize_incident_node(initial_state)

        if state.step_count >= state.max_steps:
            return produce_rca_report_node(state)

        state = collect_initial_evidence_node(state, self._adapter)
        state = formulate_hypotheses_node(state)

        next_node = route_after_hypotheses(state)
        while next_node == "execute_diagnostics":
            state = plan_and_execute_diagnostics_node(state, self._adapter)
            state = reassess_evidence_node(state)
            next_node = route_after_reassessment(state)

        state = produce_rca_report_node(state)
        return state