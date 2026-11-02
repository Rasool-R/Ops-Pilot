from scripts.verify_mvp_readiness import run_readiness_check, verify_repository_completeness


def test_mvp_readiness_script_confirms_all_artifacts_and_eval_gates() -> None:
    """Ensure all required MVP files exist and readiness verification returns True."""
    missing = verify_repository_completeness()
    assert missing == [], f"Missing required files: {missing}"
    assert run_readiness_check() is True