from optimizer.regression_gate import compare_regression_scores
from optimizer.scoring import ScoreSummary, TypeScoreSummary


def _code_summary(total=10, correct=9, accuracy=90.0):
    return ScoreSummary(
        business_total=total,
        business_correct=correct,
        business_accuracy=accuracy,
        strict_correct=correct,
        strict_accuracy=accuracy,
    )


def _type_summary(total=10, correct=9, accuracy=90.0, not_evaluable=0):
    return TypeScoreSummary(
        type_total=total,
        type_correct=correct,
        type_accuracy=accuracy,
        not_evaluable_count=not_evaluable,
    )


def test_code_regression_gate_passes_equal_or_better_metrics():
    decision = compare_regression_scores(
        "code",
        _code_summary(),
        _code_summary(total=11, correct=10, accuracy=91.0),
    )

    assert decision.passed is True
    assert decision.reason == "passed"
    assert [check.name for check in decision.checks] == [
        "business_accuracy_not_decreased",
        "business_total_not_shrunk",
    ]


def test_code_regression_gate_rejects_business_accuracy_decrease():
    decision = compare_regression_scores("code", _code_summary(accuracy=90.0), _code_summary(accuracy=89.99))

    assert decision.passed is False
    assert decision.checks[0].passed is False
    assert decision.checks[0].reason == "business_accuracy decreased from 90.0 to 89.99"


def test_code_regression_gate_rejects_denominator_shrinkage():
    decision = compare_regression_scores("code", _code_summary(total=10), _code_summary(total=9))

    assert decision.passed is False
    assert decision.checks[1].passed is False
    assert decision.checks[1].reason == "business_total shrank from 10 to 9"


def test_type_regression_gate_rejects_type_accuracy_decrease():
    decision = compare_regression_scores("type", _type_summary(accuracy=90.0), _type_summary(accuracy=89.99))

    assert decision.passed is False
    assert decision.checks[0].passed is False
    assert decision.checks[0].reason == "type_accuracy decreased from 90.0 to 89.99"


def test_type_regression_gate_rejects_not_evaluable_increase():
    decision = compare_regression_scores(
        "type",
        _type_summary(not_evaluable=1),
        _type_summary(not_evaluable=2),
    )

    assert decision.passed is False
    assert decision.checks[1].passed is False
    assert decision.checks[1].reason == "not_evaluable_count increased from 1 to 2"


def test_type_regression_gate_rejects_denominator_shrinkage():
    decision = compare_regression_scores("type", _type_summary(total=10), _type_summary(total=9))

    assert decision.passed is False
    assert decision.checks[2].passed is False
    assert decision.checks[2].reason == "type_total shrank from 10 to 9"


def test_type_regression_gate_passes_equal_or_better_metrics():
    decision = compare_regression_scores(
        "type",
        _type_summary(total=10, correct=9, accuracy=90.0, not_evaluable=1),
        _type_summary(total=10, correct=10, accuracy=100.0, not_evaluable=0),
    )

    assert decision.passed is True
    assert decision.reason == "passed"
    assert [check.name for check in decision.checks] == [
        "type_accuracy_not_decreased",
        "not_evaluable_count_not_increased",
        "type_total_not_shrunk",
    ]
