from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Sequence

from openpyxl import Workbook

from optimizer.dataset import TaskName
from optimizer.evaluation import EvaluationResult, INFRASTRUCTURE_FAILURES
from optimizer.scoring import aggregate_scores, aggregate_type_scores, normalize_business

SECRET_KEY_MARKERS = (
    "secret",
    "token",
    "authorization",
    "password",
    "credential",
    "salt",
    "api_key",
    "gateway_key",
    "base64",
    "raw_image",
    "image_bytes",
    "ssm_value",
)


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(key) else _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _is_secret_key(key: object) -> bool:
    lowered = str(key).lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def _summary(task: TaskName, phase: str, results: Sequence[EvaluationResult]) -> dict[str, object]:
    failures = Counter(result.failure_category for result in results if result.failure_category)
    summary: dict[str, object] = {
        "task": task,
        "phase": phase,
        "samples": len(results),
        "failure_categories": dict(sorted(failures.items())),
    }
    if task == "type":
        score = aggregate_type_scores(result.type_score for result in results if result.type_score is not None)
        summary.update(
            {
                "type_total": score.type_total,
                "type_correct": score.type_correct,
                "type_accuracy": score.type_accuracy,
                "evaluable_count": score.type_total,
                "not_evaluable_count": score.not_evaluable_count,
            }
        )
        return summary

    score = aggregate_scores(result.row_score for result in results)
    summary.update(
        {
            "business_total": score.business_total,
            "business_correct": score.business_correct,
            "business_accuracy": score.business_accuracy,
            "strict_correct": score.strict_correct,
            "strict_accuracy": score.strict_accuracy,
        }
    )
    return summary


def write_gate_artifact(run_dir: Path, payload: dict) -> None:
    required = ("task", "phase", "decision", "checks", "reason", "metrics")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"gate payload missing: {', '.join(missing)}")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "gate.json", _sanitize(payload))


def write_regression_artifacts(
    run_dir: Path,
    results: Sequence[EvaluationResult],
    task: TaskName,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "regression-summary.json", _summary(task, "regression", results))
    _write_results_xlsx(run_dir / "regression-results.xlsx", results, task)


def write_feedback_failures(
    run_dir: Path,
    feedback_set: str,
    results: Sequence[EvaluationResult],
    task: TaskName = "code",
    last_candidate_results: Sequence[EvaluationResult] | None = None,
) -> dict[str, object]:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = _feedback_failures(feedback_set, results, task)
    _write_json(run_dir / "feedback-failures.json", payload)
    _write_feedback_review_xlsx(
        run_dir / "feedback-review.xlsx",
        results,
        task,
        last_candidate_results or [],
    )
    return payload


def _feedback_failures(
    feedback_set: str,
    results: Sequence[EvaluationResult],
    task: TaskName,
) -> dict[str, object]:
    primary: dict[str, dict[str, object]] = {}
    secondary: dict[str, dict[str, object]] = {}
    for result in results:
        key, is_secondary = _feedback_group_key(result, task)
        if not key:
            continue
        target = secondary if is_secondary else primary
        _add_feedback_group_result(target, key, result, task)
    return {
        "task": task,
        "feedback_set": feedback_set,
        "primary_groups": list(primary.values()),
        "secondary_groups": list(secondary.values()),
    }


def _feedback_group_key(result: EvaluationResult, task: TaskName) -> tuple[str, bool]:
    if result.failure_category in INFRASTRUCTURE_FAILURES:
        return "", False
    if task == "type":
        if result.failure_category:
            return result.failure_category, False
        return "", False

    category = result.failure_category
    if category == "wrong_code":
        # 业务优先：先把“选错码来源”和“字符识别错”拆开，避免 optimizer 只记行号。
        if _selected_non_redeemable_number(result):
            return "wrong_code_selected_non_redeemable_number", False
        return "wrong_code_ocr_confusion", False
    if category == "no_card":
        return "no_card_false_negative", False
    if category == "missing_code":
        return "missing_code", False
    if category == "extra_code":
        return "extra_code_output", True
    if _strict_only_code_issue(result):
        return "strict_code_cleanliness", True
    return "", False


def _selected_non_redeemable_number(result: EvaluationResult) -> bool:
    expected = normalize_business(result.sample.expected_raw)
    if not expected or not re.search(r"[A-Z]", expected):
        return False
    return any(
        _digits_only(actual) and len(_digits_only(actual)) >= 12
        for actual in result.actual_numbers
    )


def _strict_only_code_issue(result: EvaluationResult) -> bool:
    score = result.row_score
    return bool(
        score.business_total
        and score.business_correct == score.business_total
        and score.strict_correct < score.business_total
    )


def _digits_only(value: object) -> str:
    return re.sub(r"\D+", "", str(value))


def _add_feedback_group_result(
    groups: dict[str, dict[str, object]],
    key: str,
    result: EvaluationResult,
    task: TaskName,
) -> None:
    group = groups.setdefault(
        key,
        {
            "key": key,
            "failure_category": result.failure_category,
            "reason": _feedback_reason(key),
            "count": 0,
            "rows": [],
            "examples": [],
        },
    )
    group["count"] = int(group["count"]) + 1
    group["rows"].append(result.sample.row_number)
    if len(group["examples"]) < 5:
        group["examples"].append(_feedback_example(result, task))


