import json

from openpyxl import load_workbook

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

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["task"] == "code"
    assert summary["phase"] == "dev"
    assert "business_accuracy" in summary
    assert (tmp_path / "failures.jsonl").read_text().strip()
    assert json.loads((tmp_path / "failures.jsonl").read_text())["task"] == "code"
    assert json.loads((tmp_path / "failure-clusters.json").read_text())["task"] == "code"
    assert (tmp_path / "results.xlsx").exists()
    wb = load_workbook(tmp_path / "results.xlsx", read_only=True)
    assert next(wb.active.iter_rows(values_only=True))[0] == "task"
    wb.close()
    assert (tmp_path / "prompt.diff").read_text().startswith("--- prompt-before.js")


def test_write_run_artifacts_redacts_optimizer_secrets(tmp_path):
    sample = Sample(2, "a.png", 0, "ABC", True)
    result = EvaluationResult.from_ocr_response(
        sample,
        {"status": 200, "data": [{"number": "ABC"}], "imageStatus": ["ok"]},
    )

    write_run_artifacts(
        run_dir=tmp_path,
        phase="dev",
        results=[result],
        prompt_before="old",
        prompt_after="new",
        optimizer_request={
            "normal": "keep me",
            "env": {"AI_GATEWAY_KEY": "secret-value", "DEC_SALT_TB": "salt-value"},
        },
        optimizer_response={"message": "ok"},
    )

    written = json.loads((tmp_path / "optimizer-request.json").read_text())
    assert written["normal"] == "keep me"
    assert written["env"]["AI_GATEWAY_KEY"] == "[REDACTED]"
    assert written["env"]["DEC_SALT_TB"] == "[REDACTED]"


def test_write_type_run_artifacts_uses_type_summary(tmp_path):
    mismatch = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "Physics", True),
        {"status": 200, "data": [{"type": "E-codes", "number": "Physics"}], "imageStatus": ["ok"]},
        task="type",
    )
    missing = EvaluationResult.from_ocr_response(
        Sample(3, "b.png", 0, "Physics", True),
        {"status": 200, "data": [{"number": "Physics"}], "imageStatus": ["ok"]},
        task="type",
    )

    write_run_artifacts(
        run_dir=tmp_path,
        phase="full",
        results=[mismatch, missing],
        prompt_before="old",
        prompt_after="new",
        optimizer_request={},
        optimizer_response={},
        task="type",
    )

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["task"] == "type"
    assert summary["type_total"] == 1
    assert summary["type_correct"] == 0
    assert summary["type_accuracy"] == 0.0
    assert summary["evaluable_count"] == 1
    assert summary["not_evaluable_count"] == 1
    assert summary["failure_categories"] == {"not_evaluable": 1, "type_mismatch": 1}
