from __future__ import annotations

import re
from typing import Sequence

from optimizer.dataset import TaskName
from optimizer.evaluation import EvaluationResult, INFRASTRUCTURE_FAILURES
from optimizer.scoring import aggregate_scores, aggregate_type_scores

SECONDARY_CODE_FAILURES = {"extra_code"}
ROW_GROUP_KEYS = (
    "improved_business_rows",
    "regressed_business_rows",
    "persistent_business_failure_rows",
    "strict_only_changed_rows",
    "infra_failure_rows",
    "improved_type_rows",
    "regressed_type_rows",
    "persistent_type_failure_rows",
    "not_evaluable_rows",
)


def compare_candidate_delta(
    task: TaskName,
    accepted: Sequence[EvaluationResult],
    candidate: Sequence[EvaluationResult],
    target_failures: Sequence[str] | None = None,
) -> dict:
    if task == "type":
        delta = _type_delta(accepted, candidate)
    else:
        delta = _code_delta(accepted, candidate)
    if target_failures:
        _add_target_failures_effect(delta, target_failures)
    return delta


def summarize_candidate_delta(delta: dict, row_limit: int = 5, value_limit: int = 80) -> dict:
    summary = {
        "task": delta.get("task"),
        "primary_metric": delta.get("primary_metric"),
        "secondary_metric": delta.get("secondary_metric"),
    }
    for key in ROW_GROUP_KEYS:
        rows = delta.get(key)
        if rows:
            summary[key] = [_summarize_row(row, value_limit) for row in rows[:row_limit]]
    for key in ("target_failures_effect", "target_priority_mismatch"):
        if key in delta:
            summary[key] = delta[key]
    return summary


def _summarize_row(row: dict, value_limit: int) -> dict:
    result = {
        "row_number": row["row_number"],
        "accepted_failure_category": row["accepted_failure_category"],
        "candidate_failure_category": row["candidate_failure_category"],
    }
    for key in ("business_delta", "strict_delta", "type_delta"):
        if key in row:
            result[key] = row[key]
    result["accepted_actual"] = _bounded_values(row.get("accepted_actual", []), value_limit)
    result["candidate_actual"] = _bounded_values(row.get("candidate_actual", []), value_limit)
    return result


def _bounded_values(values: Sequence[object], limit: int) -> list[str]:
    return [_bounded_text(value, limit) for value in values]


