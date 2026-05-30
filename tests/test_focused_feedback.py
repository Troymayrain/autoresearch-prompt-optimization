from optimizer.focused_feedback import build_failed_strategy_memory, select_focused_group


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


def test_build_failed_strategy_memory_records_regression():
    entry = build_failed_strategy_memory(
        focused_group="wrong_code_ocr_confusion",
        strategy_summary="tighten B/8 and W/M reading",
        target_rows=[92, 411],
        dev_delta={
            "regressed_business_rows": [
                {"row_number": 92},
                {"row_number": 411},
            ],
            "target_failures_effect": {
                "row_targets": [
                    {"row_number": 92, "outcome": "regressed"},
                    {"row_number": 411, "outcome": "unchanged"},
                ],
            },
        },
        prompt_diff="+added rule\n-context line\n+another rule\n",
    )

    assert entry == {
        "focused_group": "wrong_code_ocr_confusion",
        "strategy_summary": "tighten B/8 and W/M reading",
        "target_rows": [92, 411],
        "outcome": "regressed",
        "regressed_rows": [92, 411],
        "prompt_diff_summary": {
            "added_lines": ["added rule", "another rule"],
            "removed_lines": ["context line"],
        },
    }


def test_build_failed_strategy_memory_records_unchanged_targets():
    entry = build_failed_strategy_memory(
        focused_group="no_card_false_negative",
        strategy_summary="allow isolated no-card codes",
        target_rows=[116],
        dev_delta={
            "persistent_business_failure_rows": [{"row_number": 116}],
            "target_failures_effect": {
                "row_targets": [{"row_number": 116, "outcome": "unchanged"}],
            },
        },
        prompt_diff="+allow cropped code\n",
    )

    assert entry["outcome"] == "unchanged"
    assert entry["regressed_rows"] == []
    assert entry["target_rows"] == [116]


def test_build_failed_strategy_memory_ignores_improved_attempts():
    entry = build_failed_strategy_memory(
        focused_group="wrong_code_selected_non_redeemable_number",
        strategy_summary="prefer alphanumeric code",
        target_rows=[330],
        dev_delta={
            "improved_business_rows": [{"row_number": 330}],
            "target_failures_effect": {
                "row_targets": [{"row_number": 330, "outcome": "improved"}],
            },
        },
        prompt_diff="+prefer alphanumeric\n",
    )

    assert entry is None
