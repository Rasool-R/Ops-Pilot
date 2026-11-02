"""Incident lifecycle service orchestrating ingestion, investigation, and safe resume."""

from sqlalchemy.orm import Session

from app.agents.graph import InvestigationGraph
from app.agents.state import InvestigationState
from app.db.models import Incident, InvestigationStatus, ServiceId, Severity
from app.db.repository import IncidentRepository, NormalizedAlertInput
from app.integrations.telemetry import MockTelemetryAdapter, TelemetryAdapter


class IncidentService:
    """Application service coordinating incident persistence and LangGraph investigation."""

    def __init__(
        self,
        session: Session,
        telemetry_adapter: TelemetryAdapter | None = None,
    ) -> None:
        self._repo = IncidentRepository(session)
        self._adapter = telemetry_adapter or MockTelemetryAdapter(fault_injected=True)

    def ingest_and_investigate(
        self,
        alert_in: NormalizedAlertInput,
        auto_investigate: bool = True,
    ) -> tuple[Incident, bool]:
        """Ingest a normalized alert idempotently and optionally run RCA investigation."""
        incident, _alert, created_new = self._repo.ingest_alert(alert_in)
        if auto_investigate and incident.investigation_status != (
            InvestigationStatus.COMPLETED.value
        ):
            incident = self.run_or_resume_investigation(incident.id)
        return incident, created_new

    def run_or_resume_investigation(
        self,
        incident_id: str,
        force_rerun: bool = False,
    ) -> Incident:
        """Execute or safely resume an interrupted RCA investigation for an incident."""
        incident = self._repo.get_incident_by_id(incident_id)
        if incident is None:
            raise ValueError(f"Incident '{incident_id}' does not exist")

        # Safe resume check: if already COMPLETED and not forced, return durable record
        if (
            incident.investigation_status == InvestigationStatus.COMPLETED.value
            and incident.report is not None
            and not force_rerun
        ):
            return incident

        initial_state = InvestigationState(
            incident_id=incident.id,
            alert_fingerprint=incident.alert_fingerprint,
            primary_service=ServiceId(incident.service_id),
            alert_title=incident.title,
            severity=Severity(incident.severity),
        )

        graph = InvestigationGraph(adapter=self._adapter)
        final_state = graph.invoke(initial_state)
        return self._repo.save_investigation_outcome(incident.id, final_state)