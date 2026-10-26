"""Unit tests verifying GitHub Actions CI configuration and governance templates."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_enforces_least_privilege_and_quality_gates() -> None:
    """Verify .github/workflows/ci.yml exists and includes mandatory CI checks."""
    ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), "CI workflow file must exist at .github/workflows/ci.yml"

    content = ci_path.read_text(encoding="utf-8")
    assert "contents: read" in content
    assert "ruff check app tests" in content
    assert "mypy app tests" in content
    assert "pytest tests/unit -v" in content
    assert "postgres:16-alpine" in content


def test_github_governance_files_exist() -> None:
    """Verify CODEOWNERS and PULL_REQUEST_TEMPLATE.md exist and define key sections."""
    codeowners_path = PROJECT_ROOT / ".github" / "CODEOWNERS"
    pr_template_path = PROJECT_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"

    assert codeowners_path.exists(), "CODEOWNERS must exist in .github/"
    assert pr_template_path.exists(), "PULL_REQUEST_TEMPLATE.md must exist in .github/"

    pr_content = pr_template_path.read_text(encoding="utf-8")
    assert "Database & Migration Impact" in pr_content
    assert "Security Review" in pr_content