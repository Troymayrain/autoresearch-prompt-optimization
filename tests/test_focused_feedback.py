from optimizer.focused_feedback import select_focused_group


def test_select_focused_group_uses_fixed_primary_priority():
    feedback = {
        "primary_groups": [
            {"key": "no_card_false_negative", "rows": [116]},
            {"key": "wrong_code_ocr_confusion", "rows": [324]},
            {"key": "wrong_code_selected_non_redeemable_number", "rows": [330]},
        ],
        "secondary_groups": [
            {"key": "extra_code_output", "rows": [113]},
        ],
    }

    group = select_focused_group(feedback)

    assert group == {"key": "wrong_code_selected_non_redeemable_number", "rows": [330]}


def test_select_focused_group_skips_failed_groups_and_secondary_groups():
    feedback = {
        "primary_groups": [
            {"key": "wrong_code_selected_non_redeemable_number", "rows": [330]},
            {"key": "wrong_code_ocr_confusion", "rows": [324]},
        ],
        "secondary_groups": [
            {"key": "extra_code_output", "rows": [113]},
        ],
    }

    group = select_focused_group(
        feedback,
        attempt_history=[
            {"focused_group": "wrong_code_selected_non_redeemable_number", "outcome": "unchanged"},
        ],
    )

    assert group == {"key": "wrong_code_ocr_confusion", "rows": [324]}


def test_select_focused_group_allows_one_follow_up_after_improvement():
    feedback = {
        "primary_groups": [
            {"key": "wrong_code_selected_non_redeemable_number", "rows": [330]},
            {"key": "wrong_code_ocr_confusion", "rows": [324]},
        ],
        "secondary_groups": [],
    }

    first_follow_up = select_focused_group(
        feedback,
        attempt_history=[
            {"focused_group": "wrong_code_selected_non_redeemable_number", "outcome": "improved"},
        ],
    )
    after_follow_up = select_focused_group(
        feedback,
        attempt_history=[
            {"focused_group": "wrong_code_selected_non_redeemable_number", "outcome": "improved"},
            {"focused_group": "wrong_code_selected_non_redeemable_number", "outcome": "improved"},
        ],
    )

    assert first_follow_up == {
        "key": "wrong_code_selected_non_redeemable_number",
        "rows": [330],
    }
    assert after_follow_up == {"key": "wrong_code_ocr_confusion", "rows": [324]}
