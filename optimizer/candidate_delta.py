from __future__ import annotations

from typing import Sequence

from optimizer.dataset import TaskName
from optimizer.evaluation import EvaluationResult, INFRASTRUCTURE_FAILURES
from optimizer.scoring import aggregate_scores, aggregate_type_scores


def compare_candidate_delta(
    task: TaskName,
    accepted: Sequence[EvaluationResult],
    candidate: Sequence[EvaluationResult],
) -> dict:
    if task == "type":
        return _type_delta(accepted, candidate)
    return _code_delta(accepted, candidate)


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
    return "extra_code" in {accepted.failure_category, candidate.failure_category}


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
