"""Incident report retrieval, lifecycle timeline, and safe dashboard links."""

import html
from datetime import datetime
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Incident
from app.db.repository import IncidentRepository


class EvidenceTimelineItem(BaseModel):
    """Single chronological evidence entry for operator timeline inspection."""

    fact_id: str
    source: str
    service_id: str
    signal_type: str
    signal_name: str
    summary: str
    numeric_value: float | None = None
    unit: str | None = None
    observed_at_utc: datetime


class HypothesisItem(BaseModel):
    """Persisted hypothesis item for lifecycle inspection."""

    hypothesis_id: str
    statement: str
    target_service: str
    confidence: float
    status: str
    supporting_fact_ids: list[str] = Field(default_factory=list)
    contradicting_fact_ids: list[str] = Field(default_factory=list)


class ProposalItem(BaseModel):
    """Persisted remediation proposal item."""

    proposal_id: str
    action_type: str
    target_service: str
    risk_level: str
    rationale: str
    requires_human_approval: bool
    preconditions: list[str] = Field(default_factory=list)
    approval_status: str
    created_at_utc: datetime


class ApprovalItem(BaseModel):
    """Persisted human approval decision item."""

    decision_id: str
    proposal_id: str
    approver_id: str
    decision: str
    reason: str
    decided_at_utc: datetime
    expires_at_utc: datetime


class ExecutionVerificationItem(BaseModel):
    """Combined action execution and fresh-telemetry verification record."""

    execution_id: str
    proposal_id: str
    action_type: str
    target_service: str
    dry_run: bool
    execution_status: str
    output_message: str
    rollback_plan: str
    executed_at_utc: datetime
    verification_status: str | None = None
    recovered: bool | None = None
    observed_5xx_rate: float | None = None
    observed_pool_wait_ms: float | None = None
    verification_summary: str | None = None


class AuditTimelineItem(BaseModel):
    """Immutable audit event entry in chronological order."""

    event_id: str
    event_type: str
    actor: str
    details: dict[str, object] = Field(default_factory=dict)
    created_at_utc: datetime


class InfrastructureDashboardLinks(BaseModel):
    """Sanitized infrastructure observability links (reviewed by Developer B)."""

    prometheus_service_5xx_url: str
    prometheus_pool_wait_url: str
    alertmanager_alerts_url: str


class IncidentLifecycleView(BaseModel):
    """Complete end-to-end lifecycle model for the Incident UI and API."""

    incident_id: str
    service_id: str
    alert_fingerprint: str
    title: str
    severity: str
    incident_status: str
    investigation_status: str
    approval_status: str
    remediation_execution_status: str
    recovery_verification_status: str
    created_at_utc: datetime
    updated_at_utc: datetime
    resolved_at_utc: datetime | None = None
    evidence_timeline: list[EvidenceTimelineItem] = Field(default_factory=list)
    hypotheses: list[HypothesisItem] = Field(default_factory=list)
    proposals: list[ProposalItem] = Field(default_factory=list)
    approvals: list[ApprovalItem] = Field(default_factory=list)
    executions: list[ExecutionVerificationItem] = Field(default_factory=list)
    report_payload: dict[str, object] | None = None
    audit_timeline: list[AuditTimelineItem] = Field(default_factory=list)
    dashboard_links: InfrastructureDashboardLinks


def sanitize_dashboard_base_url(raw_url: str) -> str:
    """Strip any embedded user:password credentials from infrastructure URLs."""
    parsed = urlsplit(raw_url.strip())
    host = parsed.hostname or "localhost"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "http"
    return urlunsplit((scheme, netloc, parsed.path.rstrip("/"), "", ""))


def build_infrastructure_links(
    service_id: str,
    settings: Settings | None = None,
) -> InfrastructureDashboardLinks:
    """Construct safe, credential-free Prometheus and Alertmanager links."""
    cfg = settings or get_settings()
    prom_base = sanitize_dashboard_base_url(cfg.PROMETHEUS_BASE_URL)
    am_base = sanitize_dashboard_base_url(cfg.ALERTMANAGER_BASE_URL)

    q_5xx = quote(f'http_requests_5xx_rate{{service="{service_id}"}}', safe="")
    q_pool = quote(f'pg_pool_wait_time_ms{{service="{service_id}"}}', safe="")
    q_am = quote(f'service_id="{service_id}"', safe="")

    return InfrastructureDashboardLinks(
        prometheus_service_5xx_url=f"{prom_base}/graph?g0.expr={q_5xx}&g0.tab=0",
        prometheus_pool_wait_url=f"{prom_base}/graph?g0.expr={q_pool}&g0.tab=0",
        alertmanager_alerts_url=f"{am_base}/#/alerts?filter={q_am}",
    )


