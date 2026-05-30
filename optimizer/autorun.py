from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from optimizer.candidate_delta import compare_candidate_delta, summarize_candidate_delta
from optimizer.config import OptimizerConfig
from optimizer.dataset import Sample, TaskName, load_dataset, split_samples
from optimizer.evaluation import EvaluationResult, evaluate_samples
from optimizer.git_control import commit_prompt, restore_prompt
from optimizer.llm import build_optimizer_messages, call_optimizer_llm
from optimizer.node_runner import OcrRunner
from optimizer.prompt_gate import validate_prompt_file
from optimizer.regression_gate import RegressionGateDecision, compare_regression_scores
from optimizer.reporting import write_gate_artifact, write_regression_artifacts, write_run_artifacts
from optimizer.scoring import (
    ScoreSummary,
    TypeScoreSummary,
    aggregate_scores,
    aggregate_type_scores,
)


def should_stop(
    iteration: int,
    full_accuracy: float,
    target: float,
    plateau_count: int,
    plateau_window: int,
    max_iterations: int,
) -> bool:
    return full_accuracy >= target or plateau_count >= plateau_window or iteration >= max_iterations


def _accuracy(results: Sequence[EvaluationResult], task: TaskName = "code") -> float:
    summary = _score_summary(results, task)
    return summary.type_accuracy if task == "type" else summary.business_accuracy


def _score_summary(
    results: Sequence[EvaluationResult],
    task: TaskName,
) -> ScoreSummary | TypeScoreSummary:
    if task == "type":
        return aggregate_type_scores(
            result.type_score for result in results if result.type_score is not None
        )
    return aggregate_scores(result.row_score for result in results)


def _run_dir(base: Path, iteration: int) -> Path:
    name = "run-000-baseline" if iteration == 0 else f"run-{iteration:03d}"
    return base / name


def _session_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d_%H-%M-%S")


def _latest_path(runs_dir: Path, task: TaskName, session_name: str) -> str:
    root = runs_dir if not runs_dir.is_absolute() else Path(runs_dir.name)
    return (root / f"card-ocr-prompt-opt-{task}" / session_name).as_posix()


