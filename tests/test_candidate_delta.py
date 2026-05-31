from optimizer.candidate_delta import compare_candidate_delta, summarize_candidate_delta
from optimizer.dataset import Sample
from optimizer.evaluation import EvaluationResult


def _code_result(row, expected, actual, *, status=200, image_status="ok"):
    return EvaluationResult.from_ocr_response(
        Sample(row, f"{row}.png", 0, expected, True),
        {
            "status": status,
            "data": [{"number": item} for item in actual],
            "imageStatus": [image_status],
        },
        task="code",
    )


def _type_result(row, expected, actual, *, status=200, image_status="ok"):
    return EvaluationResult.from_ocr_response(
        Sample(row, f"{row}.png", 0, expected, True),
        {
            "status": status,
            "data": [{"type": item} for item in actual],
            "imageStatus": [image_status],
        },
        task="type",
    )


def test_code_delta_groups_business_and_secondary_changes():
    accepted = [
        _code_result(2, "ABC", ["MISS"]),
        _code_result(3, "AAA\nBBB", ["AAA", "BBB"]),
        _code_result(4, "CCC", ["MISS"]),
        _code_result(5, "OIS", ["015"]),
        _code_result(6, "DDD", ["DDD"]),
    ]
    candidate = [
        _code_result(2, "ABC", ["ABC"]),
        _code_result(3, "AAA\nBBB", ["AAA"]),
        _code_result(4, "CCC", ["WRONG"]),
        _code_result(5, "OIS", ["OIS"]),
        _code_result(6, "DDD", ["DDD", "EXTRA"]),
    ]

    delta = compare_candidate_delta("code", accepted, candidate)

    assert delta["primary_metric"] == {
        "name": "business_code_match",
        "accepted_correct": 4,
        "candidate_correct": 4,
        "total": 6,
        "delta": 0,
    }
    assert delta["secondary_metric"] == {
        "name": "strict_code_match",
        "accepted_correct": 3,
        "candidate_correct": 4,
        "total": 6,
        "delta": 1,
    }
    assert [row["row_number"] for row in delta["improved_business_rows"]] == [2]
    assert delta["regressed_business_rows"] == [
        {
            "row_number": 3,
            "expected": "AAA\nBBB",
            "accepted_actual": ["AAA", "BBB"],
            "candidate_actual": ["AAA"],
            "accepted_failure_category": "",
            "candidate_failure_category": "wrong_code",
            "business_total": 2,
            "accepted_business_correct": 2,
            "candidate_business_correct": 1,
            "business_delta": -1,
            "accepted_strict_correct": 2,
            "candidate_strict_correct": 1,
            "strict_delta": -1,
        }
    ]
    assert [row["row_number"] for row in delta["persistent_business_failure_rows"]] == [4]
    assert [row["row_number"] for row in delta["strict_only_changed_rows"]] == [5, 6]


def test_code_delta_separates_infra_and_keeps_no_card_business_relevant():
    accepted = [
        _code_result(2, "ABC", ["MISS"]),
        _code_result(3, "AAA", ["AAA"]),
    ]
    candidate = [
        _code_result(2, "ABC", [], image_status="no-card"),
        _code_result(3, "AAA", [], image_status="error-download"),
    ]

    delta = compare_candidate_delta("code", accepted, candidate)

    assert [row["row_number"] for row in delta["persistent_business_failure_rows"]] == [2]
    assert [row["row_number"] for row in delta["infra_failure_rows"]] == [3]
    assert delta["persistent_business_failure_rows"][0]["candidate_failure_category"] == "no_card"
    assert delta["infra_failure_rows"][0]["candidate_failure_category"] == "download_error"


