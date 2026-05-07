import json

from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult
from optimizer.reporting import write_run_artifacts


def test_write_run_artifacts_creates_summary_failures_and_excel(tmp_path):
    sample = Sample(2, "a.png", 0, "ABC", True)
    result = EvaluationResult.from_ocr_response(sample, {"status": 200, "data": [], "imageStatus": ["ok"]})

    write_run_artifacts(
        run_dir=tmp_path,
        phase="dev",
        results=[result],
        prompt_before="old",
        prompt_after="new",
        optimizer_request={"a": 1},
        optimizer_response={"b": 2},
    )

    assert json.loads((tmp_path / "summary.json").read_text())["phase"] == "dev"
    assert (tmp_path / "failures.jsonl").read_text().strip()
    assert (tmp_path / "results.xlsx").exists()
    assert (tmp_path / "prompt.diff").read_text().startswith("--- prompt-before.js")
