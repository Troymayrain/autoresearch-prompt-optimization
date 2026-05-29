from __future__ import annotations

from dataclasses import dataclass

from optimizer.dataset import TaskName
from optimizer.scoring import ScoreSummary, TypeScoreSummary


@dataclass(frozen=True)
class RegressionGateCheck:
    name: str
    passed: bool
    accepted: int | float
    candidate: int | float
    reason: str


@dataclass(frozen=True)
class RegressionGateDecision:
    task: TaskName
    passed: bool
    checks: tuple[RegressionGateCheck, ...]
    reason: str


def _not_decreased(metric: str, accepted: float, candidate: float) -> RegressionGateCheck:
    passed = candidate >= accepted
    return RegressionGateCheck(
        name=f"{metric}_not_decreased",
        passed=passed,
        accepted=accepted,
        candidate=candidate,
        reason="passed" if passed else f"{metric} decreased from {accepted} to {candidate}",
    )


def _not_shrunk(metric: str, accepted: int, candidate: int) -> RegressionGateCheck:
    passed = candidate >= accepted
    return RegressionGateCheck(
        name=f"{metric}_not_shrunk",
        passed=passed,
        accepted=accepted,
        candidate=candidate,
        reason="passed" if passed else f"{metric} shrank from {accepted} to {candidate}",
    )


def _not_increased(metric: str, accepted: int, candidate: int) -> RegressionGateCheck:
    passed = candidate <= accepted
    return RegressionGateCheck(
        name=f"{metric}_not_increased",
        passed=passed,
        accepted=accepted,
        candidate=candidate,
        reason="passed" if passed else f"{metric} increased from {accepted} to {candidate}",
    )


def _decision(task: TaskName, checks: tuple[RegressionGateCheck, ...]) -> RegressionGateDecision:
    failures = [check.reason for check in checks if not check.passed]
    return RegressionGateDecision(
        task=task,
        passed=not failures,
        checks=checks,
        reason="passed" if not failures else "; ".join(failures),
    )


def compare_regression_scores(
    task: TaskName,
    accepted: ScoreSummary | TypeScoreSummary,
    candidate: ScoreSummary | TypeScoreSummary,
) -> RegressionGateDecision:
    if task == "code":
        accepted_code = accepted
        candidate_code = candidate
        return _decision(
            task,
            (
                _not_decreased(
                    "business_accuracy",
                    accepted_code.business_accuracy,
                    candidate_code.business_accuracy,
                ),
                _not_shrunk(
                    "business_total",
                    accepted_code.business_total,
                    candidate_code.business_total,
                ),
            ),
        )

    if task == "type":
        accepted_type = accepted
        candidate_type = candidate
        return _decision(
            task,
            (
                _not_decreased(
                    "type_accuracy",
                    accepted_type.type_accuracy,
                    candidate_type.type_accuracy,
                ),
                _not_increased(
                    "not_evaluable_count",
                    accepted_type.not_evaluable_count,
                    candidate_type.not_evaluable_count,
                ),
                _not_shrunk(
                    "type_total",
                    accepted_type.type_total,
                    candidate_type.type_total,
                ),
            ),
        )

    raise ValueError(f"unsupported task: {task}")
