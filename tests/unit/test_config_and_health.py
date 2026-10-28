"""Unit tests for configuration bounds, secret masking, and health endpoints."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db.session import get_db
from app.main import create_app


def test_settings_defaults_and_secret_masking() -> None:
    """Ensure settings enforce safe defaults and do not leak secrets in string representations."""
    settings = Settings(
        APP_ENV="testing",
        LLM_API_KEY="super-secret-llm-key",  # type: ignore[arg-type]
        DATABASE_URL="postgresql+psycopg://user:super-secret-db-pass@localhost:5432/db",  # type: ignore[arg-type]
    )
    assert settings.APP_ENV == "testing"
    assert settings.REMEDIATION_DRY_RUN_ONLY is True
    assert "super-secret-llm-key" not in repr(settings.LLM_API_KEY)
    assert "super-secret-db-pass" not in repr(settings.DATABASE_URL)


def test_settings_rejects_unbounded_values() -> None:
    """Verify that out-of-range operational bounds raise a ValidationError."""
    with pytest.raises(ValidationError):
        Settings(GRAPH_MAX_STEPS=100)

    with pytest.raises(ValidationError):
        Settings(TELEMETRY_TIMEOUT_SECONDS=0)

    with pytest.raises(ValidationError):
        Settings(TELEMETRY_MAX_PAYLOAD_BYTES=10_000_000)


def test_liveness_endpoint_returns_ok() -> None:
    """Verify /api/v1/health returns HTTP 200 and expected service metadata."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "OpsPilot"


def test_readiness_endpoint_when_db_is_healthy() -> None:
    """Verify /api/v1/health/ready returns HTTP 200 when SELECT 1 succeeds."""
    app = create_app()
    mock_session = MagicMock()

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] == "ok"
    mock_session.execute.assert_called_once()


def test_readiness_endpoint_when_db_fails() -> None:
    """Verify /api/v1/health/ready returns HTTP 503 without leaking sensitive error details."""
    app = create_app()
    mock_session = MagicMock()
    mock_session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("password authentication failed for user")
    )

    def override_get_db() -> Generator[MagicMock, None, None]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "database_unreachable: OperationalError"
    assert "password" not in payload["database"]