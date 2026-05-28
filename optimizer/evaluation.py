from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from optimizer.dataset import Sample, TaskName
from optimizer.node_runner import OcrPayload, OcrRunnerError
from optimizer.scoring import RowScore, TypeRowScore, score_row, score_type_row

INFRASTRUCTURE_FAILURES = {"download_error", "decrypt_error", "ai_error", "parse_error"}


@dataclass(frozen=True)
class EvaluationResult:
    sample: Sample
    ocr_response: dict[str, Any]
    actual_numbers: list[str]
    actual_types: list[str]
    image_status: str
    row_score: RowScore
    type_score: TypeRowScore | None
    failure_category: str

    @classmethod
    def from_ocr_response(
        cls,
        sample: Sample,
        response: dict[str, Any],
        task: TaskName = "code",
    ) -> "EvaluationResult":
        data = response.get("data") if isinstance(response, dict) else []
        actual_numbers = []
        actual_types = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    if item.get("number"):
                        actual_numbers.append(str(item["number"]))
                    if item.get("type"):
                        actual_types.append(str(item["type"]))
                elif isinstance(item, str) and item:
                    actual_numbers.append(item)
        image_status_values = response.get("imageStatus") if isinstance(response, dict) else []
        image_status = image_status_values[0] if image_status_values else ""
        row_score = score_row(sample.expected_raw, actual_numbers)
        failure_category = _code_failure_category(
            sample,
            response,
            actual_numbers,
            row_score,
            str(image_status or ""),
        )
        if failure_category in INFRASTRUCTURE_FAILURES:
            row_score = _excluded_row_score(sample.expected_raw, actual_numbers)
        type_score = None
        if task == "type":
            failure_category, type_score = _type_failure_category(
                sample,
                response,
                actual_types,
                str(image_status or ""),
            )
        return cls(
            sample=sample,
            ocr_response=response,
            actual_numbers=actual_numbers,
            actual_types=actual_types,
            image_status=str(image_status or ""),
            row_score=row_score,
            type_score=type_score,
            failure_category=failure_category,
        )


def build_payload(sample: Sample) -> OcrPayload:
    return OcrPayload(image=sample.card_image, origin=sample.origin, channel="TB", type="complex")


def _excluded_row_score(expected_raw: object, actual_numbers: list[str]) -> RowScore:
    return RowScore("" if expected_raw is None else str(expected_raw), actual_numbers, 0, 0, 0, [], actual_numbers)


def _code_failure_category(
    sample: Sample,
    response: dict[str, Any],
    actual_numbers: list[str],
    row_score: RowScore,
    image_status: str,
) -> str:
    if not sample.scoreable:
        return ""
    if response.get("status") == "parse_error":
        return "parse_error"
    if image_status in {"error-download", "error-small", "error-upload"}:
        return "download_error"
    if image_status in {"error-decrypt", "decrypt_error"}:
        return "decrypt_error"
    if image_status == "no-card":
        return "no_card"
    if response.get("status") not in {200, "200"}:
        return "ai_error"
    if row_score.business_total and row_score.business_correct == row_score.business_total:
        return "extra_code" if row_score.unmatched_actual else ""
    if not actual_numbers:
        return "missing_code"
    if row_score.unmatched_expected:
        return "wrong_code"
    if row_score.unmatched_actual:
        return "extra_code"
    return ""


def _type_failure_category(
    sample: Sample,
    response: dict[str, Any],
    actual_types: list[str],
    image_status: str,
) -> tuple[str, TypeRowScore]:
    infrastructure_failure = _infrastructure_failure(response, image_status)
    if infrastructure_failure:
        return "not_evaluable", TypeRowScore(
            sample.expected_raw,
            actual_types,
            0,
            0,
            infrastructure_failure,
        )

    type_score = score_type_row(sample.expected_raw, actual_types)
    if type_score.not_evaluable_reason:
        return "not_evaluable", type_score
    if type_score.type_correct != type_score.type_total:
        return "type_mismatch", type_score
    return "", type_score


def _infrastructure_failure(response: dict[str, Any], image_status: str) -> str:
    if response.get("status") == "parse_error":
        return "parse_error"
    if image_status in {"error-download", "error-small", "error-upload"}:
        return "download_error"
    if image_status in {"error-decrypt", "decrypt_error"}:
        return "decrypt_error"
    if response.get("status") not in {200, "200"}:
        return "ai_error"
    return ""


async def evaluate_samples(
    samples: Sequence[Sample],
    runner,
    concurrency: int,
    task: TaskName = "code",
) -> list[EvaluationResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(sample: Sample) -> EvaluationResult:
        async with semaphore:
            try:
                response = await runner.run_one(build_payload(sample))
            except OcrRunnerError as exc:
                response = {"status": "parse_error", "error": str(exc), "data": [], "imageStatus": []}
            except Exception as exc:
                response = {"status": "parse_error", "error": str(exc), "data": [], "imageStatus": []}
            return EvaluationResult.from_ocr_response(sample, response, task)

    return list(await asyncio.gather(*(run(sample) for sample in samples)))