def _feedback_example(result: EvaluationResult, task: TaskName) -> dict[str, object]:
    actual = result.actual_types if task == "type" else result.actual_numbers
    return {
        "row_number": result.sample.row_number,
        "card_image": result.sample.card_image,
        "origin": result.sample.origin,
        "expected": result.sample.expected_raw,
        "actual": actual,
        "failure_category": result.failure_category,
        "image_status": result.image_status,
    }


def _feedback_reason(key: str) -> str:
    return {
        "wrong_code_selected_non_redeemable_number": "selected a non-redeemable numeric value instead of the gift card code",
        "wrong_code_ocr_confusion": "selected a code-like value with character-level OCR differences",
        "no_card_false_negative": "reported no card or no valid code when a labeled code exists",
        "missing_code": "returned no redeemable code for a scoreable row",
        "extra_code_output": "returned the expected code plus additional unmatched code output",
        "strict_code_cleanliness": "business match passed but strict code presentation still changed",
    }.get(key, key)


def _write_feedback_review_xlsx(
    path: Path,
    results: Sequence[EvaluationResult],
    task: TaskName,
    last_candidate_results: Sequence[EvaluationResult],
) -> None:
    last_by_row = {result.sample.row_number: result for result in last_candidate_results}
    wb = Workbook()
    ws = wb.active
    ws.title = "feedback-review"
    ws.append(
        [
            "group_key",
            "row_number",
            "origin",
            "card_image",
            "expected",
            "accepted_actual",
            "last_candidate_actual",
            "failure_category",
            "review_decision",
            "review_notes",
        ]
    )
    for result in results:
        key, _ = _feedback_group_key(result, task)
        if not key:
            continue
        last_candidate = last_by_row.get(result.sample.row_number)
        ws.append(
            [
                key,
                result.sample.row_number,
                result.sample.origin,
                result.sample.card_image,
                result.sample.expected_raw,
                _actual_text(result, task),
                _actual_text(last_candidate, task) if last_candidate else "",
                result.failure_category,
                "",
                "",
            ]
        )
    wb.save(path)


def _actual_text(result: EvaluationResult, task: TaskName) -> str:
    actual = result.actual_types if task == "type" else result.actual_numbers
    return "\n".join(actual)


def _write_results_xlsx(path: Path, results: Sequence[EvaluationResult], task: TaskName) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "results"
    base_columns = [
        "task",
        "row_number",
        "card_image",
        "origin",
        "expected",
        "actual",
    ]
    if task == "type":
        ws.append(
            base_columns
            + [
                "type_correct",
                "type_total",
                "not_evaluable_reason",
                "failure_category",
                "image_status",
            ]
        )
        for result in results:
            type_score = result.type_score
            if type_score is None:
                raise ValueError("type results require type_score")
            ws.append(
                _base_result_row(task, result, result.actual_types)
                + [
                    type_score.type_correct,
                    type_score.type_total,
                    type_score.not_evaluable_reason,
                    result.failure_category,
                    result.image_status,
                ]
            )
    else:
        ws.append(
            base_columns
            + [
                "business_correct",
                "business_total",
                "failure_category",
                "image_status",
            ]
        )
        for result in results:
            ws.append(
                _base_result_row(task, result, result.actual_numbers)
                + [
                    result.row_score.business_correct,
                    result.row_score.business_total,
                    result.failure_category,
                    result.image_status,
                ]
            )
    wb.save(path)


def _base_result_row(task: TaskName, result: EvaluationResult, actual: Sequence[str]) -> list[object]:
    return [
        task,
        result.sample.row_number,
        result.sample.card_image,
        result.sample.origin,
        result.sample.expected_raw,
        "\n".join(actual),
    ]


def write_run_artifacts(
    run_dir: Path,
    phase: str,
    results: Sequence[EvaluationResult],
    prompt_before: str,
    prompt_after: str,
    optimizer_request: dict,
    optimizer_response: dict,
    task: TaskName = "code",
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary = _summary(task, phase, results)
    _write_json(run_dir / "summary.json", summary)
    _write_json(
        run_dir / "failure-clusters.json",
        {"task": task, "failure_categories": summary["failure_categories"]},
    )
    _write_json(run_dir / "optimizer-request.json", _sanitize(optimizer_request))
    _write_json(run_dir / "optimizer-response.json", _sanitize(optimizer_response))
    (run_dir / "prompt-before.js").write_text(prompt_before, encoding="utf-8")
    (run_dir / "prompt-after.js").write_text(prompt_after, encoding="utf-8")
    (run_dir / "prompt.diff").write_text(
        "".join(
            difflib.unified_diff(
                prompt_before.splitlines(True),
                prompt_after.splitlines(True),
                fromfile="prompt-before.js",
                tofile="prompt-after.js",
            )
        ),
        encoding="utf-8",
    )
    with (run_dir / "failures.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            if result.failure_category:
                handle.write(
                    json.dumps(
                        {
                            "row_number": result.sample.row_number,
                            "task": task,
                            "card_image": result.sample.card_image,
                            "expected": result.sample.expected_raw,
                            "actual": (
                                result.actual_types
                                if task == "type"
                                else result.actual_numbers
                            ),
                            "failure_category": result.failure_category,
                            "image_status": result.image_status,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    _write_results_xlsx(run_dir / "results.xlsx", results, task)
