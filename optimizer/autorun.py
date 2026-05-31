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
from optimizer.focused_feedback import (
    build_failed_strategy_memory,
    focused_target_improved,
    select_focused_group,
)
from optimizer.git_control import commit_prompt, restore_prompt
from optimizer.llm import build_optimizer_messages, call_optimizer_llm
from optimizer.node_runner import OcrRunner
from optimizer.prompt_gate import validate_prompt_file
from optimizer.regression_gate import RegressionGateDecision, compare_regression_scores
from optimizer.reporting import (
    write_feedback_failures,
    write_gate_artifact,
    write_regression_artifacts,
    write_run_artifacts,
)
from optimizer.review_feedback import build_review_feedback, write_review_feedback
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
    no_business_learning_count: int = 0,
    no_business_learning_window: int = 3,
) -> bool:
    return bool(
        stop_reason(
            iteration,
            full_accuracy,
            target,
            plateau_count,
            plateau_window,
            max_iterations,
            no_business_learning_count,
            no_business_learning_window,
        )
    )


def stop_reason(
    iteration: int,
    full_accuracy: float,
    target: float,
    plateau_count: int,
    plateau_window: int,
    max_iterations: int,
    no_business_learning_count: int,
    no_business_learning_window: int,
) -> str:
    if full_accuracy >= target:
        return "target_reached"
    if no_business_learning_count >= no_business_learning_window:
        return "no_business_learning"
    if plateau_count >= plateau_window:
        return "plateau"
    if iteration >= max_iterations:
        return "max_iterations"
    return ""


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


def _has_primary_learning(dev_delta: dict) -> bool:
    return bool(dev_delta.get("improved_business_rows") or dev_delta.get("improved_type_rows"))


def _target_failures_for_delta(
    target_failures: Sequence[str],
    feedback_failures: dict,
    focused_feedback_group: dict | None = None,
) -> list[str]:
    group_rows = {}
    if focused_feedback_group:
        rows = focused_feedback_group.get("rows", [])
        return [f"row {row}" for row in rows] if isinstance(rows, list) else []
    else:
        groups = [
            group
            for section in ("primary_groups", "secondary_groups")
            for group in feedback_failures.get(section, [])
        ]
    for group in groups:
        if isinstance(group, dict):
            key = str(group.get("key", "")).strip()
            rows = group.get("rows", [])
            if key and isinstance(rows, list):
                group_rows[key] = [f"row {row}" for row in rows]

    expanded = []
    for target in target_failures:
        # 闭环要求 group key 在进入 delta 前落到 dev rows，否则下一轮只能得到 no_matching_evidence。
        expanded.extend(group_rows.get(str(target).strip(), [target]))
    return expanded


def _record_focused_attempt(
    focused_group: dict | None,
    strategy_summary: str,
    dev_delta: dict,
    prompt_diff: str,
    failed_strategy_memory: list[dict],
    focused_attempt_history: list[dict],
    run_dir: Path,
) -> None:
    if not focused_group:
        return
    group_key = str(focused_group.get("key", "")).strip()
    rows = focused_group.get("rows", [])
    if not group_key or not isinstance(rows, list):
        return

    entry = build_failed_strategy_memory(
        group_key,
        strategy_summary,
        rows,
        dev_delta,
        prompt_diff,
    )
    if entry:
        failed_strategy_memory.append(entry)
        focused_attempt_history.append(entry)
        _write_json(run_dir / "failed-strategy-memory.json", {"entries": failed_strategy_memory})
    elif focused_target_improved(dev_delta, rows):
        focused_attempt_history.append(
            {
                "focused_group": group_key,
                "strategy_summary": strategy_summary,
                "target_rows": rows,
                "outcome": "improved",
            }
        )


def _has_eligible_focused_group(feedback_failures: dict, attempt_history: Sequence[dict]) -> bool:
    return bool(feedback_failures.get("primary_groups")) and bool(
        select_focused_group(feedback_failures, attempt_history)
    )


