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


def normalize_business(value: object) -> str:
    stripped = BUSINESS_STRIP_RE.sub("", str(value or ""))
    return stripped.upper().replace("O", "0").replace("I", "1").replace("S", "5")


def normalize_strict(value: object) -> str:
    return BUSINESS_STRIP_RE.sub("", str(value or "")).upper()


def split_codes(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def _match(expected_raw: Sequence[str], actual_raw: Sequence[str], normalizer) -> tuple[int, list[str], list[str]]:
    expected_norm = [normalizer(item) for item in expected_raw if normalizer(item)]
    actual_norm = [normalizer(item) for item in actual_raw if normalizer(item)]
    used_actual = [False] * len(actual_norm)
    matched = [False] * len(expected_norm)

    for i, expected in enumerate(expected_norm):
        for j, actual in enumerate(actual_norm):
            if not used_actual[j] and actual == expected:
                used_actual[j] = True
                matched[i] = True
                break

    for i, expected in enumerate(expected_norm):
        if matched[i]:
            continue
        for j, actual in enumerate(actual_norm):
            if not used_actual[j] and expected in actual:
                used_actual[j] = True
                matched[i] = True
                break

    unmatched_expected = [expected_raw[i] for i, ok in enumerate(matched) if not ok]
    unmatched_actual = [actual_raw[i] for i, used in enumerate(used_actual) if not used]
    return sum(1 for ok in matched if ok), unmatched_expected, unmatched_actual


def score_row(expected_raw: object, actual_codes: Sequence[object]) -> RowScore:
    expected = split_codes(expected_raw)
    actual = [str(item or "").strip() for item in actual_codes if str(item or "").strip()]
    if not expected:
        return RowScore(str(expected_raw or ""), actual, 0, 0, 0, [], actual)
    business_correct, unmatched_expected, unmatched_actual = _match(expected, actual, normalize_business)
    strict_correct, _, _ = _match(expected, actual, normalize_strict)
    return RowScore(
        expected_raw=str(expected_raw or ""),
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
