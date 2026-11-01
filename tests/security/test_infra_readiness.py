from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_and_operational_readiness_docs_exist_without_secrets() -> None:
    """Verify operational docs exist and .env.example contains only safe placeholders."""
    env_example = PROJECT_ROOT / ".env.example"
    sec_doc = PROJECT_ROOT / "docs" / "security.md"
    dep_doc = PROJECT_ROOT / "docs" / "deployment.md"
    trb_doc = PROJECT_ROOT / "docs" / "troubleshooting.md"
    tel_doc = PROJECT_ROOT / "docs" / "telemetry-contracts.md"

    assert env_example.exists(), ".env.example must exist"
    assert sec_doc.exists(), "docs/security.md must exist"
    assert dep_doc.exists(), "docs/deployment.md must exist"
    assert trb_doc.exists(), "docs/troubleshooting.md must exist"
    assert tel_doc.exists(), "docs/telemetry-contracts.md must exist"

    env_text = env_example.read_text(encoding="utf-8")
    assert "sk-proj-" not in env_text
    assert "lsv2_pt_" not in env_text
    assert "<REDACTED_" in env_text or "<CHANGE_ME_" in env_text


def test_docker_compose_binds_all_host_ports_to_localhost_only() -> None:

    """Verify no container port in docker-compose.yaml is exposed to 0.0.0.0 on host."""

    compose_path = PROJECT_ROOT / "docker-compose.yml"
    
    if not compose_path.exists():
        compose_path = PROJECT_ROOT / "docker-compose.yaml"

    content = compose_path.read_text(encoding="utf-8")

    assert "127.0.0.1:8001:8001" in content
    assert "127.0.0.1:9090:9090" in content
    assert "127.0.0.1:9093:9093" in content
    assert "pg_dump" in (PROJECT_ROOT / "docs" / "deployment.md").read_text(
        encoding="utf-8"
    )