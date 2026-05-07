from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

BUSINESS_STRIP_RE = re.compile(r"[\n\r\t\v\f \u00A0\u3000-]+")


@dataclass(frozen=True)
class RowScore:
    expected_raw: str
    actual_raw: list[str]
    business_total: int
    business_correct: int
    strict_correct: int
    unmatched_expected: list[str]
    unmatched_actual: list[str]

    @property
    def business_accuracy(self) -> float:
        return 0.0 if self.business_total == 0 else round(self.business_correct / self.business_total * 100, 2)


@dataclass(frozen=True)
class ScoreSummary:
    business_total: int
    business_correct: int
    business_accuracy: float
    strict_correct: int
    strict_accuracy: float


def _to_text(value: object) -> str:
    return "" if value is None else str(value)


def normalize_business(value: object) -> str:
    stripped = BUSINESS_STRIP_RE.sub("", _to_text(value))
    return stripped.upper().replace("O", "0").replace("I", "1").replace("S", "5")


def normalize_strict(value: object) -> str:
    return BUSINESS_STRIP_RE.sub("", _to_text(value)).upper()


def split_codes(value: object) -> list[str]:
    return [part.strip() for part in _to_text(value).splitlines() if part.strip()]


def _match(expected_raw: Sequence[str], actual_raw: Sequence[str], normalizer) -> tuple[int, list[str], list[str]]:
    expected = [(item, normalizer(item)) for item in expected_raw]
    actual = [(item, normalizer(item)) for item in actual_raw]
    expected = [(raw, norm) for raw, norm in expected if norm]
    actual = [(raw, norm) for raw, norm in actual if norm]
    used_actual = [False] * len(actual)
    matched = [False] * len(expected)

    for i, (_, expected_norm) in enumerate(expected):
        for j, (_, actual_norm) in enumerate(actual):
            if not used_actual[j] and actual_norm == expected_norm:
                used_actual[j] = True
                matched[i] = True
                break

    for i, (_, expected_norm) in enumerate(expected):
        if matched[i]:
            continue
        for j, (_, actual_norm) in enumerate(actual):
            if not used_actual[j] and expected_norm in actual_norm:
                used_actual[j] = True
                matched[i] = True
                break

    unmatched_expected = [raw for (raw, _), ok in zip(expected, matched) if not ok]
    unmatched_actual = [raw for (raw, _), used in zip(actual, used_actual) if not used]
    return sum(1 for ok in matched if ok), unmatched_expected, unmatched_actual


def score_row(expected_raw: object, actual_codes: Sequence[object]) -> RowScore:
    expected = split_codes(expected_raw)
    actual = [code for item in actual_codes for code in split_codes(item)]
    if not expected:
        return RowScore(_to_text(expected_raw), actual, 0, 0, 0, [], actual)
    business_correct, unmatched_expected, unmatched_actual = _match(expected, actual, normalize_business)
    strict_correct, _, _ = _match(expected, actual, normalize_strict)
    return RowScore(
        expected_raw=_to_text(expected_raw),
        actual_raw=actual,
        business_total=len([item for item in expected if normalize_business(item)]),
        business_correct=business_correct,
        strict_correct=strict_correct,
        unmatched_expected=unmatched_expected,
        unmatched_actual=unmatched_actual,
    )


def aggregate_scores(rows: Iterable[RowScore]) -> ScoreSummary:
    scored = list(rows)
    total = sum(row.business_total for row in scored)
    business_correct = sum(row.business_correct for row in scored)
    strict_correct = sum(row.strict_correct for row in scored)
    return ScoreSummary(
        business_total=total,
        business_correct=business_correct,
        business_accuracy=0.0 if total == 0 else round(business_correct / total * 100, 2),
        strict_correct=strict_correct,
        strict_accuracy=0.0 if total == 0 else round(strict_correct / total * 100, 2),
    )
