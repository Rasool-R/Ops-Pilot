"""Integration tests for Phase 10 Incident UI, lifecycle timeline, and exposure review."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.services.report_service import build_infrastructure_links


@pytest.fixture()
def ui_db() -> Generator[Session, None, None]:
    """Create an isolated in-memory database for end-to-end lifecycle and UI tests."""
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


def test_operator_can_inspect_full_incident_lifecycle_report_and_ui_end_to_end(
    ui_db: Session,
) -> None:
    """Verify ingest -> RCA -> approval -> execution -> lifecycle/report/UI inspection."""
    app = create_app()

    def override_get_db() -> Generator[Session, None, None]:
        yield ui_db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    # 1. Ingest alert and trigger RCA investigation
    ingest_resp = client.post(
        "/api/v1/incidents/ingest",
        json={
            "idempotency_key": "ui-test-delivery-001",
            "alert_fingerprint": "fp-ui-order-pool",
            "service_id": "order-service",
            "title": "Order-service 5xx spike for UI lifecycle test",
            "severity": "CRITICAL",
            "starts_at_utc": "2026-10-30T10:00:00Z",
        },
    )
    assert ingest_resp.status_code == 201
    incident_id = ingest_resp.json()["id"]

    # 2. Fetch lifecycle view to obtain the proposal_id
    lifecycle_initial = client.get(f"/api/v1/incidents/{incident_id}/lifecycle")
    assert lifecycle_initial.status_code == 200
    initial_data = lifecycle_initial.json()
    assert len(initial_data["proposals"]) == 1
    proposal_id = initial_data["proposals"][0]["proposal_id"]

    # 3. Approve and execute remediation
    decide_resp = client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/decide",
        json={
            "approver_id": "sre.rasool",
            "decision": "APPROVED",
            "reason": "Approved from Incident UI test",
        },
    )
    assert decide_resp.status_code == 200

    exec_resp = client.post(
        f"/api/v1/approvals/proposals/{proposal_id}/execute",
        json={"parameters": {"force": True}, "dry_run": True},
    )
    assert exec_resp.status_code == 200

    # 4. Inspect full lifecycle JSON after recovery verification
    lifecycle_final = client.get(f"/api/v1/incidents/{incident_id}/lifecycle")
    assert lifecycle_final.status_code == 200
    final_data = lifecycle_final.json()

    assert final_data["incident_status"] == "RESOLVED"
    assert final_data["investigation_status"] == "COMPLETED"
    assert final_data["approval_status"] == "APPROVED"
    assert final_data["remediation_execution_status"] == "SUCCEEDED"
    assert final_data["recovery_verification_status"] == "VERIFIED_RECOVERED"
    assert len(final_data["evidence_timeline"]) >= 5
    assert len(final_data["approvals"]) == 1
    assert len(final_data["executions"]) == 1
    assert final_data["executions"][0]["recovered"] is True
    assert len(final_data["audit_timeline"]) >= 5
    assert "prometheus_service_5xx_url" in final_data["dashboard_links"]

    # 5. Retrieve standalone structured RCA report
    report_resp = client.get(f"/api/v1/incidents/{incident_id}/report")
    assert report_resp.status_code == 200
    report_data = report_resp.json()
    assert report_data["status"] == "COMPLETED"
    assert "RB-PG-POOL-001" in str(report_data["runbook_citations"])

    # 6. Inspect HTML UI endpoint
    ui_resp = client.get(f"/api/v1/incidents/{incident_id}/ui")
    assert ui_resp.status_code == 200
    html_body = ui_resp.text
    assert "Incident Overview:" in html_body
    assert "VERIFIED_RECOVERED" in html_body
    assert "Prometheus HTTP 5xx Graph" in html_body


def test_dashboard_links_strip_embedded_credentials_for_exposure_safety() -> None:
    """Verify infrastructure links never expose credentials embedded in base URLs."""
    settings = Settings(
        APP_ENV="testing",
        PROMETHEUS_BASE_URL="http://prom_admin:super_secret_prom_pw@prometheus.internal:9090",
        ALERTMANAGER_BASE_URL="http://am_user:am_secret_pw@alertmanager.internal:9093",
    )
    links = build_infrastructure_links("order-service", settings=settings)

    assert "super_secret_prom_pw" not in links.prometheus_service_5xx_url
    assert "prom_admin" not in links.prometheus_service_5xx_url
    assert "am_secret_pw" not in links.alertmanager_alerts_url
    assert links.prometheus_service_5xx_url.startswith("http://prometheus.internal:9090/graph")