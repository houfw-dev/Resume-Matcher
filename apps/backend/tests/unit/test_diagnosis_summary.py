"""Tests for checklist verdict summarisation (score-free V4 rubric)."""

from app.services.diagnosis_rules import (
    RATING_CONFORM,
    RATING_NA,
    RATING_NONCONFORM,
    RATING_PARTIAL,
    SEVERITY_NORMAL,
    SEVERITY_REDLINE,
    DiagnosisRules,
)
from app.services.diagnosis_summary import empty_counts, summarize_verdicts


def _rules() -> DiagnosisRules:
    return DiagnosisRules(
        spec_version="V4-TEST",
        items={
            1: {"id": 1, "dimension": "a", "severity": SEVERITY_NORMAL},
            2: {"id": 2, "dimension": "a", "severity": SEVERITY_NORMAL},
            3: {"id": 3, "dimension": "b", "severity": SEVERITY_NORMAL},
            41: {"id": 41, "dimension": "b", "severity": SEVERITY_REDLINE},
        },
        dimensions={
            "a": {"key": "a", "name": "维度甲"},
            "b": {"key": "b", "name": "维度乙"},
        },
        dimension_order=("a", "b"),
    )


def test_empty_counts_is_zeroed_with_effective() -> None:
    counts = empty_counts()
    assert counts == {
        RATING_CONFORM: 0,
        RATING_PARTIAL: 0,
        RATING_NONCONFORM: 0,
        RATING_NA: 0,
        "effective": 0,
    }


def test_counts_and_na_excluded_from_effective() -> None:
    verdicts = {
        1: (RATING_CONFORM, "ok"),
        2: (RATING_NA, "module missing"),
        3: (RATING_PARTIAL, "weak"),
        41: (RATING_CONFORM, "ok"),
    }
    summary = summarize_verdicts(verdicts, rules=_rules())
    counts = summary["counts"]
    assert counts[RATING_CONFORM] == 2
    assert counts[RATING_PARTIAL] == 1
    assert counts[RATING_NONCONFORM] == 0
    assert counts[RATING_NA] == 1
    assert counts["effective"] == 3  # na does not count as applicable


def test_per_dimension_counts() -> None:
    verdicts = {
        1: (RATING_CONFORM, ""),
        2: (RATING_NONCONFORM, ""),
        3: (RATING_NA, ""),
        41: (RATING_CONFORM, ""),
    }
    summary = summarize_verdicts(verdicts, rules=_rules())
    dims = {d["key"]: d for d in summary["dimensions"]}
    assert dims["a"]["name"] == "维度甲"
    assert dims["a"]["counts"][RATING_CONFORM] == 1
    assert dims["a"]["counts"][RATING_NONCONFORM] == 1
    assert dims["a"]["counts"]["effective"] == 2
    assert dims["b"]["counts"][RATING_NA] == 1
    assert dims["b"]["counts"]["effective"] == 1


def test_missing_verdict_defaults_na_not_failure() -> None:
    summary = summarize_verdicts({1: (RATING_CONFORM, "")}, rules=_rules())
    # Items 2, 3, 41 were never judged: all na, red line therefore not failed.
    assert summary["counts"][RATING_NA] == 3
    assert summary["redline_passed"] is True
    assert summary["failed_redline_ids"] == []


def test_failed_redline_aggregation() -> None:
    verdicts = {
        1: (RATING_CONFORM, ""),
        2: (RATING_CONFORM, ""),
        3: (RATING_CONFORM, ""),
        # A red line rated partial is a warning, not a veto; only nonconform fails.
        41: (RATING_PARTIAL, ""),
    }
    summary = summarize_verdicts(verdicts, rules=_rules())
    assert summary["redline_passed"] is True

    verdicts[41] = (RATING_NONCONFORM, "gap > 6 months")
    summary = summarize_verdicts(verdicts, rules=_rules())
    assert summary["redline_passed"] is False
    assert summary["failed_redline_ids"] == [41]


def test_unknown_rating_counts_as_nonconform() -> None:
    # A defensive default: a garbled LLM rating must never silently pass.
    summary = summarize_verdicts({1: ("bogus", "")}, rules=_rules())
    assert summary["counts"][RATING_NONCONFORM] == 1
