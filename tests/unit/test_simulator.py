"""Unit tests for the disposable e-commerce simulator and scenario lifecycle."""

from fastapi.testclient import TestClient

from app.simulator.service import create_simulator_app


def test_simulator_healthy_baseline_and_metrics() -> None:
    """Verify simulator starts or resets to healthy state with low 5xx and pool wait."""
    client = TestClient(create_simulator_app())
    reset_resp = client.post("/admin/scenario/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["fault_injected"] is False

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    body = metrics_resp.text
    assert 'http_requests_5xx_rate{service="order-service"} 0.001' in body
    assert 'pg_pool_wait_time_ms{service="order-service"} 4.0' in body


def test_simulator_fault_injection_exposes_symptoms_without_leaking_ground_truth() -> None:
    """Verify triggering the fault produces 5xx/pool symptoms without ground-truth labels."""
    client = TestClient(create_simulator_app())
    trigger_resp = client.post("/admin/scenario/trigger")
    assert trigger_resp.status_code == 200
    assert trigger_resp.json()["fault_injected"] is True

    metrics_body = client.get("/metrics").text
    assert 'http_requests_5xx_rate{service="order-service"} 0.24' in metrics_body
    assert 'pg_stat_activity_active_connections{service="postgres"} 100.0' in metrics_body
    assert "root_cause" not in metrics_body.lower()
    assert "ground_truth" not in metrics_body.lower()

    logs_resp = client.get("/telemetry/logs", params={"service_id": "order-service"})
    assert logs_resp.status_code == 200
    logs_payload = logs_resp.json()
    assert logs_payload["count"] >= 1
    assert "QueuePool limit" in str(logs_payload["logs"])


def test_simulator_remediation_restores_healthy_telemetry() -> None:
    """Verify executing reset_db_connection_pool recovers the simulator to healthy state."""
    client = TestClient(create_simulator_app())
    client.post("/admin/scenario/trigger")

    remediate_resp = client.post(
        "/admin/remediation/execute",
        json={
            "action_type": "reset_db_connection_pool",
            "target": "order-service",
            "parameters": {"force": True},
        },
    )
    assert remediate_resp.status_code == 200
    assert remediate_resp.json()["executed"] is True

    metrics_after = client.get("/metrics").text
    assert 'http_requests_5xx_rate{service="order-service"} 0.001' in metrics_after

    client.post("/admin/scenario/reset")