import argparse
import json
import types

import pytest

import optimizer.autorun as autorun
from optimizer.autorun import _accuracy, should_stop
from optimizer.dataset import DatasetSplit, Sample
from optimizer.evaluation import EvaluationResult
from optimizer.llm import OptimizerProposal


def test_stop_when_target_reached():
    assert should_stop(iteration=3, full_accuracy=99.0, target=99.0, plateau_count=0, plateau_window=3, max_iterations=15)


def test_stop_when_plateau_window_reached():
    assert should_stop(iteration=4, full_accuracy=90.0, target=99.0, plateau_count=3, plateau_window=3, max_iterations=15)


def test_stop_when_max_iterations_reached():
    assert should_stop(iteration=15, full_accuracy=90.0, target=99.0, plateau_count=0, plateau_window=3, max_iterations=15)


def test_continue_before_limits():
    assert not should_stop(iteration=2, full_accuracy=90.0, target=99.0, plateau_count=1, plateau_window=3, max_iterations=15)


def test_accuracy_uses_business_score_only():
    result = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "A-B-C", True),
        {"status": 200, "data": [{"number": "ABC"}], "imageStatus": ["ok"]},
    )

    assert _accuracy([result]) == 100.0


@pytest.mark.asyncio
async def test_autorun_uses_last_accepted_summary_after_rejected_candidate(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("good", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "A", True)
    cfg = types.SimpleNamespace(
        dev_sample_size=1,
        ocr_concurrency=1,
        runs_dir=tmp_path / "runs",
        prompt_path=prompt,
        node_binary="node",
        ocr_runner_path="runner.js",
        max_iterations=2,
        target_business_accuracy=101.0,
        plateau_window=3,
        optimizer_provider="test",
        optimizer_model="test",
    )
    seen_accuracies = []
    proposals = iter(
        [
            OptimizerProposal("h", "e", "r", "bad"),
            OptimizerProposal("h", "e", "r", "good"),
        ]
    )

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(autorun, "load_dataset", lambda path: [sample])
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(autorun, "validate_prompt_file", lambda path, node_binary="node": None)
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: pytest.fail("should not commit"))

    async def fake_run_once(samples, runner, concurrency):
        actual = "B" if prompt.read_text(encoding="utf-8") == "bad" else "A"
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"number": actual}], "imageStatus": ["ok"]},
            )
            for item in samples
        ]

    def fake_call(provider, model, system, user):
        seen_accuracies.append(json.loads(user)["summary"]["business_accuracy"])
        return next(proposals)

    monkeypatch.setattr(autorun, "run_once", fake_run_once)
    monkeypatch.setattr(autorun, "call_optimizer_llm", fake_call)

    await autorun.main_async(argparse.Namespace(dataset="dataset.xlsx", task="code"))

    assert seen_accuracies == [100.0, 100.0]
    assert prompt.read_text(encoding="utf-8") == "good"


@pytest.mark.asyncio
async def test_autorun_retries_once_when_optimizer_returns_invalid_prompt(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("old-valid", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "A", True)
    cfg = types.SimpleNamespace(
        dev_sample_size=1,
        ocr_concurrency=1,
        runs_dir=tmp_path / "runs",
        prompt_path=prompt,
        node_binary="node",
        ocr_runner_path="runner.js",
        max_iterations=1,
        target_business_accuracy=101.0,
        plateau_window=3,
        optimizer_provider="test",
        optimizer_model="test",
    )
    proposals = iter(
        [
            OptimizerProposal("h1", "e1", "r1", "--- prompt.js\n+++ prompt.js\n@@\n+bad"),
            OptimizerProposal("h2", "e2", "r2", "new-valid"),
        ]
    )
    seen_users = []
    commits = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(autorun, "load_dataset", lambda path: [sample])
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: commits.append(message))

    def fake_validate(path, node_binary="node"):
        if prompt.read_text(encoding="utf-8").startswith("---"):
            raise RuntimeError("prompt syntax check failed")

    async def fake_run_once(samples, runner, concurrency):
        actual = "A" if prompt.read_text(encoding="utf-8") == "new-valid" else "B"
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"number": actual}], "imageStatus": ["ok"]},
            )
            for item in samples
        ]

    def fake_call(provider, model, system, user):
        seen_users.append(user)
        return next(proposals)

    monkeypatch.setattr(autorun, "validate_prompt_file", fake_validate)
    monkeypatch.setattr(autorun, "run_once", fake_run_once)
    monkeypatch.setattr(autorun, "call_optimizer_llm", fake_call)

    await autorun.main_async(argparse.Namespace(dataset="dataset.xlsx", task="type"))

    assert len(seen_users) == 2
    retry_payload = json.loads(seen_users[1])
    assert retry_payload["task"] == "type"
    assert "PROMPT_COMPLEX" in " ".join(retry_payload["mutation_boundary"]["allowed"])
    assert retry_payload["gate_error"] == "prompt syntax check failed"
    assert prompt.read_text(encoding="utf-8") == "new-valid"
    assert commits == ["prompt: improve card OCR accuracy to 100.00%"]
    assert json.loads((tmp_path / "runs/card-ocr-prompt-opt/run-001/summary.json").read_text())["phase"] == "full"
