from optimizer.scoring import (
    aggregate_scores,
    aggregate_type_scores,
    normalize_business,
    normalize_strict,
    score_row,
    score_type_row,
    split_codes,
)


def test_business_normalization_matches_card_type_rules():
    assert normalize_business(" ab-OI S\u3000-12 ") == "AB01512"


def test_falsey_values_are_string_normalized():
    assert normalize_business(0) == "0"

    result = score_row(0, [0])

    assert result.business_correct == 1
    assert result.business_total == 1


def test_strict_normalization_does_not_replace_ois():
    assert normalize_strict(" O-I-S ") == "OIS"


def test_split_codes_uses_newlines_and_filters_empty_values():
    assert split_codes("AAA\n\n BBB \r\n") == ["AAA", "BBB"]


def test_exact_then_includes_match_consumes_actual_once():
    result = score_row("ABC\nABC", ["ABC-999"])

    assert result.business_correct == 1
    assert result.business_total == 2
    assert result.unmatched_expected == ["ABC"]


def test_matching_is_not_positional():
    result = score_row("AAA\nBBB", ["xxxBBBxxx", "AAA"])

    assert result.business_correct == 2
    assert result.business_accuracy == 100.0


def test_ambiguous_includes_follow_expected_order_greedy_tie_break():
    result = score_row("A\nAB", ["ABX\nAY"])

    assert result.business_correct == 1
    assert result.business_total == 2
    assert result.unmatched_expected == ["AB"]


def test_ambiguous_includes_can_match_when_specific_code_is_first():
    result = score_row("AB\nA", ["ABX\nAY"])

    assert result.business_correct == 2
    assert result.business_total == 2


def test_actual_cells_are_split_by_newline():
    result = score_row("AAA\nBBB", ["AAA\nBBB"])

    assert result.business_correct == 2
    assert result.business_accuracy == 100.0


def test_filtering_keeps_unmatched_expected_aligned():
    result = score_row("-\nABC", ["MISS"])

    assert result.unmatched_expected == ["ABC"]


def test_filtering_keeps_unmatched_actual_aligned():
    result = score_row("AAA", ["-", "MISS"])

    assert result.unmatched_actual == ["MISS"]


def test_empty_expected_is_skipped():
    result = score_row("", ["ANY"])

    assert result.business_total == 0
    assert result.business_accuracy == 0.0


def test_aggregate_scores_uses_business_metric_as_primary():
    summary = aggregate_scores([
        score_row("OIS", ["015"]),
        score_row("AAA", ["MISS"]),
    ])

    assert summary.business_total == 2
    assert summary.business_correct == 1
    assert summary.business_accuracy == 50.0


def test_type_scoring_accepts_single_and_repeated_values():
    single = score_type_row("Physics", ["Physics"])
    repeated = score_type_row("E-codesE-codes", ["E-codes", "E-codes"])

    assert single.type_correct == 1
    assert single.type_total == 1
    assert repeated.type_correct == 1
    assert repeated.type_total == 1


def test_type_scoring_accepts_contains_match():
    result = score_type_row("PhysicsPhysics", ["prefixPhysics", "Physicssuffix"])

    assert result.actual_raw == ["prefixPhysics", "Physicssuffix"]
    assert result.type_correct == 1


def test_type_scoring_marks_mismatch_evaluable():
    result = score_type_row("Physics", ["E-codes"])

    assert result.type_total == 1
    assert result.type_correct == 0
    assert result.not_evaluable_reason == ""


def test_type_scoring_excludes_missing_type_values():
    result = score_type_row("Physics", [])

    assert result.type_total == 0
    assert result.type_correct == 0
    assert result.not_evaluable_reason == "missing_type"


def test_aggregate_type_scores_exposes_not_evaluable_count():
    summary = aggregate_type_scores([
        score_type_row("Physics", ["Physics"]),
        score_type_row("E-codes", ["Physics"]),
        score_type_row("Physics", []),
    ])

    assert summary.type_total == 2
    assert summary.type_correct == 1
    assert summary.type_accuracy == 50.0
    assert summary.not_evaluable_count == 1
