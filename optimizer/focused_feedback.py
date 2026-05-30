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


def build_failed_strategy_memory(
    focused_group: str,
    strategy_summary: str,
    target_rows: Sequence[int],
    dev_delta: dict,
    prompt_diff: str,
    line_limit: int = 8,
) -> dict | None:
    rows = _row_numbers(target_rows)
    if not rows:
        return None

    regressed_rows = _regressed_rows(dev_delta)
    target_outcomes = _target_outcomes(dev_delta, rows)
    if regressed_rows or "regressed" in target_outcomes:
        outcome = "regressed"
    elif "improved" in target_outcomes:
        return None
    else:
        outcome = "unchanged"

    return {
        "focused_group": focused_group,
        "strategy_summary": strategy_summary,
        "target_rows": rows,
        "outcome": outcome,
        "regressed_rows": regressed_rows,
        "prompt_diff_summary": _prompt_diff_summary(prompt_diff, line_limit),
    }


def focused_target_improved(dev_delta: dict, target_rows: Sequence[int]) -> bool:
    return "improved" in _target_outcomes(dev_delta, _row_numbers(target_rows))


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


def _regressed_rows(dev_delta: dict) -> list[int]:
    rows = _row_numbers(
        row.get("row_number")
        for row in dev_delta.get("regressed_business_rows", [])
        if isinstance(row, dict)
    )
    rows.extend(
        row.get("row_number")
        for row in dev_delta.get("target_failures_effect", {}).get("row_targets", [])
        if isinstance(row, dict) and row.get("outcome") == "regressed"
    )
    return _unique_rows(rows)


def _target_outcomes(dev_delta: dict, target_rows: Sequence[int]) -> list[str]:
    target_set = set(target_rows)
    return [
        str(row.get("outcome"))
        for row in dev_delta.get("target_failures_effect", {}).get("row_targets", [])
        if isinstance(row, dict) and _coerce_int(row.get("row_number")) in target_set
    ]


def _prompt_diff_summary(prompt_diff: str, line_limit: int) -> dict:
    added_lines = []
    removed_lines = []
    for raw_line in prompt_diff.splitlines():
        if raw_line.startswith("+++") or raw_line.startswith("---"):
            continue
        if raw_line.startswith("+"):
            _append_limited(added_lines, raw_line[1:], line_limit)
        elif raw_line.startswith("-"):
            _append_limited(removed_lines, raw_line[1:], line_limit)
    return {"added_lines": added_lines, "removed_lines": removed_lines}


def _append_limited(lines: list[str], value: str, limit: int) -> None:
    text = value.strip()
    if text and len(lines) < limit:
        lines.append(text)


def _row_numbers(values: Sequence[object]) -> list[int]:
    rows = [_coerce_int(value) for value in values]
    return [row for row in rows if row is not None]


def _unique_rows(rows: Sequence[int]) -> list[int]:
    seen = set()
    result = []
    for row in rows:
        if row not in seen:
            seen.add(row)
            result.append(row)
    return result


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
