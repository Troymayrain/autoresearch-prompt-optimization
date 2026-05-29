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

    assert _accuracy([result], task="code") == 100.0


def test_accuracy_uses_type_score_for_type_task():
    result = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "Physics", True),
        {"status": 200, "data": [{"type": "Physics", "number": "wrong"}], "imageStatus": ["ok"]},
        task="type",
    )

    assert _accuracy([result], task="type") == 100.0


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
            OptimizerProposal("h", "e", "r", ["row 2"], "bad"),
            OptimizerProposal("h", "e", "r", ["row 2"], "good"),
        ]
    )

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    loaded_tasks = []

    def fake_load_dataset(path, task):
        loaded_tasks.append(task)
        return [sample]

    monkeypatch.setattr(autorun, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(
        autorun,
        "validate_prompt_file",
        lambda path, node_binary="node", task=None, baseline_source=None: None,
    )
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: pytest.fail("should not commit"))

    async def fake_run_once(samples, runner, concurrency, task):
        assert task == "code"
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

    assert loaded_tasks == ["code"]
    assert seen_accuracies == [100.0, 100.0]
    assert prompt.read_text(encoding="utf-8") == "good"


@pytest.mark.asyncio
async def test_autorun_retries_once_when_optimizer_returns_invalid_prompt(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("old-valid", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "Physics", True)
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
            OptimizerProposal("h1", "e1", "r1", ["row 2"], "--- prompt.js\n+++ prompt.js\n@@\n+bad"),
            OptimizerProposal("h2", "e2", "r2", ["row 2"], "new-valid"),
        ]
    )
    seen_users = []
    commits = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(autorun, "load_dataset", lambda path, task: [sample])
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: commits.append(message))

    def fake_validate(path, node_binary="node", task=None, baseline_source=None):
        if prompt.read_text(encoding="utf-8").startswith("---"):
            raise RuntimeError("prompt syntax check failed")

    async def fake_run_once(samples, runner, concurrency, task):
        actual_type = "Physics" if prompt.read_text(encoding="utf-8") == "new-valid" else "E-codes"
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"type": actual_type, "number": "wrong"}], "imageStatus": ["ok"]},
                task="type",
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
    assert commits == ["prompt(type): improve type OCR accuracy to 100.00%"]
    summary = json.loads((tmp_path / "runs/card-ocr-prompt-opt-type/run-001/summary.json").read_text())
    assert summary["task"] == "type"


@pytest.mark.asyncio
async def test_autorun_uses_type_metric_for_keep_commit_and_artifacts(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("old-valid", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "Physics", True)
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
    commits = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(autorun, "load_dataset", lambda path, task: [sample])
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(
        autorun,
        "validate_prompt_file",
        lambda path, node_binary="node", task=None, baseline_source=None: None,
    )
    monkeypatch.setattr(
        autorun,
        "call_optimizer_llm",
        lambda provider, model, system, user: OptimizerProposal("h", "e", "r", ["row 2"], "new-valid"),
    )
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: commits.append(message))

    async def fake_run_once(samples, runner, concurrency, task):
        assert task == "type"
        actual_type = "Physics" if prompt.read_text(encoding="utf-8") == "new-valid" else "E-codes"
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"type": actual_type, "number": "wrong"}], "imageStatus": ["ok"]},
                task="type",
            )
            for item in samples
        ]

    monkeypatch.setattr(autorun, "run_once", fake_run_once)

    await autorun.main_async(argparse.Namespace(dataset="dataset.xlsx", task="type"))

    assert commits == ["prompt(type): improve type OCR accuracy to 100.00%"]
    summary = json.loads((tmp_path / "runs/card-ocr-prompt-opt-type/run-001/summary.json").read_text())
    assert summary["task"] == "type"
    assert summary["type_accuracy"] == 100.0