def _create_session_dir(runs_dir: Path, task: TaskName) -> Path:
    task_root = runs_dir / f"card-ocr-prompt-opt-{task}"
    stamp = _session_timestamp()
    for index in range(1, 100):
        suffix = "" if index == 1 else f"-{index:02d}"
        session = task_root / f"{stamp}{suffix}"
        try:
            session.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (task_root / "latest.json").write_text(
            json.dumps(
                {
                    "task": task,
                    "session_dir": session.name,
                    "path": _latest_path(runs_dir, task, session.name),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return session
    raise RuntimeError(f"could not create run session under {task_root}")


async def run_once(
    samples: Sequence[Sample],
    runner: OcrRunner,
    concurrency: int,
    task: TaskName = "code",
) -> list[EvaluationResult]:
    return await evaluate_samples(samples, runner, concurrency, task)


def _results_for_samples(
    results: Sequence[EvaluationResult],
    samples: Sequence[Sample],
) -> list[EvaluationResult]:
    by_row = {result.sample.row_number: result for result in results}
    return [by_row[sample.row_number] for sample in samples if sample.row_number in by_row]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _read_failures(path: Path) -> list[dict]:
    if not path.exists():
        return []
    failures = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                failures.append(json.loads(line))
    return failures


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_artifacts(
    run_dir: Path,
    phase: str,
    results: Sequence[EvaluationResult],
    prompt_before: str,
    prompt_after: str,
    optimizer_request: dict,
    optimizer_response: dict,
    task: TaskName,
) -> str:
    write_run_artifacts(
        run_dir,
        phase,
        results,
        prompt_before,
        prompt_after,
        optimizer_request,
        optimizer_response,
        task,
    )
    diff = run_dir / "prompt.diff"
    return diff.read_text(encoding="utf-8") if diff.exists() else ""


def _gate_retry_user(original_user: str, gate_error: str, invalid_prompt: str) -> str:
    previous_request = json.loads(original_user)
    return json.dumps(
        {
            "task": previous_request.get("task"),
            "mutation_boundary": previous_request.get("mutation_boundary"),
            "previous_request": previous_request,
            "gate_error": gate_error,
            "invalid_prompt_file_prefix": invalid_prompt[:2000],
            "retry_instruction": (
                "Return JSON only with hypothesis, expected_effect, risk, target_failures, "
                "and prompt_file. The prompt_file field must be the complete valid CommonJS "
                "JavaScript file, starting with module.exports = {. Do not return a unified "
                "diff, patch, markdown fence, or excerpt."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _write_regression_gate(
    run_dir: Path,
    task: TaskName,
    decision: str,
    gate: RegressionGateDecision,
    accepted: ScoreSummary | TypeScoreSummary,
    candidate: ScoreSummary | TypeScoreSummary,
) -> None:
    write_gate_artifact(
        run_dir,
        {
            "task": task,
            "phase": "regression",
            "decision": decision,
            "checks": [asdict(check) for check in gate.checks],
            "reason": gate.reason,
            "metrics": {
                "accepted": asdict(accepted),
                "candidate": asdict(candidate),
            },
        },
    )


def _write_regression_not_configured(run_dir: Path, task: TaskName) -> None:
    write_gate_artifact(
        run_dir,
        {
            "task": task,
            "phase": "regression",
            "decision": "not_configured",
            "checks": [],
            "reason": "regression_not_configured",
            "metrics": {},
        },
    )


async def main_async(args: argparse.Namespace) -> int:
    task = args.task
    cfg = OptimizerConfig.from_env()
    samples = load_dataset(args.dataset, task=task)
    regression_dataset = getattr(args, "regression_dataset", None)
    regression_samples = (
        load_dataset(regression_dataset, task=task) if regression_dataset is not None else None
    )
    split = split_samples(samples, cfg.dev_sample_size)
    runner = OcrRunner(cfg.node_binary, cfg.ocr_runner_path)
    experiment_dir = _create_session_dir(cfg.runs_dir, task)
    prompt_path = cfg.prompt_path
    recent_diffs: list[str] = []
    recent_delta_summaries: list[dict] = []
    plateau_count = 0

    validate_prompt_file(prompt_path, cfg.node_binary)
    baseline_prompt = prompt_path.read_text(encoding="utf-8")
    full_results = await run_once(split.full, runner, cfg.ocr_concurrency, task)
    regression_baseline = None
    if regression_samples is not None:
        regression_results = await run_once(regression_samples, runner, cfg.ocr_concurrency, task)
        regression_baseline = _score_summary(regression_results, task)
    best_full_accuracy = _accuracy(full_results, task)
    accepted_dev_results = _results_for_samples(full_results, split.dev)
    best_dev_accuracy = _accuracy(accepted_dev_results, task)
    accepted_dir = _run_dir(experiment_dir, 0)
    _write_artifacts(
        accepted_dir,
        "full",
        full_results,
        baseline_prompt,
        baseline_prompt,
        {},
        {},
        task,
    )

    for iteration in range(1, cfg.max_iterations + 1):
        if should_stop(
            iteration - 1,
            best_full_accuracy,
            cfg.target_business_accuracy,
            plateau_count,
            cfg.plateau_window,
            cfg.max_iterations,
        ):
            break

        current_prompt = prompt_path.read_text(encoding="utf-8")
        summary = _read_json(accepted_dir / "summary.json")
        failure_clusters = _read_json(accepted_dir / "failure-clusters.json")
        failures = _read_failures(accepted_dir / "failures.jsonl")
        system, user = build_optimizer_messages(
            current_prompt,
            summary,
            failure_clusters,
            failures,
            recent_diffs,
            recent_delta_summaries,
            task=task,
        )
        request = {"system": system, "user": user}
        run_dir = _run_dir(experiment_dir, iteration)

        for gate_attempt in range(2):
            proposal = call_optimizer_llm(cfg.optimizer_provider, cfg.optimizer_model, system, user)
            response = asdict(proposal)

            if proposal.prompt_file == current_prompt:
                _write_artifacts(
                    run_dir,
                    "proposal_no_change",
                    [],
                    current_prompt,
                    current_prompt,
                    request,
                    response,
                    task,
                )
                plateau_count += 1
                break

            prompt_path.write_text(proposal.prompt_file, encoding="utf-8")
            try:
                validate_prompt_file(
                    prompt_path,
                    cfg.node_binary,
                    task=task,
                    baseline_source=current_prompt,
                )
                break
            except Exception as exc:
                restore_prompt(prompt_path, current_prompt)
                response["gate_error"] = str(exc)
                if gate_attempt == 0:
                    user = _gate_retry_user(user, str(exc), proposal.prompt_file)
                    request = {"system": system, "user": user}
                    continue
                recent_diffs.append(
                    _write_artifacts(
                        run_dir,
                        "gate_failed",
                        [],
                        current_prompt,
                        proposal.prompt_file,
                        request,
                        response,
                        task,
                    )
                )
                plateau_count += 1
                break
        else:
            continue

        if prompt_path.read_text(encoding="utf-8") == current_prompt:
            continue

        dev_results = await run_once(split.dev, runner, cfg.ocr_concurrency, task)
        dev_delta = compare_candidate_delta(
            task,
            accepted_dev_results,
            dev_results,
            proposal.target_failures,
        )
        _write_json(run_dir / "dev-delta.json", dev_delta)
        recent_delta_summaries.append(summarize_candidate_delta(dev_delta))
        dev_accuracy = _accuracy(dev_results, task)
        if dev_accuracy <= best_dev_accuracy:
            recent_diffs.append(
                _write_artifacts(
                    run_dir,
                    "dev",
                    dev_results,
                    current_prompt,
                    proposal.prompt_file,
                    request,
                    response,
                    task,
                )
            )
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1
            continue

        full_results = await run_once(split.full, runner, cfg.ocr_concurrency, task)
        full_accuracy = _accuracy(full_results, task)
        recent_diffs.append(
            _write_artifacts(
                run_dir,
                "full",
                full_results,
                current_prompt,
                proposal.prompt_file,
                request,
                response,
                task,
            )
        )
        if full_accuracy > best_full_accuracy:
            if regression_samples is not None and regression_baseline is not None:
                regression_results = await run_once(
                    regression_samples,
                    runner,
                    cfg.ocr_concurrency,
                    task,
                )
                candidate_regression = _score_summary(regression_results, task)
                regression_gate = compare_regression_scores(
                    task,
                    regression_baseline,
                    candidate_regression,
                )
                if not regression_gate.passed:
                    write_regression_artifacts(run_dir, regression_results, task)
                    _write_regression_gate(
                        run_dir,
                        task,
                        "discard",
                        regression_gate,
                        regression_baseline,
                        candidate_regression,
                    )
                    restore_prompt(prompt_path, current_prompt)
                    plateau_count += 1
                    continue
                _write_regression_gate(
                    run_dir,
                    task,
                    "keep",
                    regression_gate,
                    regression_baseline,
                    candidate_regression,
                )
                regression_baseline = candidate_regression
            else:
                _write_regression_not_configured(run_dir, task)
            best_full_accuracy = full_accuracy
            best_dev_accuracy = dev_accuracy
            accepted_dev_results = dev_results
            accepted_dir = run_dir
            plateau_count = 0
            commit_prompt(
                prompt_path,
                f"prompt({task}): improve {task} OCR accuracy to {full_accuracy:.2f}%",
            )
        else:
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, choices=("code", "type"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--regression-dataset")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
