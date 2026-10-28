"""Tests for the stateful investigation graph, evidence grounding, and failure handling."""

from app.agents.graph import InvestigationGraph
from app.agents.schemas import HypothesisStatus
from app.agents.state import InvestigationState
from app.db.models import InvestigationStatus, ServiceId, Severity
from app.integrations.telemetry import MockTelemetryAdapter


def _build_initial_state(max_steps: int = 10) -> InvestigationState:
    """Create a baseline initial investigation state for an order-service 5xx alert."""
    return InvestigationState(
        incident_id="inc-test-001",
        alert_fingerprint="fp-order-5xx",
        primary_service=ServiceId.ORDER_SERVICE,
        alert_title="Elevated HTTP 5xx error rate on order-service",
        severity=Severity.CRITICAL,
        max_steps=max_steps,
    )


def test_investigation_graph_diagnoses_db_pool_exhaustion_with_grounded_evidence() -> None:
    """Verify synthetic alert yields grounded RCA and refutes payment-service."""
    adapter = MockTelemetryAdapter(fault_injected=True, simulate_failure=False)
    graph = InvestigationGraph(adapter=adapter)

    final_state = graph.invoke(_build_initial_state())

    assert final_state.investigation_status == InvestigationStatus.COMPLETED
    assert final_state.final_report is not None
    report = final_state.final_report

    assert report.status == "COMPLETED"
    assert "connection-pool saturation" in report.root_cause_summary
    assert report.confidence >= 0.90
    assert len(report.observed_facts) >= 5
    assert len(report.diagnostics_executed) == 3

    hyp_map = {h.hypothesis_id: h for h in report.hypotheses}
    assert hyp_map["hyp-db-pool-exhaustion"].status == HypothesisStatus.SUPPORTED
    assert len(hyp_map["hyp-db-pool-exhaustion"].supporting_fact_ids) >= 2
    assert hyp_map["hyp-payment-service-degradation"].status == HypothesisStatus.REFUTED

    assert len(report.recommendations) == 1
    rec = report.recommendations[0]
    assert rec.action_type == "reset_db_connection_pool"
    assert rec.requires_human_approval is True


def test_investigation_graph_reports_uncertainty_when_telemetry_fails() -> None:
    """Verify tool failures produce an INCONCLUSIVE report with unknowns and next diagnostic."""
    failing_adapter = MockTelemetryAdapter(fault_injected=True, simulate_failure=True)
    graph = InvestigationGraph(adapter=failing_adapter)

    final_state = graph.invoke(_build_initial_state())

    assert final_state.investigation_status == InvestigationStatus.INCONCLUSIVE
    assert final_state.final_report is not None
    report = final_state.final_report

    assert report.status == "INCONCLUSIVE"
    assert report.recommendations == []
    assert len(report.unknowns_and_uncertainties) >= 2
    assert report.bounded_next_diagnostic is not None
    assert "order-service" in report.bounded_next_diagnostic


def test_investigation_graph_respects_max_steps_bound() -> None:
    """Verify the graph terminates safely when max_steps is reached early."""
    adapter = MockTelemetryAdapter(fault_injected=True)
    graph = InvestigationGraph(adapter=adapter)

    constrained_state = _build_initial_state(max_steps=1)
    final_state = graph.invoke(constrained_state)

    assert final_state.step_count <= 2
    assert final_state.final_report is not None
    assert final_state.final_report.status == "INCONCLUSIVE"