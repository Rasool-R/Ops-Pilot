"""Unit tests verifying Dockerfile and docker-compose.yml structural and security requirements."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_enforces_non_root_and_healthcheck() -> None:
    """Verify Dockerfile defines a non-root user and a container HEALTHCHECK."""
    dockerfile_path = PROJECT_ROOT / "Dockerfile"
    assert dockerfile_path.exists(), "Dockerfile must exist in project root"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "USER opspilot" in content
    assert "HEALTHCHECK" in content
    assert "/api/v1/health" in content


def test_docker_compose_defines_postgres_healthcheck_and_limits() -> None:
    """Verify docker-compose.yml includes postgres, healthchecks, volumes, and resource limits."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist in project root"

    content = compose_path.read_text(encoding="utf-8")
    assert "postgres:16-alpine" in content
    assert "pg_isready" in content
    assert "service_healthy" in content
    assert "postgres_data:" in content
    assert "limits:" in content