def _write_review_feedback_overlay(
    review_workbook: str | None,
    run_dir: Path,
    feedback_failures: dict,
    dev_samples: Sequence[Sample],
) -> dict | None:
    if not review_workbook:
        return None
    payload = build_review_feedback(
        review_workbook,
        feedback_failures,
        [sample.row_number for sample in dev_samples],
    )
    write_review_feedback(run_dir, payload)
    return payload


def _optimizer_feedback_for_review(feedback_failures: dict, review_feedback: dict | None) -> dict:
    if not review_feedback:
        return feedback_failures
    background = review_feedback.get("background_groups", {})
    return {
        "task": feedback_failures.get("task"),
        "feedback_set": feedback_failures.get("feedback_set"),
        "review_workbook": review_feedback.get("review_workbook"),
        "primary_groups": list(review_feedback.get("active_groups", [])),
        "secondary_groups": list(background.get("primary_groups", []))
        + list(background.get("secondary_groups", [])),
    }


def _reviewed_targets_for_delta(feedback_failures: dict) -> list[dict]:
    return [
        {"key": group["key"], "rows": list(group.get("rows", []))}
        for group in feedback_failures.get("primary_groups", [])
        if isinstance(group, dict) and group.get("key") and isinstance(group.get("rows"), list)
    ]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_stop_artifact(
    session_dir: Path,
    task: TaskName,
    reason: str,
    iteration: int,
    best_full_accuracy: float,
    best_dev_accuracy: float,
    target_accuracy: float,
    plateau_count: int,
    no_business_learning_count: int,
    last_run_dir: str,
    last_phase: str,
) -> None:
    _write_json(
        session_dir / "stop.json",
        {
            "task": task,
            "reason": reason,
            "iteration": iteration,
            "metrics": {
                "best_full_accuracy": best_full_accuracy,
                "best_dev_accuracy": best_dev_accuracy,
                "target_accuracy": target_accuracy,
            },
            "plateau_count": plateau_count,
            "no_business_learning_count": no_business_learning_count,
            "last_run_dir": last_run_dir,
            "last_phase": last_phase,
        },
    )


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
    review_workbook = getattr(args, "review_workbook", None)
    if review_workbook and task != "code":
        raise ValueError("--review-workbook is only supported for task code")
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
    focused_attempt_history: list[dict] = []
    failed_strategy_memory: list[dict] = []
    no_business_learning_count = 0
    no_business_learning_window = getattr(cfg, "no_business_learning_window", 3)
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
    completed_iteration = 0
    last_run_dir = accepted_dir.name
    last_phase = "full"
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
    feedback_failures = write_feedback_failures(accepted_dir, "dev", accepted_dev_results, task)
    _write_review_feedback_overlay(review_workbook, accepted_dir, feedback_failures, split.dev)

    for iteration in range(1, cfg.max_iterations + 1):
        current_prompt = prompt_path.read_text(encoding="utf-8")
        summary = _read_json(accepted_dir / "summary.json")
        failure_clusters = _read_json(accepted_dir / "failure-clusters.json")
        feedback_failures = _read_json(accepted_dir / "feedback-failures.json")
        review_feedback = _read_json(accepted_dir / "review-feedback.json") if review_workbook else None
        optimizer_feedback = _optimizer_feedback_for_review(feedback_failures, review_feedback)
        has_primary_feedback = bool(optimizer_feedback.get("primary_groups"))
        focused_group = (
            select_focused_group(optimizer_feedback, focused_attempt_history)
            if has_primary_feedback
            else None
        )
        if should_stop(
            iteration - 1,
            best_full_accuracy,
            cfg.target_business_accuracy,
            plateau_count,
            cfg.plateau_window,
            cfg.max_iterations,
            0 if has_primary_feedback else no_business_learning_count,
            no_business_learning_window,
        ):
            break
        if has_primary_feedback and not focused_group:
            no_business_learning_count = no_business_learning_window
            last_phase = "focused_feedback_exhausted"
            break
        failures = _read_failures(accepted_dir / "failures.jsonl")
        system, user = build_optimizer_messages(
            current_prompt,
            summary,
            failure_clusters,
            failures,
            recent_diffs,
            recent_delta_summaries,
            feedback_failures=optimizer_feedback,
            focused_feedback_group=focused_group,
            failed_strategy_memory=failed_strategy_memory,
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
                completed_iteration = iteration
                last_run_dir = run_dir.name
                last_phase = "proposal_no_change"
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
                completed_iteration = iteration
                last_run_dir = run_dir.name
                last_phase = "gate_failed"
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
            target_failures=_target_failures_for_delta(
                proposal.target_failures,
                optimizer_feedback,
                focused_group,
            ),
            reviewed_targets=_reviewed_targets_for_delta(optimizer_feedback) if review_workbook else None,
        )
        _write_json(run_dir / "dev-delta.json", dev_delta)
        dev_delta_summary = summarize_candidate_delta(dev_delta)
        if _has_primary_learning(dev_delta):
            no_business_learning_count = 0
        else:
            no_business_learning_count += 1
        dev_accuracy = _accuracy(dev_results, task)
        if dev_accuracy <= best_dev_accuracy:
            prompt_diff = _write_artifacts(
                run_dir,
                "dev",
                dev_results,
                current_prompt,
                proposal.prompt_file,
                request,
                response,
                task,
            )
            recent_diffs.append(prompt_diff)
            recent_delta_summaries.append(dev_delta_summary)
            _record_focused_attempt(
                focused_group,
                proposal.hypothesis,
                dev_delta,
                prompt_diff,
                failed_strategy_memory,
                focused_attempt_history,
                run_dir,
            )
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1
            completed_iteration = iteration
            last_run_dir = run_dir.name
            last_phase = "dev"
            continue

        _record_focused_attempt(
            focused_group,
            proposal.hypothesis,
            dev_delta,
            "",
            failed_strategy_memory,
            focused_attempt_history,
            run_dir,
        )

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
        completed_iteration = iteration
        last_run_dir = run_dir.name
        last_phase = "full"
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
                    recent_delta_summaries.append(dev_delta_summary)
                    restore_prompt(prompt_path, current_prompt)
                    plateau_count += 1
                    last_phase = "regression"
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
                last_phase = "regression"
            else:
                _write_regression_not_configured(run_dir, task)
            best_full_accuracy = full_accuracy
            best_dev_accuracy = dev_accuracy
            accepted_dev_results = dev_results
            feedback_failures = write_feedback_failures(run_dir, "dev", accepted_dev_results, task)
            _write_review_feedback_overlay(review_workbook, run_dir, feedback_failures, split.dev)
            accepted_dir = run_dir
            plateau_count = 0
            commit_prompt(
                prompt_path,
                f"prompt({task}): improve {task} OCR accuracy to {full_accuracy:.2f}%",
            )
        else:
            recent_delta_summaries.append(dev_delta_summary)
            restore_prompt(prompt_path, current_prompt)
            plateau_count += 1

    reason = stop_reason(
        completed_iteration,
        best_full_accuracy,
        cfg.target_business_accuracy,
        plateau_count,
        cfg.plateau_window,
        cfg.max_iterations,
        (
            0
            if _has_eligible_focused_group(
                _optimizer_feedback_for_review(
                    _read_json(accepted_dir / "feedback-failures.json"),
                    _read_json(accepted_dir / "review-feedback.json") if review_workbook else None,
                ),
                focused_attempt_history,
            )
            else no_business_learning_count
        ),
        no_business_learning_window,
    )
    _write_stop_artifact(
        experiment_dir,
        task,
        reason,
        completed_iteration,
        best_full_accuracy,
        best_dev_accuracy,
        cfg.target_business_accuracy,
        plateau_count,
        no_business_learning_count,
        last_run_dir,
        last_phase,
    )
    print(
        f"run_session={_latest_path(cfg.runs_dir, task, experiment_dir.name)} "
        f"stop_reason={reason}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, choices=("code", "type"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--regression-dataset")
    parser.add_argument("--review-workbook")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
