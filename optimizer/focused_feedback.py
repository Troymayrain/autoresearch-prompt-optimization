from __future__ import annotations

from typing import Sequence

PRIMARY_GROUP_PRIORITY = (
    "wrong_code_selected_non_redeemable_number",
    "wrong_code_ocr_confusion",
    "no_card_false_negative",
)
FAILED_OUTCOMES = {"unchanged", "regressed"}


def select_focused_group(
    feedback_failures: dict,
    attempt_history: Sequence[dict] | None = None,
) -> dict | None:
    attempts = list(attempt_history or [])
    groups = _ordered_primary_groups(feedback_failures)
    for group in groups:
        key = str(group.get("key", "")).strip()
        rows = group.get("rows", [])
        if not key or not rows:
            continue
        if _has_failed_attempt(key, attempts):
            continue
        if _improvement_count(key, attempts) > 1:
            continue
        return {"key": key, "rows": list(rows)}
    return None


def _ordered_primary_groups(feedback_failures: dict) -> list[dict]:
    groups = [
        group
        for group in feedback_failures.get("primary_groups", [])
        if isinstance(group, dict)
    ]
    by_key = {str(group.get("key", "")): group for group in groups}
    ordered = [by_key[key] for key in PRIMARY_GROUP_PRIORITY if key in by_key]
    ordered.extend(
        group
        for group in groups
        if str(group.get("key", "")) not in PRIMARY_GROUP_PRIORITY
    )
    return ordered


def _has_failed_attempt(group_key: str, attempts: Sequence[dict]) -> bool:
    return any(
        attempt.get("focused_group") == group_key
        and attempt.get("outcome") in FAILED_OUTCOMES
        for attempt in attempts
    )


def _improvement_count(group_key: str, attempts: Sequence[dict]) -> int:
    return sum(
        1
        for attempt in attempts
        if attempt.get("focused_group") == group_key
        and attempt.get("outcome") == "improved"
    )