def _bounded_text(value: object, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _pairs(
    accepted: Sequence[EvaluationResult],
    candidate: Sequence[EvaluationResult],
) -> list[tuple[EvaluationResult, EvaluationResult]]:
    accepted_by_row = {result.sample.row_number: result for result in accepted}
    return [
        (accepted_by_row[result.sample.row_number], result)
        for result in candidate
        if result.sample.row_number in accepted_by_row
    ]


def _metric(name: str, accepted_correct: int, candidate_correct: int, total: int) -> dict:
    return {
        "name": name,
        "accepted_correct": accepted_correct,
        "candidate_correct": candidate_correct,
        "total": total,
        "delta": candidate_correct - accepted_correct,
    }


def _code_delta(
    accepted: Sequence[EvaluationResult],
    candidate: Sequence[EvaluationResult],
) -> dict:
    accepted_summary = aggregate_scores(result.row_score for result in accepted)
    candidate_summary = aggregate_scores(result.row_score for result in candidate)
    delta = {
        "task": "code",
        "primary_metric": _metric(
            "business_code_match",
            accepted_summary.business_correct,
            candidate_summary.business_correct,
            max(accepted_summary.business_total, candidate_summary.business_total),
        ),
        "secondary_metric": _metric(
            "strict_code_match",
            accepted_summary.strict_correct,
            candidate_summary.strict_correct,
            max(accepted_summary.business_total, candidate_summary.business_total),
        ),
        "improved_business_rows": [],
        "regressed_business_rows": [],
        "persistent_business_failure_rows": [],
        "strict_only_changed_rows": [],
        "infra_failure_rows": [],
    }
    for accepted_result, candidate_result in _pairs(accepted, candidate):
        detail = _code_row_detail(accepted_result, candidate_result)
        if _has_infra_failure(accepted_result, candidate_result):
            delta["infra_failure_rows"].append(detail)
        elif detail["business_delta"] > 0:
            delta["improved_business_rows"].append(detail)
        elif detail["business_delta"] < 0:
            delta["regressed_business_rows"].append(detail)
        elif detail["business_total"] and detail["candidate_business_correct"] < detail["business_total"]:
            delta["persistent_business_failure_rows"].append(detail)
        elif detail["strict_delta"] != 0 or _has_secondary_code_failure(accepted_result, candidate_result):
            delta["strict_only_changed_rows"].append(detail)
    return delta


def _code_row_detail(accepted: EvaluationResult, candidate: EvaluationResult) -> dict:
    accepted_score = accepted.row_score
    candidate_score = candidate.row_score
    return {
        "row_number": candidate.sample.row_number,
        "expected": candidate_score.expected_raw,
        "accepted_actual": accepted_score.actual_raw,
        "candidate_actual": candidate_score.actual_raw,
        "accepted_failure_category": accepted.failure_category,
        "candidate_failure_category": candidate.failure_category,
        "business_total": max(accepted_score.business_total, candidate_score.business_total),
        "accepted_business_correct": accepted_score.business_correct,
        "candidate_business_correct": candidate_score.business_correct,
        "business_delta": candidate_score.business_correct - accepted_score.business_correct,
        "accepted_strict_correct": accepted_score.strict_correct,
        "candidate_strict_correct": candidate_score.strict_correct,
        "strict_delta": candidate_score.strict_correct - accepted_score.strict_correct,
    }


def _has_infra_failure(accepted: EvaluationResult, candidate: EvaluationResult) -> bool:
    return (
        accepted.failure_category in INFRASTRUCTURE_FAILURES
        or candidate.failure_category in INFRASTRUCTURE_FAILURES
    )


def _has_secondary_code_failure(accepted: EvaluationResult, candidate: EvaluationResult) -> bool:
    return bool(SECONDARY_CODE_FAILURES & {accepted.failure_category, candidate.failure_category})


def _type_delta(
    accepted: Sequence[EvaluationResult],
    candidate: Sequence[EvaluationResult],
) -> dict:
    accepted_scores = [result.type_score for result in accepted if result.type_score is not None]
    candidate_scores = [result.type_score for result in candidate if result.type_score is not None]
    accepted_summary = aggregate_type_scores(accepted_scores)
    candidate_summary = aggregate_type_scores(candidate_scores)
    delta = {
        "task": "type",
        "primary_metric": _metric(
            "card_type_match",
            accepted_summary.type_correct,
            candidate_summary.type_correct,
            max(accepted_summary.type_total, candidate_summary.type_total),
        ),
        "secondary_metric": {
            "name": "not_evaluable",
            "accepted_count": accepted_summary.not_evaluable_count,
            "candidate_count": candidate_summary.not_evaluable_count,
            "delta": candidate_summary.not_evaluable_count - accepted_summary.not_evaluable_count,
        },
        "improved_type_rows": [],
        "regressed_type_rows": [],
        "persistent_type_failure_rows": [],
        "not_evaluable_rows": [],
    }
    for accepted_result, candidate_result in _pairs(accepted, candidate):
        detail = _type_row_detail(accepted_result, candidate_result)
        if detail["candidate_not_evaluable_reason"] or detail["accepted_not_evaluable_reason"]:
            delta["not_evaluable_rows"].append(detail)
        elif detail["type_delta"] > 0:
            delta["improved_type_rows"].append(detail)
        elif detail["type_delta"] < 0:
            delta["regressed_type_rows"].append(detail)
        elif detail["type_total"] and detail["candidate_type_correct"] < detail["type_total"]:
            delta["persistent_type_failure_rows"].append(detail)
    return delta


def _type_row_detail(accepted: EvaluationResult, candidate: EvaluationResult) -> dict:
    if accepted.type_score is None or candidate.type_score is None:
        raise ValueError("type delta requires type evaluation results")
    accepted_score = accepted.type_score
    candidate_score = candidate.type_score
    return {
        "row_number": candidate.sample.row_number,
        "expected": candidate_score.expected_raw,
        "accepted_actual": accepted_score.actual_raw,
        "candidate_actual": candidate_score.actual_raw,
        "accepted_failure_category": accepted.failure_category,
        "candidate_failure_category": candidate.failure_category,
        "type_total": max(accepted_score.type_total, candidate_score.type_total),
        "accepted_type_correct": accepted_score.type_correct,
        "candidate_type_correct": candidate_score.type_correct,
        "type_delta": candidate_score.type_correct - accepted_score.type_correct,
        "accepted_not_evaluable_reason": accepted_score.not_evaluable_reason,
        "candidate_not_evaluable_reason": candidate_score.not_evaluable_reason,
    }


def _add_target_failures_effect(delta: dict, target_failures: Sequence[str]) -> None:
    details = _all_row_details(delta)
    by_row = {detail["row_number"]: detail for detail in details}
    effect = {"row_targets": [], "category_targets": []}
    mismatches = []
    for target in target_failures:
        row_number = _target_row_number(target)
        if row_number is not None:
            result = _row_target_effect(str(target), row_number, by_row)
            effect["row_targets"].append(result)
        else:
            result = _category_target_effect(str(target).strip(), details)
            effect["category_targets"].append(result)
        if _is_priority_mismatch(result):
            mismatches.append(str(target))
    delta["target_failures_effect"] = effect
    if mismatches:
        delta["target_priority_mismatch"] = mismatches


def _all_row_details(delta: dict) -> list[dict]:
    details = []
    for key, value in delta.items():
        if key.endswith("_rows") and isinstance(value, list):
            details.extend(value)
    return details


def _target_row_number(target: object) -> int | None:
    text = str(target).strip().lower()
    if text.isdigit():
        return int(text)
    match = re.fullmatch(r"row\s+(\d+)", text)
    return int(match.group(1)) if match else None


def _row_target_effect(target: str, row_number: int, by_row: dict[int, dict]) -> dict:
    detail = by_row.get(row_number)
    if detail is None:
        return {
            "target": target,
            "row_number": row_number,
            "outcome": "ignored",
            "reason": "row_not_found",
        }
    outcome = _detail_outcome(detail)
    result = {"target": target, "row_number": row_number, "outcome": outcome}
    if outcome == "ignored":
        result["reason"] = "infrastructure"
    return result


def _category_target_effect(target: str, details: list[dict]) -> dict:
    matched = [
        detail
        for detail in details
        if target in {detail["accepted_failure_category"], detail["candidate_failure_category"]}
    ]
    if not matched:
        return {"target": target, "outcome": "ignored", "reason": "no_matching_evidence", "row_numbers": []}
    row_numbers = [detail["row_number"] for detail in matched]
    if target in INFRASTRUCTURE_FAILURES:
        return {
            "target": target,
            "outcome": "ignored",
            "reason": "infrastructure",
            "row_numbers": row_numbers,
        }
    outcomes = [_detail_outcome(detail) for detail in matched]
    if "regressed" in outcomes:
        outcome = "regressed"
    elif "improved" in outcomes:
        outcome = "improved"
    else:
        outcome = "unchanged"
    return {"target": target, "outcome": outcome, "row_numbers": row_numbers}


def _detail_outcome(detail: dict) -> str:
    if _detail_has_infra(detail):
        return "ignored"
    delta = detail.get("business_delta", detail.get("type_delta", 0))
    if delta > 0:
        return "improved"
    if delta < 0:
        return "regressed"
    return "unchanged"


def _detail_has_infra(detail: dict) -> bool:
    categories = {detail["accepted_failure_category"], detail["candidate_failure_category"]}
    return bool(categories & INFRASTRUCTURE_FAILURES)


def _is_priority_mismatch(result: dict) -> bool:
    if result.get("reason") == "infrastructure":
        return True
    target = result.get("target")
    return isinstance(target, str) and target in SECONDARY_CODE_FAILURES
