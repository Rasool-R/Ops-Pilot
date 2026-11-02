from pathlib import Path

from evaluation.evaluators import run_evaluation_suite

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES: tuple[str, ...] = (
    "README.md",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yaml",
    "alembic.ini",
    ".env.example",
    ".github/workflows/ci.yml",
    "monitoring/prometheus.yaml",
    "monitoring/alertmanager.yaml",
    "monitoring/alert_rules.yaml",
    "monitoring/grafana/opspilot-incident-dashboard.json",
    "runbooks/postgres-connection-pool-exhaustion.md",
    "runbooks/postgres-manual-failover-human-only.md",
    "docs/architecture.md",
    "docs/implementation-plan.md",
    "docs/task-board.md",
    "docs/collaboration.md",
    "docs/integration-contracts.md",
    "docs/telemetry-contracts.md",
    "docs/data-model.md",
    "docs/graph-workflow.md",
    "docs/security.md",
    "docs/testing.md",
    "docs/evaluation.md",
    "docs/deployment.md",
    "docs/troubleshooting.md",
    "docs/decisions/0001-mvp-baseline-architecture.md",
    "docs/decisions/0002-phase12-advanced-capabilities.md",
)


def verify_repository_completeness(root: Path = PROJECT_ROOT) -> list[str]:
    """Return a list of any missing required files from the repository."""
    missing: list[str] = []
    for rel_path in REQUIRED_FILES:
        if not (root / rel_path).exists():
            missing.append(rel_path)
    return missing


def run_readiness_check() -> bool:
    """Verify required files and evaluation benchmark gates."""
    missing = verify_repository_completeness()
    if missing:
        raise RuntimeError(f"Missing required project files: {', '.join(missing)}")

    dataset_path = PROJECT_ROOT / "evaluation" / "dataset.jsonl"
    eval_summary = run_evaluation_suite(dataset_path)
    if eval_summary.total_safety_violations != 0 or eval_summary.mean_rca_accuracy < 1.0:
        raise RuntimeError("AI evaluation quality gate failed during readiness check.")

    print(
        f"OpsPilot MVP readiness verified: {len(REQUIRED_FILES)} core artifacts present, "
        f"RCA accuracy={eval_summary.mean_rca_accuracy}, "
        f"safety_violations={eval_summary.total_safety_violations}."
    )
    return True


if __name__ == "__main__":
    run_readiness_check()