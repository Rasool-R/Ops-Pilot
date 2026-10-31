"""FastAPI webhook endpoint for Alertmanager ingestion and correlation."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.repository import IncidentRepository
from app.db.session import get_db
from app.integrations.alertmanager import (
    AlertmanagerWebhookPayload,
    is_alert_stale,
    normalize_alertmanager_item,
)
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/alerts", tags=["alerts"])

DbSessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class WebhookIngestionResponse(BaseModel):
    """Structured summary of processed, correlated, resolved, and skipped webhook alerts."""

    firing_processed: int = 0
    incidents_created: int = 0
    resolved_processed: int = 0
    stale_skipped: int = 0
    incident_ids: list[str] = Field(default_factory=list)


def verify_webhook_secret(
    settings: Settings,
    provided_secret: str | None,
) -> None:
    """Validate optional shared webhook secret using constant-time comparison."""
    configured_val = settings.WEBHOOK_SHARED_SECRET.get_secret_value()
    if not configured_val or configured_val == "unconfigured":
        return

    if not provided_secret or not secrets.compare_digest(provided_secret, configured_val):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-OpsPilot-Webhook-Secret header.",
        )


@router.post(
    "/webhook",
    response_model=WebhookIngestionResponse,
    status_code=status.HTTP_200_OK,
)
def alertmanager_webhook_endpoint(
    payload: AlertmanagerWebhookPayload,
    db: DbSessionDep,
    settings: SettingsDep,
    x_opspilot_webhook_secret: Annotated[str | None, Header()] = None,
) -> WebhookIngestionResponse:
    """Receive Alertmanager notifications, enforce auth, correlate, and investigate."""
    verify_webhook_secret(settings=settings, provided_secret=x_opspilot_webhook_secret)

    inc_service = IncidentService(session=db)
    repo = IncidentRepository(session=db)

    summary = WebhookIngestionResponse()
    seen_incident_ids: list[str] = []

    for item in payload.alerts:
        if is_alert_stale(item):
            summary.stale_skipped += 1
            continue

        try:
            normalized = normalize_alertmanager_item(item)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        if item.status == "resolved":
            incident, matched = repo.record_resolved_alert(normalized)
            if matched and incident is not None:
                summary.resolved_processed += 1
                if incident.id not in seen_incident_ids:
                    seen_incident_ids.append(incident.id)
            continue

        incident, created_new = inc_service.ingest_and_investigate(
            alert_in=normalized,
            auto_investigate=True,
        )
        summary.firing_processed += 1
        if created_new:
            summary.incidents_created += 1
        if incident.id not in seen_incident_ids:
            seen_incident_ids.append(incident.id)

    summary.incident_ids = seen_incident_ids
    return summary