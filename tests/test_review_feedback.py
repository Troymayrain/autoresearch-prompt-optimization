from openpyxl import Workbook

import json

from optimizer.review_feedback import build_review_feedback, write_review_feedback


def _review_workbook(path, rows):
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
            "review_group_key",
            "review_decision",
            "review_notes",
        ]
    )
    for row in rows:
        ws.append(row)
    wb.save(path)


def _feedback_failures():
    return {
        "task": "code",
        "feedback_set": "dev",
        "primary_groups": [
            {
                "key": "wrong_code_ocr_confusion",
                "failure_category": "wrong_code",
                "reason": "selected a code-like value with character-level OCR differences",
                "count": 1,
                "rows": [324],
                "examples": [{"row_number": 324, "expected": "F3", "actual": ["FB"], "failure_category": "wrong_code"}],
            }
        ],
        "secondary_groups": [
            {
                "key": "extra_code_output",
                "failure_category": "extra_code",
                "reason": "returned the expected code plus additional unmatched code output",
                "count": 2,
                "rows": [113, 91],
                "examples": [
                    {"row_number": 113, "expected": "ABC", "actual": ["ABC", "PIN"], "failure_category": "extra_code"},
                    {"row_number": 91, "expected": "DEF", "actual": ["DEF", "BAR"], "failure_category": "extra_code"},
                ],
            },
            {
                "key": "strict_code_cleanliness",
                "failure_category": "",
                "reason": "business match passed but strict code presentation still changed",
                "count": 1,
                "rows": [290],
                "examples": [{"row_number": 290, "expected": "Q0", "actual": ["Q-O"], "failure_category": ""}],
            },
        ],
    }


def test_build_review_feedback_filters_and_groups_prompt_fixable_rows(tmp_path):
    workbook = tmp_path / "feedback-review.xlsx"
    _review_workbook(
        workbook,
        [
            ["extra_code_output", 113, 10, "a.png", "ABC", "ABC\nPIN", "", "extra_code", "extra_code_security_pin", "prompt_fixable", "pin"],
            ["extra_code_output", 91, 10, "b.png", "DEF", "DEF\nBAR", "", "extra_code", "extra_code_barcode_receipt_number", "prompt_fixable", "barcode"],
            ["wrong_code_ocr_confusion", 324, 0, "c.png", "F3", "FB", "", "wrong_code", "", "prompt_fixable", "ocr"],
            ["strict_code_cleanliness", 290, 10, "d.png", "Q0", "Q-O", "", "", "", "image_unreadable", "bad image"],
            ["extra_code_output", 500, 10, "e.png", "GHI", "GHI\nPIN", "", "extra_code", "extra_code_security_pin", "prompt_fixable", "resolved"],
        ],
    )

    review = build_review_feedback(
        workbook,
        _feedback_failures(),
        dev_row_numbers=[91, 113, 290, 324, 500],
    )

    assert [group["key"] for group in review["active_groups"]] == [
        "wrong_code_ocr_confusion",
        "extra_code_security_pin",
        "extra_code_barcode_receipt_number",
    ]
    assert review["active_groups"][0]["rows"] == [324]
    assert review["active_groups"][1]["rows"] == [113]
    assert review["active_groups"][2]["rows"] == [91]
    assert review["excluded_rows"] == [
        {"row_number": 290, "group_key": "strict_code_cleanliness", "review_decision": "image_unreadable"}
    ]
    assert review["already_resolved_rows"] == [
        {"row_number": 500, "group_key": "extra_code_security_pin", "original_group_key": "extra_code_output"}
    ]
    assert review["mismatched_rows"] == []
    assert review["background_groups"]["secondary_groups"][0]["key"] == "extra_code_output"


def test_build_review_feedback_requires_review_group_key_for_extra_code_prompt_fixable(tmp_path):
    workbook = tmp_path / "feedback-review.xlsx"
    _review_workbook(
        workbook,
        [["extra_code_output", 113, 10, "a.png", "ABC", "ABC\nPIN", "", "extra_code", "", "prompt_fixable", "pin"]],
    )

    try:
        build_review_feedback(workbook, _feedback_failures(), dev_row_numbers=[113])
    except ValueError as exc:
        assert "review_group_key required for prompt_fixable extra_code_output rows: 113" in str(exc)
    else:
        raise AssertionError("expected missing review_group_key to fail")


def test_build_review_feedback_rejects_rows_outside_current_dev_set(tmp_path):
    workbook = tmp_path / "feedback-review.xlsx"
    _review_workbook(
        workbook,
        [["extra_code_output", 999, 10, "z.png", "ABC", "ABC\nPIN", "", "extra_code", "extra_code_security_pin", "prompt_fixable", "pin"]],
    )

    try:
        build_review_feedback(workbook, _feedback_failures(), dev_row_numbers=[113])
    except ValueError as exc:
        assert "review rows not found in current dev set: 999" in str(exc)
    else:
        raise AssertionError("expected missing dev row to fail")


def test_write_review_feedback_persists_review_overlay(tmp_path):
    payload = {
        "task": "code",
        "active_groups": [{"key": "extra_code_security_pin", "rows": [113]}],
        "already_resolved_rows": [{"row_number": 500}],
        "mismatched_rows": [],
    }

    write_review_feedback(tmp_path, payload)

    assert json.loads((tmp_path / "review-feedback.json").read_text()) == payload