@pytest.mark.asyncio
async def test_autorun_records_gate_failure_without_running_dev_or_full(tmp_path, monkeypatch):
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
    run_prompts = []
    proposals = iter(
        [
            OptimizerProposal("h1", "e1", "r1", ["row 2"], "bad-boundary"),
            OptimizerProposal("h2", "e2", "r2", ["row 2"], "bad-boundary"),
        ]
    )

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))
    monkeypatch.setattr(autorun, "load_dataset", lambda path, task: [sample])
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(autorun, "call_optimizer_llm", lambda provider, model, system, user: next(proposals))
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: pytest.fail("should not commit"))

    def fake_validate(path, node_binary="node", task=None, baseline_source=None):
        if prompt.read_text(encoding="utf-8") == "bad-boundary":
            raise RuntimeError("code task cannot change protected exports")

    async def fake_run_once(samples, runner, concurrency, task):
        run_prompts.append(prompt.read_text(encoding="utf-8"))
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"number": "A"}], "imageStatus": ["ok"]},
            )
            for item in samples
        ]

    monkeypatch.setattr(autorun, "validate_prompt_file", fake_validate)
    monkeypatch.setattr(autorun, "run_once", fake_run_once)

    await autorun.main_async(argparse.Namespace(dataset="dataset.xlsx", task="code"))

    assert run_prompts == ["old-valid"]
    summary = json.loads((tmp_path / "runs/card-ocr-prompt-opt-code/run-001/summary.json").read_text())
    response = json.loads((tmp_path / "runs/card-ocr-prompt-opt-code/run-001/optimizer-response.json").read_text())
    assert summary["phase"] == "gate_failed"
    assert summary["task"] == "code"
    assert "code task cannot change protected exports" in response["gate_error"]


@pytest.mark.asyncio
async def test_autorun_loads_regression_dataset_with_selected_task_schema(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("valid", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "Physics", True)
    cfg = types.SimpleNamespace(
        dev_sample_size=1,
        ocr_concurrency=1,
        runs_dir=tmp_path / "runs",
        prompt_path=prompt,
        node_binary="node",
        ocr_runner_path="runner.js",
        max_iterations=0,
        target_business_accuracy=101.0,
        plateau_window=3,
        optimizer_provider="test",
        optimizer_model="test",
    )
    loaded = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))

    def fake_load_dataset(path, task):
        loaded.append((path, task))
        return [sample]

    async def fake_run_once(samples, runner, concurrency, task):
        return [
            EvaluationResult.from_ocr_response(
                item,
                {"status": 200, "data": [{"type": "Physics", "number": "wrong"}], "imageStatus": ["ok"]},
                task="type",
            )
            for item in samples
        ]

    monkeypatch.setattr(autorun, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=[sample], full=[sample]))
    monkeypatch.setattr(
        autorun,
        "validate_prompt_file",
        lambda path, node_binary="node", task=None, baseline_source=None: None,
    )
    monkeypatch.setattr(autorun, "run_once", fake_run_once)

    await autorun.main_async(
        argparse.Namespace(dataset="dataset.xlsx", regression_dataset="regression.xlsx", task="type")
    )

    assert loaded == [("dataset.xlsx", "type"), ("regression.xlsx", "type")]


