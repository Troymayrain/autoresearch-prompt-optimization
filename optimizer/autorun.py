from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from optimizer.config import OptimizerConfig
from optimizer.dataset import Sample, TaskName, load_dataset, split_samples
from optimizer.evaluation import EvaluationResult, evaluate_samples
from optimizer.git_control import commit_prompt, restore_prompt
from optimizer.llm import build_optimizer_messages, call_optimizer_llm
from optimizer.node_runner import OcrRunner
from optimizer.prompt_gate import validate_prompt_file
from optimizer.reporting import write_run_artifacts
from optimizer.scoring import aggregate_scores, aggregate_type_scores


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
    if task == "type":
        return aggregate_type_scores(
            result.type_score for result in results if result.type_score is not None
        ).type_accuracy
    return aggregate_scores(result.row_score for result in results).business_accuracy


def _run_dir(base: Path, iteration: int) -> Path:
    name = "run-000-baseline" if iteration == 0 else f"run-{iteration:03d}"
    return base / name


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
                "Return JSON only. The prompt_file field must be the complete valid "
                "CommonJS JavaScript file, starting with module.exports = {. Do not return "
                "a unified diff, patch, markdown fence, or excerpt."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


async def main_async(args: argparse.Namespace) -> int:
    task = args.task
    cfg = OptimizerConfig.from_env()
    samples = load_dataset(args.dataset, task=task)
    split = split_samples(samples, cfg.dev_sample_size)
    runner = OcrRunner(cfg.node_binary, cfg.ocr_runner_path)
    experiment_dir = cfg.runs_dir / f"card-ocr-prompt-opt-{task}"
    prompt_path = cfg.prompt_path
    recent_diffs: list[str] = []
    plateau_count = 0

    validate_prompt_file(prompt_path, cfg.node_binary)
    baseline_prompt = prompt_path.read_text(encoding="utf-8")
    full_results = await run_once(split.full, runner, cfg.ocr_concurrency, task)
    best_full_accuracy = _accuracy(full_results, task)
    best_dev_accuracy = _accuracy(_results_for_samples(full_results, split.dev), task)
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
            best_full_accuracy = full_accuracy
            best_dev_accuracy = dev_accuracy
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
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