class ReportService:
    """Service assembling end-to-end incident lifecycle views and HTML inspection UI."""

    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._repo = IncidentRepository(session)
        self._settings = settings or get_settings()

    def get_lifecycle_view(self, incident_id: str) -> IncidentLifecycleView:
        """Assemble full incident overview, timelines, approvals, and report."""
        inc = self._repo.get_incident_by_id(incident_id)
        if inc is None:
            raise ValueError(f"Incident '{incident_id}' not found")

        evidence_sorted = sorted(
            inc.evidence_records, key=lambda item: item.observed_at_utc
        )
        evidence_timeline = [
            EvidenceTimelineItem(
                fact_id=ev.fact_id,
                source=ev.source,
                service_id=ev.service_id,
                signal_type=ev.signal_type,
                signal_name=ev.signal_name,
                summary=ev.summary,
                numeric_value=ev.numeric_value,
                unit=ev.unit,
                observed_at_utc=ev.observed_at_utc,
            )
            for ev in evidence_sorted
        ]

        hypotheses = [
            HypothesisItem(
                hypothesis_id=h.hypothesis_id,
                statement=h.statement,
                target_service=h.target_service,
                confidence=h.confidence,
                status=h.status,
                supporting_fact_ids=list(h.supporting_fact_ids_json),
                contradicting_fact_ids=list(h.contradicting_fact_ids_json),
            )
            for h in inc.hypotheses
        ]

        proposals = [
            ProposalItem(
                proposal_id=p.id,
                action_type=p.action_type,
                target_service=p.target_service,
                risk_level=p.risk_level,
                rationale=p.rationale,
                requires_human_approval=p.requires_human_approval,
                preconditions=list(p.preconditions_json),
                approval_status=p.approval_status,
                created_at_utc=p.created_at_utc,
            )
            for p in inc.remediation_proposals
        ]

        approvals = [
            ApprovalItem(
                decision_id=d.id,
                proposal_id=d.proposal_id,
                approver_id=d.approver_id,
                decision=d.decision,
                reason=d.reason,
                decided_at_utc=d.decided_at_utc,
                expires_at_utc=d.expires_at_utc,
            )
            for d in sorted(inc.approval_decisions, key=lambda x: x.decided_at_utc)
        ]

        verif_by_exec = {v.execution_id: v for v in inc.verification_results}
        executions: list[ExecutionVerificationItem] = []
        for ex in sorted(inc.action_executions, key=lambda x: x.executed_at_utc):
            verif = verif_by_exec.get(ex.id)
            executions.append(
                ExecutionVerificationItem(
                    execution_id=ex.id,
                    proposal_id=ex.proposal_id,
                    action_type=ex.action_type,
                    target_service=ex.target_service,
                    dry_run=ex.dry_run,
                    execution_status=ex.execution_status,
                    output_message=ex.output_message,
                    rollback_plan=ex.rollback_plan,
                    executed_at_utc=ex.executed_at_utc,
                    verification_status=(
                        verif.verification_status if verif is not None else None
                    ),
                    recovered=verif.recovered if verif is not None else None,
                    observed_5xx_rate=(
                        verif.observed_5xx_rate if verif is not None else None
                    ),
                    observed_pool_wait_ms=(
                        verif.observed_pool_wait_ms if verif is not None else None
                    ),
                    verification_summary=verif.summary if verif is not None else None,
                )
            )

        audit_timeline = [
            AuditTimelineItem(
                event_id=a.id,
                event_type=a.event_type,
                actor=a.actor,
                details=dict(a.details_json),
                created_at_utc=a.created_at_utc,
            )
            for a in sorted(inc.audit_events, key=lambda x: x.created_at_utc)
        ]

        return IncidentLifecycleView(
            incident_id=inc.id,
            service_id=inc.service_id,
            alert_fingerprint=inc.alert_fingerprint,
            title=inc.title,
            severity=inc.severity,
            incident_status=inc.incident_status,
            investigation_status=inc.investigation_status,
            approval_status=inc.approval_status,
            remediation_execution_status=inc.remediation_execution_status,
            recovery_verification_status=inc.recovery_verification_status,
            created_at_utc=inc.created_at_utc,
            updated_at_utc=inc.updated_at_utc,
            resolved_at_utc=inc.resolved_at_utc,
            evidence_timeline=evidence_timeline,
            hypotheses=hypotheses,
            proposals=proposals,
            approvals=approvals,
            executions=executions,
            report_payload=(
                dict(inc.report.report_payload_json) if inc.report is not None else None
            ),
            audit_timeline=audit_timeline,
            dashboard_links=build_infrastructure_links(inc.service_id, self._settings),
        )

    def render_incident_html(self, incident_id: str) -> str:
        """Render an XSS-safe HTML dashboard for inspecting an incident lifecycle."""
        view = self.get_lifecycle_view(incident_id)
        esc_title = html.escape(view.title)
        esc_service = html.escape(view.service_id)
        rca_summary = "Pending or inconclusive"
        if view.report_payload and "root_cause_summary" in view.report_payload:
            rca_summary = html.escape(str(view.report_payload["root_cause_summary"]))

        ev_rows = "".join(
            f"<li><strong>{html.escape(e.fact_id)}</strong> [{html.escape(e.source)}] "
            f"{html.escape(e.summary)}</li>"
            for e in view.evidence_timeline
        )
        prop_rows = "".join(
            f"<li><strong>{html.escape(p.action_type)}</strong> on "
            f"{html.escape(p.target_service)} — Status: "
            f"<em>{html.escape(p.approval_status)}</em></li>"
            for p in view.proposals
        )
        exec_rows = "".join(
            f"<li>Execution <strong>{html.escape(ex.execution_status)}</strong> | "
            f"Verification: <strong>{html.escape(ex.verification_status or 'N/A')}</strong> "
            f"({html.escape(ex.verification_summary or '')})</li>"
            for ex in view.executions
        )

        prom_5xx = html.escape(view.dashboard_links.prometheus_service_5xx_url)
        prom_pool = html.escape(view.dashboard_links.prometheus_pool_wait_url)
        am_url = html.escape(view.dashboard_links.alertmanager_alerts_url)

        return (
            "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
            f"<title>OpsPilot Incident {html.escape(view.incident_id)}</title></head>"
            "<body>"
            f"<h1>Incident Overview: {esc_title}</h1>"
            f"<p>Service: <strong>{esc_service}</strong> | "
            f"Severity: <strong>{html.escape(view.severity)}</strong></p>"
            "<h2>State Machines</h2>"
            "<ul>"
            f"<li>Incident Status: {html.escape(view.incident_status)}</li>"
            f"<li>Investigation Status: {html.escape(view.investigation_status)}</li>"
            f"<li>Approval Status: {html.escape(view.approval_status)}</li>"
            f"<li>Execution Status: {html.escape(view.remediation_execution_status)}</li>"
            f"<li>Verification Status: {html.escape(view.recovery_verification_status)}</li>"
            "</ul>"
            f"<h2>Root-Cause Analysis (RCA)</h2><p>{rca_summary}</p>"
            f"<h2>Evidence Timeline</h2><ul>{ev_rows}</ul>"
            f"<h2>Remediation Proposals & Approvals</h2><ul>{prop_rows}</ul>"
            f"<h2>Execution & Recovery Verification</h2><ul>{exec_rows}</ul>"
            "<h2>Infrastructure Dashboard Links</h2>"
            "<ul>"
            f"<li><a href='{prom_5xx}'>Prometheus HTTP 5xx Graph</a></li>"
            f"<li><a href='{prom_pool}'>Prometheus DB Pool Wait Graph</a></li>"
            f"<li><a href='{am_url}'>Alertmanager Active Alerts</a></li>"
            "</ul>"
            "</body></html>"
        )


def get_incident_report_payload(inc: Incident) -> dict[str, object] | None:
    """Extract persisted RCA report payload dictionary if available."""
    if inc.report is None:
        return None
    return dict(inc.report.report_payload_json)