@pytest.mark.asyncio
async def test_autorun_fails_fast_when_regression_dataset_is_malformed(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("valid", encoding="utf-8")
    sample = Sample(2, "a.png", 0, "A", True)
    cfg = types.SimpleNamespace(
        dev_sample_size=1,
        ocr_concurrency=1,
        runs_dir=tmp_path / "runs",
        prompt_path=prompt,
        node_binary="node",
        ocr_runner_path="runner.js",
        max_iterations=0,
        target_business_accuracy=101.0,
        plateau_window=3,
        optimizer_provider="test",
        optimizer_model="test",
    )

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))

    def fake_load_dataset(path, task):
        if path == "regression.xlsx":
            raise ValueError("missing required columns: md5_card_number")
        return [sample]

    monkeypatch.setattr(autorun, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(autorun, "run_once", lambda *args, **kwargs: pytest.fail("should fail before OCR"))

    with pytest.raises(ValueError, match="missing required columns: md5_card_number"):
        await autorun.main_async(
            argparse.Namespace(dataset="dataset.xlsx", regression_dataset="regression.xlsx", task="code")
        )


@pytest.mark.asyncio
async def test_autorun_discards_full_improvement_when_regression_gate_fails(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("accepted", encoding="utf-8")
    main_sample = Sample(2, "main.png", 0, "MAIN", True)
    regression_sample = Sample(99, "guard.png", 0, "SAFE", True)
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
    proposals = iter(
        [
            OptimizerProposal("h1", "e1", "r1", ["row 99"], "candidate"),
            OptimizerProposal("h2", "e2", "r2", ["row 99"], "accepted"),
        ]
    )
    seen_accuracies = []
    run_labels = []
    commits = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))

    def fake_load_dataset(path, task):
        return [regression_sample] if path == "regression.xlsx" else [main_sample]

    async def fake_run_once(samples, runner, concurrency, task):
        sample = samples[0]
        prompt_text = prompt.read_text(encoding="utf-8")
        is_regression = sample.row_number == regression_sample.row_number
        run_labels.append(("regression" if is_regression else "main", prompt_text))
        if is_regression:
            actual = "SAFE" if prompt_text == "accepted" else "MISS"
        else:
            actual = "MAIN" if prompt_text == "candidate" else "MISS"
        return [
            EvaluationResult.from_ocr_response(
                sample,
                {"status": 200, "data": [{"number": actual}], "imageStatus": ["ok"]},
            )
        ]

    def fake_call(provider, model, system, user):
        seen_accuracies.append(json.loads(user)["summary"]["business_accuracy"])
        return next(proposals)

    monkeypatch.setattr(autorun, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=samples, full=samples))
    monkeypatch.setattr(
        autorun,
        "validate_prompt_file",
        lambda path, node_binary="node", task=None, baseline_source=None: None,
    )
    monkeypatch.setattr(autorun, "run_once", fake_run_once)
    monkeypatch.setattr(autorun, "call_optimizer_llm", fake_call)
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: commits.append(message))

    await autorun.main_async(
        argparse.Namespace(dataset="dataset.xlsx", regression_dataset="regression.xlsx", task="code")
    )

    assert commits == []
    assert prompt.read_text(encoding="utf-8") == "accepted"
    assert seen_accuracies == [0.0, 0.0]
    assert run_labels == [
        ("main", "accepted"),
        ("regression", "accepted"),
        ("main", "candidate"),
        ("main", "candidate"),
        ("regression", "candidate"),
    ]


@pytest.mark.asyncio
async def test_autorun_updates_regression_baseline_after_accepted_candidate(tmp_path, monkeypatch):
    prompt = tmp_path / "prompts" / "ocr.js"
    prompt.parent.mkdir()
    prompt.write_text("accepted", encoding="utf-8")
    main_sample = Sample(2, "main.png", 0, "A\nB", True)
    regression_sample = Sample(99, "guard.png", 0, "SAFE\nGUARD", True)
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
    proposals = iter(
        [
            OptimizerProposal("h1", "e1", "r1", ["row 2"], "candidate-one"),
            OptimizerProposal("h2", "e2", "r2", ["row 2"], "candidate-two"),
        ]
    )
    seen_accuracies = []
    commits = []

    monkeypatch.setattr(autorun.OptimizerConfig, "from_env", classmethod(lambda cls: cfg))

    def fake_load_dataset(path, task):
        return [regression_sample] if path == "regression.xlsx" else [main_sample]

    async def fake_run_once(samples, runner, concurrency, task):
        sample = samples[0]
        prompt_text = prompt.read_text(encoding="utf-8")
        if sample.row_number == regression_sample.row_number:
            actual = "SAFE" if prompt_text == "candidate-one" else ""
        elif prompt_text == "candidate-one":
            actual = "A"
        elif prompt_text == "candidate-two":
            actual = "A\nB"
        else:
            actual = ""
        return [
            EvaluationResult.from_ocr_response(
                sample,
                {"status": 200, "data": [{"number": actual}], "imageStatus": ["ok"]},
            )
        ]

    def fake_call(provider, model, system, user):
        seen_accuracies.append(json.loads(user)["summary"]["business_accuracy"])
        return next(proposals)

    monkeypatch.setattr(autorun, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(autorun, "split_samples", lambda samples, size: DatasetSplit(dev=samples, full=samples))
    monkeypatch.setattr(
        autorun,
        "validate_prompt_file",
        lambda path, node_binary="node", task=None, baseline_source=None: None,
    )
    monkeypatch.setattr(autorun, "run_once", fake_run_once)
    monkeypatch.setattr(autorun, "call_optimizer_llm", fake_call)
    monkeypatch.setattr(autorun, "commit_prompt", lambda path, message: commits.append(message))

    await autorun.main_async(
        argparse.Namespace(dataset="dataset.xlsx", regression_dataset="regression.xlsx", task="code")
    )

    assert commits == ["prompt(code): improve code OCR accuracy to 50.00%"]
    assert prompt.read_text(encoding="utf-8") == "candidate-one"
    assert seen_accuracies == [0.0, 50.0]
