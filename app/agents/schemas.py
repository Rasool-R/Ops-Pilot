"""Typed schemas enforcing epistemic separation in RCA investigations."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import ServiceId


class HypothesisStatus(StrEnum):
    """Evaluation lifecycle state of an agent hypothesis."""

    PROPOSED = "PROPOSED"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class RiskLevel(StrEnum):
    """Risk classification for remediation proposals."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ObservedFact(BaseModel):
    """Verifiable observation returned directly from a bounded telemetry tool."""

    fact_id: str
    source: str
    service_id: ServiceId
    signal_type: Literal["metric", "log"]
    signal_name: str
    summary: str
    numeric_value: float | None = None
    unit: str | None = None
    observed_at_utc: datetime


class Hypothesis(BaseModel):
    """Candidate explanation linking observed facts, tracked separately from raw facts."""

    hypothesis_id: str
    statement: str
    target_service: ServiceId
    confidence: float = Field(ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_fact_ids: list[str] = Field(default_factory=list)
    contradicting_fact_ids: list[str] = Field(default_factory=list)


class DiagnosticStep(BaseModel):
    """Bounded diagnostic tool execution record planned during investigation."""

    step_id: str
    tool_name: Literal["query_service_metrics", "query_service_logs"]
    target_service: ServiceId
    rationale: str
    executed: bool = False
    succeeded: bool = False
    error_code: str | None = None


class RemediationRecommendation(BaseModel):
    """Predefined remediation proposal citing approved runbook procedures."""

    action_type: Literal["reset_db_connection_pool", "restart_service_container"]
    target_service: ServiceId
    risk_level: RiskLevel
    rationale: str
    requires_human_approval: bool = True
    preconditions: list[str] = Field(default_factory=list)
    cited_runbook_id: str | None = None
    cited_runbook_path: str | None = None


class RCAReport(BaseModel):
    """Final structured Root-Cause Analysis output strictly separating epistemic categories."""

    incident_id: str
    status: Literal["COMPLETED", "INCONCLUSIVE"]
    root_cause_summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    observed_facts: list[ObservedFact] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    diagnostics_executed: list[DiagnosticStep] = Field(default_factory=list)
    recommendations: list[RemediationRecommendation] = Field(default_factory=list)
    unknowns_and_uncertainties: list[str] = Field(default_factory=list)
    bounded_next_diagnostic: str | None = None
    runbook_citations: list[str] = Field(default_factory=list)
    retrieval_gaps: list[str] = Field(default_factory=list)