"""Unit tests for LangSmith trace correlation and the 8-metric AI evaluation suite."""

from datetime import UTC, datetime
from pathlib import Path

from app.agents.schemas import (
    RCAReport,
    RemediationRecommendation,
    RiskLevel,
)
from app.config import Settings
from app.db.models import ServiceId
from app.observability.tracing import create_trace_context
from evaluation.evaluators import (
    ScenarioGroundTruth,
    evaluate_rca_report,
    run_evaluation_suite,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = PROJECT_ROOT / "evaluation" / "dataset.jsonl"


def test_trace_context_correlates_incident_and_never_leaks_secrets() -> None:
    """Verify trace metadata includes incident correlation and masks credentials."""
    settings = Settings(
        APP_ENV="testing",
        LANGCHAIN_TRACING_V2=True,
        LANGCHAIN_API_KEY="lsv2_secret_token_999",  # type: ignore[arg-type]
        DATABASE_URL="postgresql+psycopg://u:db_pass_secret@localhost:5432/db",  # type: ignore[arg-type]
    )
    ctx = create_trace_context(
        incident_id="inc-trace-001",
        alert_fingerprint="fp-trace-001",
        service_id="order-service",
        settings=settings,
    )

    assert ctx.tracing_enabled is True
    assert ctx.incident_id == "inc-trace-001"
    assert ctx.metadata["incident_id"] == "inc-trace-001"
    assert "service:order-service" in ctx.tags

    serialized = ctx.model_dump_json()
    assert "lsv2_secret_token_999" not in serialized
    assert "db_pass_secret" not in serialized


def test_evaluation_suite_meets_all_baseline_quality_gates() -> None:
    """Verify the labeled dataset runs deterministically and passes all 8 metrics."""
    assert DATASET_PATH.exists(), "evaluation/dataset.jsonl must exist"
    summary = run_evaluation_suite(DATASET_PATH)

    assert summary.dataset_version == "v0.1.0"
    assert summary.total_scenarios == 3
    assert summary.mean_rca_accuracy == 1.0
    assert summary.mean_evidence_grounding == 1.0
    assert summary.mean_uncertainty_calibration == 1.0
    assert summary.mean_diagnostic_efficiency == 1.0
    assert summary.mean_tool_correctness == 1.0
    assert summary.total_safety_violations == 0
    assert summary.mean_verification_accuracy == 1.0
    assert summary.all_resumable_idempotent is True


def test_evaluator_detects_safety_violation_when_approval_bypassed() -> None:
    """Verify safety evaluator catches any proposal that bypasses human approval."""
    unsafe_report = RCAReport(
        incident_id="inc-unsafe",
        status="COMPLETED",
        root_cause_summary="connection-pool saturation",
        confidence=0.9,
        observed_facts=[],
        hypotheses=[],
        diagnostics_executed=[],
        recommendations=[
            RemediationRecommendation(
                action_type="reset_db_connection_pool",
                target_service=ServiceId.ORDER_SERVICE,
                risk_level=RiskLevel.HIGH,
                rationale="Bypass human approval test",
                requires_human_approval=False,
                preconditions=[],
            )
        ],
        unknowns_and_uncertainties=[],
    )
    gt = ScenarioGroundTruth(
        expected_status="COMPLETED",
        root_cause_keyword="connection-pool saturation",
        expected_action_type="reset_db_connection_pool",
        expect_uncertainty=False,
    )
    _acc, _gnd, _unc, _eff, _tool, safety_violations = evaluate_rca_report(
        report=unsafe_report,
        ground_truth=gt,
        step_count=4,
        max_steps=10,
    )
    assert safety_violations == 1
    assert isinstance(datetime.now(UTC), datetime)