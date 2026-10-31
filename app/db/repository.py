"""Application data-access repository with idempotent persistence."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.state import InvestigationState
from app.db.models import (
    Alert,
    ApprovalStatus,
    AuditEvent,
    DiagnosticRun,
    EvidenceRecord,
    HypothesisRecord,
    Incident,
    IncidentReport,
    IncidentStatus,
    InvestigationStatus,
    RecoveryVerificationStatus,
    RemediationExecutionStatus,
    RemediationProposal,
    ServiceId,
    Severity,
)


class NormalizedAlertInput(BaseModel):
    """Validated, bounded input schema for alert ingestion."""

    idempotency_key: str = Field(min_length=4, max_length=128)
    alert_fingerprint: str = Field(min_length=4, max_length=128)
    service_id: ServiceId
    title: str = Field(min_length=3, max_length=255)
    severity: Severity
    starts_at_utc: datetime
    ends_at_utc: datetime | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class IncidentRepository:
    """Transactional repository managing Incident, Alert, and RCA persistence."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ingest_alert(self, alert_in: NormalizedAlertInput) -> tuple[Incident, Alert, bool]:
        """Ingest a normalized alert idempotently and correlate it with an active incident."""
        existing_alert = self._session.scalar(
            select(Alert).where(Alert.idempotency_key == alert_in.idempotency_key)
        )
        if existing_alert is not None:
            return existing_alert.incident, existing_alert, False

        active_statuses = (
            IncidentStatus.OPEN.value,
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.MITIGATING.value,
        )
        incident = self._session.scalar(
            select(Incident)
            .where(
                Incident.service_id == alert_in.service_id.value,
                Incident.alert_fingerprint == alert_in.alert_fingerprint,
                Incident.incident_status.in_(active_statuses),
            )
            .order_by(Incident.created_at_utc.desc())
        )

        created_new_incident = False
        if incident is None:
            created_new_incident = True
            incident = Incident(
                service_id=alert_in.service_id.value,
                alert_fingerprint=alert_in.alert_fingerprint,
                title=alert_in.title,
                severity=alert_in.severity.value,
                incident_status=IncidentStatus.OPEN.value,
                investigation_status=InvestigationStatus.PENDING.value,
                approval_status=ApprovalStatus.NOT_REQUIRED.value,
                remediation_execution_status=RemediationExecutionStatus.NOT_STARTED.value,
                recovery_verification_status=RecoveryVerificationStatus.PENDING.value,
            )
            self._session.add(incident)
            self._session.flush()

            self._session.add(
                AuditEvent(
                    incident_id=incident.id,
                    event_type="incident.created",
                    actor="system.alert_ingestor",
                    details_json={
                        "service_id": incident.service_id,
                        "alert_fingerprint": incident.alert_fingerprint,
                        "severity": incident.severity,
                    },
                )
            )
        else:
            incident.updated_at_utc = datetime.now(UTC)

        alert = Alert(
            incident_id=incident.id,
            idempotency_key=alert_in.idempotency_key,
            alert_fingerprint=alert_in.alert_fingerprint,
            service_id=alert_in.service_id.value,
            severity=alert_in.severity.value,
            starts_at_utc=alert_in.starts_at_utc,
            ends_at_utc=alert_in.ends_at_utc,
            labels_json=dict(alert_in.labels),
            annotations_json=dict(alert_in.annotations),
        )
        self._session.add(alert)
        self._session.flush()

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type="alert.ingested",
                actor="system.alert_ingestor",
                details_json={
                    "alert_id": alert.id,
                    "idempotency_key": alert.idempotency_key,
                    "created_new_incident": created_new_incident,
                },
            )
        )

        self._session.commit()
        self._session.refresh(incident)
        self._session.refresh(alert)
        return incident, alert, created_new_incident

    def record_resolved_alert(
        self,
        alert_in: NormalizedAlertInput,
    ) -> tuple[Incident | None, bool]:
        """Correlate an Alertmanager resolved notification with an active incident."""
        active_statuses = (
            IncidentStatus.OPEN.value,
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.MITIGATING.value,
        )
        incident = self._session.scalar(
            select(Incident)
            .where(
                Incident.service_id == alert_in.service_id.value,
                Incident.alert_fingerprint == alert_in.alert_fingerprint,
                Incident.incident_status.in_(active_statuses),
            )
            .order_by(Incident.created_at_utc.desc())
        )
        if incident is None:
            return None, False

        now = datetime.now(UTC)
        resolved_time = alert_in.ends_at_utc or now
        for existing_alert in incident.alerts:
            if existing_alert.ends_at_utc is None:
                existing_alert.ends_at_utc = resolved_time

        incident.updated_at_utc = now
        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type="alert.resolved_notification",
                actor="system.alert_ingestor",
                details_json={
                    "alert_fingerprint": alert_in.alert_fingerprint,
                    "ends_at_utc": resolved_time.isoformat(),
                },
            )
        )
        self._session.commit()
        self._session.refresh(incident)
        return incident, True

    def save_investigation_outcome(
        self,
        incident_id: str,
        final_state: InvestigationState,
    ) -> Incident:
        """Persist evidence, hypotheses, diagnostics, proposals, and report idempotently."""
        incident = self.get_incident_by_id(incident_id)
        if incident is None:
            raise ValueError(f"Incident '{incident_id}' not found")

        # 1. Upsert Evidence Records idempotently
        for fact in final_state.observed_facts:
            existing_ev = self._session.scalar(
                select(EvidenceRecord).where(
                    EvidenceRecord.incident_id == incident.id,
                    EvidenceRecord.fact_id == fact.fact_id,
                )
            )
            if existing_ev is None:
                self._session.add(
                    EvidenceRecord(
                        incident_id=incident.id,
                        fact_id=fact.fact_id,
                        source=fact.source,
                        service_id=fact.service_id.value,
                        signal_type=fact.signal_type,
                        signal_name=fact.signal_name,
                        summary=fact.summary,
                        numeric_value=fact.numeric_value,
                        unit=fact.unit,
                        observed_at_utc=fact.observed_at_utc,
                    )
                )

        # 2. Upsert Hypotheses idempotently
        for hyp in final_state.hypotheses:
            existing_hyp = self._session.scalar(
                select(HypothesisRecord).where(
                    HypothesisRecord.incident_id == incident.id,
                    HypothesisRecord.hypothesis_id == hyp.hypothesis_id,
                )
            )
            if existing_hyp is None:
                self._session.add(
                    HypothesisRecord(
                        incident_id=incident.id,
                        hypothesis_id=hyp.hypothesis_id,
                        statement=hyp.statement,
                        target_service=hyp.target_service.value,
                        confidence=hyp.confidence,
                        status=hyp.status.value,
                        supporting_fact_ids_json=list(hyp.supporting_fact_ids),
                        contradicting_fact_ids_json=list(hyp.contradicting_fact_ids),
                    )
                )
            else:
                existing_hyp.confidence = hyp.confidence
                existing_hyp.status = hyp.status.value
                existing_hyp.supporting_fact_ids_json = list(hyp.supporting_fact_ids)
                existing_hyp.contradicting_fact_ids_json = list(hyp.contradicting_fact_ids)

        # 3. Upsert Diagnostic Runs idempotently
        for step in final_state.diagnostics_executed:
            existing_diag = self._session.scalar(
                select(DiagnosticRun).where(
                    DiagnosticRun.incident_id == incident.id,
                    DiagnosticRun.step_id == step.step_id,
                )
            )
            if existing_diag is None:
                self._session.add(
                    DiagnosticRun(
                        incident_id=incident.id,
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        target_service=step.target_service.value,
                        rationale=step.rationale,
                        executed=step.executed,
                        succeeded=step.succeeded,
                        error_code=step.error_code,
                    )
                )
            else:
                existing_diag.executed = step.executed
                existing_diag.succeeded = step.succeeded
                existing_diag.error_code = step.error_code

        # 4. Upsert Remediation Proposals idempotently (never duplicate on retry/resume)
        for rec in final_state.recommendations:
            idem_key = f"prop-{incident.id}-{rec.action_type}-{rec.target_service.value}"
            existing_prop = self._session.scalar(
                select(RemediationProposal).where(
                    RemediationProposal.idempotency_key == idem_key
                )
            )
            if existing_prop is None:
                self._session.add(
                    RemediationProposal(
                        incident_id=incident.id,
                        idempotency_key=idem_key,
                        action_type=rec.action_type,
                        target_service=rec.target_service.value,
                        risk_level=rec.risk_level.value,
                        rationale=rec.rationale,
                        requires_human_approval=rec.requires_human_approval,
                        preconditions_json=list(rec.preconditions),
                        approval_status=(
                            ApprovalStatus.PENDING_APPROVAL.value
                            if rec.requires_human_approval
                            else ApprovalStatus.NOT_REQUIRED.value
                        ),
                    )
                )

        # 5. Upsert Final RCA Report
        if final_state.final_report is not None:
            rep = final_state.final_report
            existing_rep = self._session.scalar(
                select(IncidentReport).where(IncidentReport.incident_id == incident.id)
            )
            payload_dict = rep.model_dump(mode="json")
            if existing_rep is None:
                self._session.add(
                    IncidentReport(
                        incident_id=incident.id,
                        status=rep.status,
                        root_cause_summary=rep.root_cause_summary,
                        confidence=rep.confidence,
                        unknowns_json=list(rep.unknowns_and_uncertainties),
                        bounded_next_diagnostic=rep.bounded_next_diagnostic,
                        report_payload_json=payload_dict,
                    )
                )
            else:
                existing_rep.status = rep.status
                existing_rep.root_cause_summary = rep.root_cause_summary
                existing_rep.confidence = rep.confidence
                existing_rep.unknowns_json = list(rep.unknowns_and_uncertainties)
                existing_rep.bounded_next_diagnostic = rep.bounded_next_diagnostic
                existing_rep.report_payload_json = payload_dict

        # 6. Update distinct state machines on Incident
        incident.investigation_status = final_state.investigation_status.value
        incident.incident_status = IncidentStatus.INVESTIGATING.value
        if final_state.recommendations:
            incident.approval_status = ApprovalStatus.PENDING_APPROVAL.value
        incident.updated_at_utc = datetime.now(UTC)

        self._session.add(
            AuditEvent(
                incident_id=incident.id,
                event_type=f"investigation.{final_state.investigation_status.value.lower()}",
                actor="agent.investigation_graph",
                details_json={
                    "step_count": final_state.step_count,
                    "evidence_count": len(final_state.observed_facts),
                    "recommendations_count": len(final_state.recommendations),
                },
            )
        )

        self._session.commit()
        self._session.refresh(incident)
        return incident

    def get_incident_by_id(self, incident_id: str) -> Incident | None:
        """Retrieve a single incident by its UUID string."""
        return self._session.scalar(select(Incident).where(Incident.id == incident_id))

    def list_incidents(self, limit: int = 20, offset: int = 0) -> list[Incident]:
        """List incidents ordered by newest first with bounded pagination."""
        bounded_limit = max(1, min(limit, 100))
        bounded_offset = max(0, offset)
        stmt = (
            select(Incident)
            .order_by(Incident.created_at_utc.desc())
            .limit(bounded_limit)
            .offset(bounded_offset)
        )
        return list(self._session.scalars(stmt).all())