def test_type_delta_uses_type_groups_without_code_categories():
    accepted = [
        _type_result(2, "Physics", ["E-codes"]),
        _type_result(3, "Physics", ["Physics"]),
        _type_result(4, "E-codes", ["Physics"]),
        _type_result(5, "Physics", []),
    ]
    candidate = [
        _type_result(2, "Physics", ["Physics"]),
        _type_result(3, "Physics", ["E-codes"]),
        _type_result(4, "E-codes", ["Physics"]),
        _type_result(5, "Physics", []),
    ]

    delta = compare_candidate_delta("type", accepted, candidate)

    assert delta["primary_metric"] == {
        "name": "card_type_match",
        "accepted_correct": 1,
        "candidate_correct": 1,
        "total": 3,
        "delta": 0,
    }
    assert "improved_business_rows" not in delta
    assert [row["row_number"] for row in delta["improved_type_rows"]] == [2]
    assert [row["row_number"] for row in delta["regressed_type_rows"]] == [3]
    assert [row["row_number"] for row in delta["persistent_type_failure_rows"]] == [4]
    assert [row["row_number"] for row in delta["not_evaluable_rows"]] == [5]


def test_target_failures_effect_reports_row_outcomes():
    accepted = [
        _code_result(2, "ABC", ["MISS"]),
        _code_result(3, "AAA", ["AAA"]),
        _code_result(4, "CCC", ["MISS"]),
        _code_result(5, "DDD", ["DDD"]),
    ]
    candidate = [
        _code_result(2, "ABC", ["ABC"]),
        _code_result(3, "AAA", ["MISS"]),
        _code_result(4, "CCC", ["WRONG"]),
        _code_result(5, "DDD", [], image_status="error-download"),
    ]

    delta = compare_candidate_delta("code", accepted, candidate, target_failures=["2", "row 3", "4", "5", "99"])

    assert delta["target_failures_effect"]["row_targets"] == [
        {"target": "2", "row_number": 2, "outcome": "improved"},
        {"target": "row 3", "row_number": 3, "outcome": "regressed"},
        {"target": "4", "row_number": 4, "outcome": "unchanged"},
        {"target": "5", "row_number": 5, "outcome": "ignored", "reason": "infrastructure"},
        {"target": "99", "row_number": 99, "outcome": "ignored", "reason": "row_not_found"},
    ]


def test_target_failures_effect_summarizes_categories_and_priority_mismatch():
    accepted = [
        _code_result(2, "ABC", []),
        _code_result(3, "AAA", ["AAA"]),
        _code_result(4, "CCC", ["CCC"]),
        _code_result(5, "DDD", ["DDD"]),
    ]
    candidate = [
        _code_result(2, "ABC", ["ABC"]),
        _code_result(3, "AAA", ["MISS"]),
        _code_result(4, "CCC", ["CCC", "EXTRA"]),
        _code_result(5, "DDD", [], image_status="error-download"),
    ]

    delta = compare_candidate_delta(
        "code",
        accepted,
        candidate,
        target_failures=["missing_code", "wrong_code", "extra_code", "download_error"],
    )

    assert delta["target_failures_effect"]["category_targets"] == [
        {"target": "missing_code", "outcome": "improved", "row_numbers": [2]},
        {"target": "wrong_code", "outcome": "regressed", "row_numbers": [3]},
        {"target": "extra_code", "outcome": "unchanged", "row_numbers": [4]},
        {"target": "download_error", "outcome": "ignored", "reason": "infrastructure", "row_numbers": [5]},
    ]
    assert delta["target_priority_mismatch"] == ["extra_code", "download_error"]


