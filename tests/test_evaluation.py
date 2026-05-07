import pytest

from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult, build_payload, evaluate_samples


class FakeRunner:
    async def run_one(self, payload):
        if payload.image == "missing.png":
            return {"status": 200, "data": [], "imageStatus": ["ok"]}
        return {"status": 200, "data": [{"type": "E-codes", "number": payload.image}], "imageStatus": ["ok"]}


def test_build_payload_uses_card_type_shape():
    sample = Sample(row_number=2, card_image="amazon_aws/card_img_tbay/a.png", origin=10, expected_raw="ABC", scoreable=True)

    payload = build_payload(sample)

    assert payload.image == "amazon_aws/card_img_tbay/a.png"
    assert payload.origin == 10
    assert payload.channel == "TB"
    assert payload.type == "complex"


def test_evaluation_result_extracts_actual_numbers():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "A123", True),
        {"status": 200, "data": [{"type": "E-codes", "number": "A-123"}], "imageStatus": ["ok"]},
    )

    assert item.actual_numbers == ["A-123"]
    assert item.row_score.business_correct == 1
    assert item.failure_category == ""


def test_evaluation_classifies_missing_code():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "missing.png", 0, "ABC", True),
        {"status": 200, "data": [], "imageStatus": ["ok"]},
    )

    assert item.failure_category == "missing_code"


@pytest.mark.asyncio
async def test_evaluate_samples_uses_concurrency():
    samples = [
        Sample(2, "ABC", 0, "ABC", True),
        Sample(3, "missing.png", 0, "XYZ", True),
    ]

    results = await evaluate_samples(samples, FakeRunner(), concurrency=2)

    assert [r.sample.row_number for r in results] == [2, 3]
    assert results[0].row_score.business_correct == 1
    assert results[1].failure_category == "missing_code"
