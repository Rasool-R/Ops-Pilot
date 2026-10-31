"""Alertmanager webhook schemas, normalization, and staleness checks."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import ServiceId, Severity
from app.db.repository import NormalizedAlertInput

MAX_ALERT_STALENESS_HOURS = 24


class AlertmanagerAlertItem(BaseModel):
    """Single alert object inside an Alertmanager v4 webhook payload."""

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime
    endsAt: datetime | None = None
    fingerprint: str = Field(min_length=1, max_length=128)


class AlertmanagerWebhookPayload(BaseModel):
    """Bounded Alertmanager webhook payload matching monitoring/alertmanager.yml."""

    version: str = "4"
    status: Literal["firing", "resolved"]
    receiver: str = Field(default="opspilot-webhook", max_length=128)
    alerts: list[AlertmanagerAlertItem] = Field(min_length=1, max_length=20)


def ensure_utc(dt: datetime) -> datetime:
    """Normalize a datetime instance to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_alert_stale(
    item: AlertmanagerAlertItem,
    now_utc: datetime | None = None,
    max_age_hours: int = MAX_ALERT_STALENESS_HOURS,
) -> bool:
    """Return True if a firing alert started beyond the allowed staleness window."""
    if item.status != "firing":
        return False
    current_time = now_utc or datetime.now(UTC)
    starts_utc = ensure_utc(item.startsAt)
    return (current_time - starts_utc) > timedelta(hours=max_age_hours)


def build_alert_idempotency_key(item: AlertmanagerAlertItem) -> str:
    """Generate a deterministic idempotency key from fingerprint, status, and startsAt."""
    starts_utc = ensure_utc(item.startsAt)
    raw = f"{item.fingerprint}:{item.status}:{int(starts_utc.timestamp())}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"am-{digest}"


def normalize_alertmanager_item(item: AlertmanagerAlertItem) -> NormalizedAlertInput:
    """Validate and convert an Alertmanager alert item into NormalizedAlertInput."""
    raw_service = item.labels.get("service_id") or item.labels.get("service") or ""
    try:
        service_id = ServiceId(raw_service)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported or missing service_id '{raw_service}' in alert labels."
        ) from exc

    raw_severity = item.labels.get("severity", "WARNING").upper()
    try:
        severity = Severity(raw_severity)
    except ValueError:
        severity = Severity.WARNING

    title = (
        item.annotations.get("summary")
        or item.labels.get("alertname")
        or f"Alert on {service_id.value}"
    )

    starts_utc = ensure_utc(item.startsAt)
    ends_utc = ensure_utc(item.endsAt) if item.endsAt is not None else None

    return NormalizedAlertInput(
        idempotency_key=build_alert_idempotency_key(item),
        alert_fingerprint=item.fingerprint,
        service_id=service_id,
        title=title[:255],
        severity=severity,
        starts_at_utc=starts_utc,
        ends_at_utc=ends_utc,
        labels=dict(item.labels),
        annotations=dict(item.annotations),
    )