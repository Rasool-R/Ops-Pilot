"""CLI entrypoint to run the deterministic OpsPilot AI evaluation suite."""

from pathlib import Path

from evaluation.evaluators import SuiteEvaluationSummary, run_evaluation_suite

DEFAULT_DATASET_PATH = Path(__file__).resolve().parent / "dataset.jsonl"


def main() -> SuiteEvaluationSummary:
    """Execute evaluation benchmark and print JSON summary."""
    summary = run_evaluation_suite(DEFAULT_DATASET_PATH)
    print(summary.model_dump_json(indent=2))
    return summary


if __name__ == "__main__":
    main()