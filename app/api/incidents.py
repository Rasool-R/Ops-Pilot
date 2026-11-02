"""FastAPI endpoints for incident ingestion, paginated history, RCA report, and UI."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Incident
from app.db.repository import IncidentRepository, NormalizedAlertInput
from app.db.session import get_db
from app.services.incident_service import IncidentService
from app.services.report_service import (
    IncidentLifecycleView,
    ReportService,
    get_incident_report_payload,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])

DbSessionDep = Annotated[Session, Depends(get_db)]


class IncidentSummarySchema(BaseModel):
    """Compact incident representation for paginated list responses."""

    id: str
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


class PaginatedIncidentsResponse(BaseModel):
    """Paginated response wrapper for querying incident history."""

    limit: int
    offset: int
    count: int
    items: list[IncidentSummarySchema]


class IncidentDetailResponse(IncidentSummarySchema):
    """Detailed incident view including persisted evidence, hypotheses, and RCA report."""

    evidence_count: int
    hypotheses_count: int
    diagnostics_count: int
    remediation_proposals_count: int
    root_cause_summary: str | None = None
    rca_confidence: float | None = None
    unknowns: list[str]
    bounded_next_diagnostic: str | None = None


def _to_summary(inc: Incident) -> IncidentSummarySchema:
    """Convert an Incident ORM instance into an IncidentSummarySchema."""
    return IncidentSummarySchema(
        id=inc.id,
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
    )


def _to_detail(inc: Incident) -> IncidentDetailResponse:
    """Convert an Incident ORM instance into a full IncidentDetailResponse."""
    report = inc.report
    return IncidentDetailResponse(
        id=inc.id,
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
        evidence_count=len(inc.evidence_records),
        hypotheses_count=len(inc.hypotheses),
        diagnostics_count=len(inc.diagnostic_runs),
        remediation_proposals_count=len(inc.remediation_proposals),
        root_cause_summary=report.root_cause_summary if report else None,
        rca_confidence=report.confidence if report else None,
        unknowns=list(report.unknowns_json) if report else [],
        bounded_next_diagnostic=report.bounded_next_diagnostic if report else None,
    )


@router.post(
    "/ingest",
    response_model=IncidentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_alert_endpoint(
    payload: NormalizedAlertInput,
    db: DbSessionDep,
    auto_investigate: Annotated[bool, Query()] = True,
) -> IncidentDetailResponse:
    """Ingest a normalized alert idempotently and trigger or resume RCA investigation."""
    service = IncidentService(session=db)
    incident, _created = service.ingest_and_investigate(
        alert_in=payload,
        auto_investigate=auto_investigate,
    )
    return _to_detail(incident)


@router.get("", response_model=PaginatedIncidentsResponse)
def list_incidents_endpoint(
    db: DbSessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedIncidentsResponse:
    """Return a bounded, paginated list of persisted incidents."""
    repo = IncidentRepository(db)
    incidents = repo.list_incidents(limit=limit, offset=offset)
    items = [_to_summary(inc) for inc in incidents]
    return PaginatedIncidentsResponse(
        limit=limit,
        offset=offset,
        count=len(items),
        items=items,
    )


@router.get("/{incident_id}", response_model=IncidentDetailResponse)
def get_incident_endpoint(
    incident_id: str,
    db: DbSessionDep,
) -> IncidentDetailResponse:
    """Retrieve a single incident and its persisted RCA summary by ID."""
    repo = IncidentRepository(db)
    incident = repo.get_incident_by_id(incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    return _to_detail(incident)


@router.post("/{incident_id}/investigate", response_model=IncidentDetailResponse)
def investigate_or_resume_endpoint(
    incident_id: str,
    db: DbSessionDep,
) -> IncidentDetailResponse:
    """Run or safely resume an interrupted RCA investigation for an existing incident."""
    service = IncidentService(session=db)
    try:
        incident = service.run_or_resume_investigation(incident_id=incident_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return _to_detail(incident)


@router.get("/{incident_id}/lifecycle", response_model=IncidentLifecycleView)
def get_incident_lifecycle_endpoint(
    incident_id: str,
    db: DbSessionDep,
) -> IncidentLifecycleView:
    """Return the complete end-to-end incident lifecycle, timelines, and dashboard links."""
    report_service = ReportService(session=db)
    try:
        return report_service.get_lifecycle_view(incident_id=incident_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/{incident_id}/report")
def get_incident_report_endpoint(
    incident_id: str,
    db: DbSessionDep,
) -> dict[str, object]:
    """Retrieve the full structured RCA report for an incident."""
    repo = IncidentRepository(db)
    incident = repo.get_incident_by_id(incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident '{incident_id}' not found",
        )
    payload = get_incident_report_payload(incident)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RCA report for incident '{incident_id}' is not generated yet",
        )
    return payload


@router.get("/{incident_id}/ui", response_class=HTMLResponse)
def get_incident_ui_endpoint(
    incident_id: str,
    db: DbSessionDep,
) -> HTMLResponse:
    """Render the operator HTML dashboard for end-to-end incident lifecycle inspection."""
    report_service = ReportService(session=db)
    try:
        html_content = report_service.render_incident_html(incident_id=incident_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return HTMLResponse(content=html_content, status_code=status.HTTP_200_OK)