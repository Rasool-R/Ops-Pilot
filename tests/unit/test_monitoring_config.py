"""Unit tests verifying Prometheus and Alertmanager configs conform to telemetry contracts."""

from pathlib import Path

from app.db.models import ServiceId
from app.integrations.telemetry import MetricName

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MONITORING_DIR = PROJECT_ROOT / "monitoring"


def test_prometheus_config_scrapes_simulator_and_opspilot() -> None:
    """Verify prometheus.yml exists and configures scrape jobs and alertmanager."""
    prom_path = MONITORING_DIR / "prometheus.yml"
    if not prom_path.exists():
        prom_path = MONITORING_DIR / "prometheus.yaml"
    assert prom_path.exists(), "monitoring/prometheus.yml or prometheus.yaml must exist"

    content = prom_path.read_text(encoding="utf-8")
    assert "ecomm-simulator:8001" in content
    assert "opspilot-app:8000" in content
    assert "alertmanager:9093" in content
    assert "alert_rules.yml" in content


def test_alert_rules_align_with_shared_telemetry_contracts() -> None:
    """Verify alert_rules.yml uses contract-approved metric names and service IDs."""
    rules_path = MONITORING_DIR / "alert_rules.yml"
    
    if not rules_path.exists():
        rules_path = MONITORING_DIR / "alert-rules.yaml"

    assert rules_path.exists(), "monitoring/alert_rules.yml or alert_rules.yaml must exist"

    content = rules_path.read_text(encoding="utf-8")
    assert MetricName.HTTP_5XX_RATE.value in content
    assert MetricName.HTTP_LATENCY_P95.value in content
    assert MetricName.PG_ACTIVE_CONNECTIONS.value in content
    assert MetricName.PG_POOL_WAIT_TIME_MS.value in content
    assert ServiceId.ORDER_SERVICE.value in content
    assert ServiceId.POSTGRES.value in content


def test_alertmanager_config_routes_to_opspilot_webhook() -> None:
    """Verify alertmanager.yml routes notifications to OpsPilot webhook with bounds."""
    am_path = MONITORING_DIR / "alertmanager.yml"
    
    if not am_path.exists():
        am_path = MONITORING_DIR / "alertmanager.yaml"

    assert am_path.exists(), "monitoring/alertmanager.yml or alertmanager.yaml must exist"

    content = am_path.read_text(encoding="utf-8")
    assert "http://opspilot-app:8000/api/v1/alerts/webhook" in content
    assert "send_resolved: true" in content
    assert "max_alerts: 20" in content