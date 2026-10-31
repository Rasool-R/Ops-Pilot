"""Integration tests for Alertmanager webhook ingestion, correlation, and auth."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models import AuditEvent, Incident
from app.db.session import get_db
from app.main import create_app


@pytest.fixture()
def webhook_db() -> Generator[Session, None, None]:
    """Create an isolated in-memory database for Alertmanager webhook tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _sample_webhook_payload(
    status: str = "firing",
    service_id: str = "order-service",
    fingerprint: str = "fp-am-order-5xx",
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> dict[str, object]:
    """Build a realistic Alertmanager v4 webhook JSON payload."""
    start_dt = starts_at or datetime.now(UTC) - timedelta(minutes=2)
    alert_item: dict[str, object] = {
        "status": status,
        "labels": {
            "alertname": "OrderServiceHigh5xxRate",
            "service_id": service_id,
            "severity": "CRITICAL",
        },
        "annotations": {
            "summary": "Elevated HTTP 5xx error rate detected on order-service",
        },
        "startsAt": start_dt.isoformat(),
        "fingerprint": fingerprint,
    }
    if ends_at is not None:
        alert_item["endsAt"] = ends_at.isoformat()

    return {
        "version": "4",
        "status": status,
        "receiver": "opspilot-webhook",
        "alerts": [alert_item],
    }


def test_webhook_firing_repeated_and_resolved_lifecycle(webhook_db: Session) -> None:
    """Verify firing alert triggers RCA, repeated correlates, and resolved logs audit."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield webhook_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    t0 = datetime.now(UTC) - timedelta(minutes=5)
    payload_1 = _sample_webhook_payload(status="firing", starts_at=t0)

    # 1. First firing delivery creates incident and runs investigation
    resp_1 = client.post("/api/v1/alerts/webhook", json=payload_1)
    assert resp_1.status_code == 200
    data_1 = resp_1.json()
    assert data_1["firing_processed"] == 1
    assert data_1["incidents_created"] == 1
    assert len(data_1["incident_ids"]) == 1
    incident_id = data_1["incident_ids"][0]

    # 2. Repeated firing delivery correlates into the same incident without duplicating
    t1 = datetime.now(UTC) - timedelta(minutes=1)
    payload_2 = _sample_webhook_payload(status="firing", starts_at=t1)
    resp_2 = client.post("/api/v1/alerts/webhook", json=payload_2)
    assert resp_2.status_code == 200
    data_2 = resp_2.json()
    assert data_2["firing_processed"] == 1
    assert data_2["incidents_created"] == 0
    assert data_2["incident_ids"] == [incident_id]

    all_incidents = list(webhook_db.scalars(select(Incident)).all())
    assert len(all_incidents) == 1
    assert len(all_incidents[0].alerts) == 2

    # 3. Resolved webhook delivery updates ends_at_utc and records audit event
    resolved_payload = _sample_webhook_payload(
        status="resolved",
        starts_at=t0,
        ends_at=datetime.now(UTC),
    )
    resp_3 = client.post("/api/v1/alerts/webhook", json=resolved_payload)
    assert resp_3.status_code == 200
    data_3 = resp_3.json()
    assert data_3["resolved_processed"] == 1
    assert data_3["incident_ids"] == [incident_id]

    events = list(
        webhook_db.scalars(
            select(AuditEvent).where(AuditEvent.incident_id == incident_id)
        ).all()
    )
    assert any(ev.event_type == "alert.resolved_notification" for ev in events)


def test_webhook_skips_stale_alerts_and_rejects_malformed_service(
    webhook_db: Session,
) -> None:
    """Verify stale firing alerts are skipped and invalid service_ids return HTTP 422."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield webhook_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    stale_start = datetime.now(UTC) - timedelta(hours=48)
    stale_payload = _sample_webhook_payload(status="firing", starts_at=stale_start)
    stale_resp = client.post("/api/v1/alerts/webhook", json=stale_payload)
    assert stale_resp.status_code == 200
    assert stale_resp.json()["stale_skipped"] == 1
    assert stale_resp.json()["incidents_created"] == 0

    bad_service_payload = _sample_webhook_payload(
        status="firing",
        service_id="unknown-rogue-service",
    )
    bad_resp = client.post("/api/v1/alerts/webhook", json=bad_service_payload)
    assert bad_resp.status_code == 422


def test_webhook_enforces_shared_secret_when_configured(webhook_db: Session) -> None:
    """Verify webhook rejects missing/wrong secret with 401 and accepts valid secret."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield webhook_db

    def override_settings() -> Settings:
        return Settings(
            APP_ENV="testing",
            WEBHOOK_SHARED_SECRET="top-secret-webhook-key",  # type: ignore[arg-type] # noqa: S106
        )

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_settings
    client = TestClient(app)

    payload = _sample_webhook_payload(status="firing")

    # Missing header -> 401
    unauth_resp = client.post("/api/v1/alerts/webhook", json=payload)
    assert unauth_resp.status_code == 401

    # Matching header -> 200
    auth_resp = client.post(
        "/api/v1/alerts/webhook",
        json=payload,
        headers={"X-OpsPilot-Webhook-Secret": "top-secret-webhook-key"},
    )
    assert auth_resp.status_code == 200
    assert auth_resp.json()["incidents_created"] == 1