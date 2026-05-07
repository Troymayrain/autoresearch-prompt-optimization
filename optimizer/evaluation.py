from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Sequence

from optimizer.dataset import Sample
from optimizer.node_runner import OcrPayload
from optimizer.scoring import RowScore, score_row


@dataclass(frozen=True)
class EvaluationResult:
    sample: Sample
    ocr_response: dict[str, Any]
    actual_numbers: list[str]
    image_status: str
    row_score: RowScore
    failure_category: str

    @classmethod
    def from_ocr_response(cls, sample: Sample, response: dict[str, Any]) -> "EvaluationResult":
        data = response.get("data") if isinstance(response, dict) else []
        actual_numbers = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("number"):
                    actual_numbers.append(str(item["number"]))
                elif isinstance(item, str) and item:
                    actual_numbers.append(item)
        image_status_values = response.get("imageStatus") if isinstance(response, dict) else []
        image_status = image_status_values[0] if image_status_values else ""
        row_score = score_row(sample.expected_raw, actual_numbers)
        return cls(
            sample=sample,
            ocr_response=response,
            actual_numbers=actual_numbers,
            image_status=str(image_status or ""),
            row_score=row_score,
            failure_category=_failure_category(
                sample,
                response,
                actual_numbers,
                row_score,
                str(image_status or ""),
            ),
        )


def build_payload(sample: Sample) -> OcrPayload:
    return OcrPayload(image=sample.card_image, origin=sample.origin, channel="TB", type="complex")


def _failure_category(
    sample: Sample,
    response: dict[str, Any],
    actual_numbers: list[str],
    row_score: RowScore,
    image_status: str,
) -> str:
    if not sample.scoreable:
        return ""
    if image_status in {"error-download", "error-small", "error-upload"}:
        return "download_error"
    if image_status == "no-card":
        return "no_card"
    if response.get("status") not in {200, "200"}:
        return "ai_error"
    if row_score.business_total and row_score.business_correct == row_score.business_total:
        return ""
    if not actual_numbers:
        return "missing_code"
    if row_score.unmatched_actual:
        return "extra_code"
    return "wrong_code"


async def evaluate_samples(samples: Sequence[Sample], runner, concurrency: int) -> list[EvaluationResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(sample: Sample) -> EvaluationResult:
        async with semaphore:
            response = await runner.run_one(build_payload(sample))
            return EvaluationResult.from_ocr_response(sample, response)

    return list(await asyncio.gather(*(run(sample) for sample in samples)))
