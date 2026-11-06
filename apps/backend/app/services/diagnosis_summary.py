"""Checklist summarisation for the V4-optimized diagnosis rubric (no scoring).

The checklist-edition rubric dropped weights entirely. A diagnosis is a
checklist: every item is conform / partial / nonconform / na, and the report
shows counts plus the hard-veto red-line verdict — no points, no band.

* "na" items are excluded from the applicable count (a missing module does not
  count as a failure).
* Dimension counts cover every item in that dimension (including na).
* A red-line item rated nonconform fails the resume regardless of counts.

No I/O and no LLM here — input is verdicts plus the static rubric.
"""

from typing import Any

from app.services.diagnosis_rules import (
    RATING_CONFORM,
    RATING_NA,
    RATING_NONCONFORM,
    RATING_PARTIAL,
    DiagnosisRules,
    get_rules,
)

RATING_ORDER = (RATING_CONFORM, RATING_PARTIAL, RATING_NONCONFORM, RATING_NA)


def empty_counts() -> dict[str, int]:
    """A zeroed rating-count dict (plus an ``effective`` applicable total)."""
    return {
        RATING_CONFORM: 0,
        RATING_PARTIAL: 0,
        RATING_NONCONFORM: 0,
        RATING_NA: 0,
        "effective": 0,
    }


def summarize_verdicts(
    verdicts: dict[int, tuple[str, str]],
    *,
    rules: DiagnosisRules | None = None,
) -> dict[str, Any]:
    """Aggregate item verdicts into checklist counts and the red-line verdict.

    Args:
        verdicts: item_id -> (rating, evidence). Items absent from this map are
            treated as na (the caller is expected to supply every rubric item).

    Returns:
        Dict with overall ``counts``, per-dimension rows and failed red lines.
    """
    rules = rules or get_rules()

    dimensions: list[dict[str, Any]] = []
    overall = empty_counts()

    for dimension_key in rules.dimension_order:
        dim_meta = rules.dimensions[dimension_key]
        dim_counts = empty_counts()
        for item in rules.items.values():
            if item["dimension"] != dimension_key:
                continue
            rating = (verdicts.get(item["id"]) or (RATING_NA, ""))[0]
            if rating not in RATING_ORDER:
                rating = RATING_NONCONFORM
            dim_counts[rating] += 1
            overall[rating] += 1
            if rating != RATING_NA:
                dim_counts["effective"] += 1
                overall["effective"] += 1
        dimensions.append(
            {
                "key": dimension_key,
                "name": dim_meta["name"],
                "counts": dim_counts,
            }
        )

    failed_redlines: list[int] = [
        item_id
        for item_id in rules.redline_ids
        if (verdicts.get(item_id) or ("", ""))[0] == RATING_NONCONFORM
    ]
    return {
        "counts": overall,
        "dimensions": dimensions,
        "redline_passed": not failed_redlines,
        "failed_redline_ids": failed_redlines,
    }
