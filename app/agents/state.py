"""Typed state definition for the stateful LangGraph investigation workflow."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.agents.schemas import (
    DiagnosticStep,
    Hypothesis,
    ObservedFact,
    RCAReport,
    RemediationRecommendation,
)
from app.db.models import InvestigationStatus, ServiceId, Severity


def utc_now() -> datetime:
    """Return current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class InvestigationState(BaseModel):
    """Bounded mutable state passed across investigation graph nodes."""

    incident_id: str
    alert_fingerprint: str
    primary_service: ServiceId
    alert_title: str
    severity: Severity
    incident_start_utc: datetime = Field(default_factory=utc_now)

    # Workflow control and bounded execution counters
    investigation_status: InvestigationStatus = InvestigationStatus.PENDING
    step_count: int = Field(default=0, ge=0)
    max_steps: int = Field(default=10, ge=1, le=25)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0, le=5)
    needs_deeper_diagnostics: bool = False

    # Epistemically separated investigation artifacts
    observed_facts: list[ObservedFact] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    diagnostics_Queue: list[DiagnosticStep] = Field(default_factory=list)
    diagnostics_executed: list[DiagnosticStep] = Field(default_factory=list)
    recommendations: list[RemediationRecommendation] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    bounded_next_diagnostic: str | None = None

    final_report: RCAReport | None = None