def test_reviewed_target_effect_reports_resolution_without_redefining_target_failures():
    accepted = [
        _code_result(113, "ABC", ["ABC", "PIN"]),
        _code_result(91, "DEF", ["DEF", "BAR"]),
        _code_result(324, "F3", ["FB"]),
        _code_result(411, "GOOD", ["GOOD"]),
        _code_result(500, "MISS", [], image_status="error-download"),
    ]
    candidate = [
        _code_result(113, "ABC", ["ABC"]),
        _code_result(91, "DEF", ["DEF", "BAR"]),
        _code_result(324, "F3", ["F3"]),
        _code_result(411, "GOOD", ["BAD"]),
        _code_result(500, "MISS", [], image_status="error-download"),
    ]

    delta = compare_candidate_delta(
        "code",
        accepted,
        candidate,
        target_failures=["extra_code"],
        reviewed_targets=[
            {"key": "extra_code_security_pin", "rows": [113]},
            {"key": "extra_code_barcode_receipt_number", "rows": [91]},
            {"key": "wrong_code_ocr_confusion", "rows": [324, 411, 500, 999]},
        ],
    )

    assert delta["target_failures_effect"]["category_targets"] == [
        {"target": "extra_code", "outcome": "unchanged", "row_numbers": [113, 91]}
    ]
    assert delta["reviewed_target_effect"]["summary"] == {
        "resolved": 2,
        "unchanged": 1,
        "regressed": 1,
        "ignored": 2,
    }
    assert delta["reviewed_target_effect"]["row_targets"] == [
        {
            "row_number": 113,
            "review_group_key": "extra_code_security_pin",
            "outcome": "resolved",
            "accepted_failure_category": "extra_code",
            "candidate_failure_category": "",
            "accepted_actual": ["ABC", "PIN"],
            "candidate_actual": ["ABC"],
        },
        {
            "row_number": 91,
            "review_group_key": "extra_code_barcode_receipt_number",
            "outcome": "unchanged",
            "accepted_failure_category": "extra_code",
            "candidate_failure_category": "extra_code",
            "accepted_actual": ["DEF", "BAR"],
            "candidate_actual": ["DEF", "BAR"],
        },
        {
            "row_number": 324,
            "review_group_key": "wrong_code_ocr_confusion",
            "outcome": "resolved",
            "accepted_failure_category": "wrong_code",
            "candidate_failure_category": "",
            "accepted_actual": ["FB"],
            "candidate_actual": ["F3"],
        },
        {
            "row_number": 411,
            "review_group_key": "wrong_code_ocr_confusion",
            "outcome": "regressed",
            "accepted_failure_category": "",
            "candidate_failure_category": "wrong_code",
            "accepted_actual": ["GOOD"],
            "candidate_actual": ["BAD"],
        },
        {
            "row_number": 500,
            "review_group_key": "wrong_code_ocr_confusion",
            "outcome": "ignored",
            "reason": "infrastructure",
            "accepted_failure_category": "download_error",
            "candidate_failure_category": "download_error",
            "accepted_actual": [],
            "candidate_actual": [],
        },
        {
            "row_number": 999,
            "review_group_key": "wrong_code_ocr_confusion",
            "outcome": "ignored",
            "reason": "row_not_found",
            "accepted_failure_category": "",
            "candidate_failure_category": "",
            "accepted_actual": [],
            "candidate_actual": [],
        },
    ]


def test_candidate_delta_summary_bounds_actual_values_without_mutating_delta():
    accepted = [_code_result(2, "ABC", ["MISS"])]
    candidate = [_code_result(2, "ABC", ["ABCDE12345"])]
    delta = compare_candidate_delta("code", accepted, candidate)

    summary = summarize_candidate_delta(delta, value_limit=5)

    assert summary["improved_business_rows"] == [
        {
            "row_number": 2,
            "accepted_failure_category": "wrong_code",
            "candidate_failure_category": "",
            "business_delta": 1,
            "strict_delta": 1,
            "accepted_actual": ["MISS"],
            "candidate_actual": ["ABCDE..."],
        }
    ]
    assert delta["improved_business_rows"][0]["candidate_actual"] == ["ABCDE12345"]


def test_candidate_delta_summary_includes_reviewed_target_effect():
    accepted = [_code_result(113, "ABC", ["ABC", "PIN"])]
    candidate = [_code_result(113, "ABC", ["ABC"])]
    delta = compare_candidate_delta(
        "code",
        accepted,
        candidate,
        reviewed_targets=[{"key": "extra_code_security_pin", "rows": [113]}],
    )

    summary = summarize_candidate_delta(delta)

    assert summary["reviewed_target_effect"]["summary"] == {
        "resolved": 1,
        "unchanged": 0,
        "regressed": 0,
        "ignored": 0,
    }
