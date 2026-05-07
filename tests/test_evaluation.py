import pytest

from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult, build_payload, evaluate_samples
from optimizer.node_runner import OcrRunnerError


class FakeRunner:
    async def run_one(self, payload):
        if payload.image == "missing.png":
            return {"status": 200, "data": [], "imageStatus": ["ok"]}
        return {"status": 200, "data": [{"type": "E-codes", "number": payload.image}], "imageStatus": ["ok"]}


class SometimesFailingRunner:
    async def run_one(self, payload):
        if payload.image == "bad.png":
            raise OcrRunnerError("boom")
        return {"status": 200, "data": [{"number": payload.image}], "imageStatus": ["ok"]}


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


@pytest.mark.parametrize(
    ("response", "category"),
    [
        ({"status": 200, "data": [], "imageStatus": ["error-download"]}, "download_error"),
        ({"status": 500, "data": [], "imageStatus": ["ok"]}, "ai_error"),
    ],
)
def test_infrastructure_failures_are_excluded_from_row_score(response, category):
    item = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "ABC", True),
        response,
    )

    assert item.failure_category == category
    assert item.row_score.business_total == 0
    assert item.row_score.strict_correct == 0


def test_wrong_code_takes_priority_over_extra_code():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "AAA", True),
        {"status": 200, "data": [{"number": "BBB"}], "imageStatus": ["ok"]},
    )

    assert item.failure_category == "wrong_code"


def test_extra_code_when_expected_codes_all_match():
    item = EvaluationResult.from_ocr_response(
        Sample(2, "a.png", 0, "AAA", True),
        {"status": 200, "data": [{"number": "AAA\nBBB"}], "imageStatus": ["ok"]},
    )

    assert item.failure_category == "extra_code"


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


@pytest.mark.asyncio
async def test_evaluate_samples_converts_runner_errors_to_parse_error():
    samples = [
        Sample(2, "bad.png", 0, "ABC", True),
        Sample(3, "OK", 0, "OK", True),
    ]

    results = await evaluate_samples(samples, SometimesFailingRunner(), concurrency=2)

    assert [result.sample.row_number for result in results] == [2, 3]
    assert results[0].failure_category == "parse_error"
    assert results[0].row_score.business_total == 0
    assert results[1].failure_category == ""
