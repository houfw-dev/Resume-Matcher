"""Loader for the V4-optimized resume diagnosis rubric.

The rubric (22 checklist items across 7 dimensions, one hard-veto red line) is
maintained in ``rules/简历诊断规范_V4_优化版.xlsx`` and exported verbatim into
``diagnosis_rules.json`` next to this module. Runtime code never reads the
spreadsheet — the JSON is the versioned artifact the app ships with.

Each item carries a public ``topic`` (the 二级维度 problem-location label
clients may see), a ``prerequisite`` ("" / "jd" / "intention") and two
server-side-only fields: the full ``criterion`` text and the ``qc``
质检违规等级建议 guidance (🔴/🟡/🟢 failure scenarios). Both are rendered into
the LLM judge prompt but never returned to API clients or the Word export.
Item 17 (目标岗位匹配度) requires the JD; the five 专业能力 pointer items
(18–22) require a clear target intention that resolves to a competency model.
``global_rules`` is kept as an empty list for forward compatibility — the
V4-optimized workbook folded the former G1–G11 cross-item guidance into the
criterion cells.

Diagnosis is a checklist (conform / partial / nonconform / na), not a scored
exam. Only an item whose QC heading declares 一票否决 (item 16) is a red line;
plain 🔴 markers (e.g. the stability risk item) are severe findings but never
vetoes. See ``diagnosis_summary`` for the counting logic.
"""

import functools
import json
from pathlib import Path
from typing import Any

# Ratings used by both deterministic checkers and the LLM judge.
RATING_CONFORM = "conform"  # 符合
RATING_PARTIAL = "partial"  # 部分符合
RATING_NONCONFORM = "nonconform"  # 不符合
RATING_NA = "na"  # 不适用 — excluded from the applicable denominator

RATINGS = (RATING_CONFORM, RATING_PARTIAL, RATING_NONCONFORM, RATING_NA)

SEVERITY_REDLINE = "redline"  # hard veto — failure fails the whole resume
SEVERITY_NORMAL = "normal"

# 7th dimension: role-specific capability items (base ids 18–22) whose actual
# standards are filled in from the matched competency model.
COMPETENCE_DIMENSION_KEY = "competence"

# Item prerequisite markers (column 诊断前置条件 in the source workbook).
PREREQUISITE_JD = "jd"  # item 17: target job description required
PREREQUISITE_INTENTION = "intention"  # items 18–22: target intention required

_RULES_PATH = Path(__file__).with_name("diagnosis_rules.json")


@functools.lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    """Return the full rubric document (cached)."""
    with _RULES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@functools.lru_cache(maxsize=1)
def get_rules() -> "DiagnosisRules":
    """Return parsed rubric structures."""
    raw = load_rules()
    items: dict[int, dict[str, Any]] = {}
    for item in raw["items"]:
        items[item["id"]] = item
    dimensions: dict[str, dict[str, Any]] = {
        dim["key"]: dim for dim in raw["dimensions"]
    }
    return DiagnosisRules(
        spec_version=raw["spec_version"],
        items=items,
        dimensions=dimensions,
        dimension_order=tuple(dim["key"] for dim in raw["dimensions"]),
        global_rules=raw.get("global_rules", []),
        competency_models=raw.get("competency_models", []),
    )


class DiagnosisRules:
    """Parsed view over the rubric document."""

    def __init__(
        self,
        *,
        spec_version: str,
        items: dict[int, dict[str, Any]],
        dimensions: dict[str, dict[str, Any]],
        dimension_order: tuple[str, ...],
        global_rules: list[dict[str, Any]] | None = None,
        competency_models: list[dict[str, Any]] | None = None,
    ) -> None:
        self.spec_version = spec_version
        self.items = items
        self.dimensions = dimensions
        self.dimension_order = dimension_order
        self.global_rules = global_rules or []
        self.competency_models = competency_models or []

    @property
    def redline_ids(self) -> tuple[int, ...]:
        """Hard-veto item ids (spec order)."""
        return tuple(
            item_id
            for item_id, item in self.items.items()
            if item.get("severity") == SEVERITY_REDLINE
        )

    def item(self, item_id: int) -> dict[str, Any]:
        """Return one rubric item."""
        return self.items[item_id]
