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

The same artifact carries two further sections maintained in
``rules/diagnosis_rules.yaml``: ``parameters`` (the objective checkers'
numeric thresholds, validated by ``DiagnosisParameters``) and
``vocabularies`` (regex strings, mainstream stack groups, recognition tokens
and template labels, validated by ``DiagnosisVocabularies``). Both are
server-side only — in particular the stack groups' ``equiv`` guidance never
leaves the server. Missing sections or uncompilable patterns fail loudly at
load time instead of reverting to hidden code defaults.
"""

import functools
import json
import re
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.rule_patterns import (
    PatternSpec,
    compile_specs,
    validate_string_list,
)

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


# ---------------------------------------------------------------------------
# Externalized objective-checker parameters and vocabularies
# ---------------------------------------------------------------------------


class StackGroup(NamedTuple):
    """One mainstream tech-stack group used by the item-7 deterministic check.

    ``equiv`` is SERVER-SIDE LLM semantic-review guidance; it never leaves the
    server (see diagnosis._build_skill_review_block).
    """

    key: str
    name: str
    pattern: re.Pattern[str]
    hint: str
    equiv: str


class StackGroupSpec(BaseModel):
    """Raw stack-group entry from the artifact (regex string, not compiled)."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    flags: list[str] = Field(default_factory=list)
    hint: str = Field(min_length=1)
    equiv: str = Field(min_length=1)

    def build(self) -> StackGroup:
        """Compile the pattern and build the runtime NamedTuple."""
        spec = PatternSpec(pattern=self.pattern, flags=self.flags)
        return StackGroup(
            key=self.key,
            name=self.name,
            pattern=spec.compile(),
            hint=self.hint,
            equiv=self.equiv,
        )


class DegreeRankSpec(BaseModel):
    """One degree-name -> rank regex (highest rank wins, list order matters)."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    pattern: str = Field(min_length=1)
    flags: list[str] = Field(default_factory=list)

    def compiled(self) -> re.Pattern[str]:
        return PatternSpec(pattern=self.pattern, flags=self.flags).compile()


class DiagnosisParameters(BaseModel):
    """All numeric thresholds of the deterministic objective checkers.

    Every field is required in the artifact — a missing threshold must fail
    loudly at load time rather than silently reverting to a code default.
    """

    model_config = ConfigDict(extra="forbid")

    # Item 1/2 layout and length.
    chars_per_line: int = Field(gt=0)
    chars_per_page: int = Field(gt=0)
    max_point_lines: int = Field(gt=0)
    max_pages: int = Field(gt=0)

    # Item 6/10 point-count bands.
    advantage_points_min: int = Field(ge=0)
    advantage_points_max: int = Field(gt=0)
    selfeval_points_min: int = Field(ge=0)
    selfeval_points_max: int = Field(gt=0)

    # Item 7 skill count and stack-group coverage bands.
    skill_count_min: int = Field(gt=0)
    skill_count_max: int = Field(gt=0)
    stack_conform_ratio: float = Field(gt=0, le=1)
    stack_partial_ratio: float = Field(gt=0, le=1)

    # Item 9 project count and tech-stack detection.
    project_count_min: int = Field(gt=0)
    project_count_max: int = Field(gt=0)
    project_tech_vocab_min_hits: int = Field(gt=0)

    # Item 14 stability risk markers.
    gap_partial_months: int = Field(ge=0)
    gap_nonconform_months: int = Field(gt=0)
    recent_window_months: int = Field(gt=0)
    job_hop_company_count: int = Field(gt=0)
    short_stint_months: int = Field(gt=0)
    short_stint_strong_months: int = Field(gt=0)

    # Item 13 timeline arithmetic.
    work_education_lead_months: int = Field(ge=0)
    stated_years_tolerance: float = Field(gt=0)

    # Tenure gates (items 3 / 8 / 15).
    advantage_required_tenure_years: int = Field(gt=0)
    internship_experienced_tenure_years: int = Field(gt=0)
    growth_gate_years: int = Field(gt=0)

    @model_validator(mode="after")
    def _check_band_ordering(self) -> "DiagnosisParameters":
        ordered_bands = (
            ("advantage_points", self.advantage_points_min, self.advantage_points_max),
            ("selfeval_points", self.selfeval_points_min, self.selfeval_points_max),
            ("skill_count", self.skill_count_min, self.skill_count_max),
            ("project_count", self.project_count_min, self.project_count_max),
            ("gap_months", self.gap_partial_months, self.gap_nonconform_months),
            ("short_stint", self.short_stint_strong_months, self.short_stint_months),
        )
        for label, low, high in ordered_bands:
            if low > high:
                raise ValueError(f"{label}: min/low ({low}) exceeds max/high ({high})")
        if self.stack_partial_ratio > self.stack_conform_ratio:
            raise ValueError("stack_partial_ratio must not exceed stack_conform_ratio")
        return self


class DiagnosisVocabularies(BaseModel):
    """Regex strings, stack groups, token lists and labels for the checkers."""

    model_config = ConfigDict(extra="forbid")

    regex_patterns: dict[str, PatternSpec]
    degree_rank_patterns: list[DegreeRankSpec]
    mainstream_stack_groups: list[StackGroupSpec]
    advantage_title_tokens: list[str]
    advantage_key_tokens: list[str]
    selfeval_title_tokens: list[str]
    selfeval_key_tokens: list[str]
    template_labels: dict[str, str]

    @field_validator("template_labels")
    @classmethod
    def _non_blank_template_labels(
        cls, labels: dict[str, str]
    ) -> dict[str, str]:
        for key, value in labels.items():
            if not key.strip() or not value.strip():
                raise ValueError("template_labels: blank keys or values are not allowed")
        return labels

    @model_validator(mode="after")
    def _validate_contents(self) -> "DiagnosisVocabularies":
        # Every externalized regex must compile at load time.
        compile_specs(self.regex_patterns)
        ranks = [spec.rank for spec in self.degree_rank_patterns]
        if not ranks or len(set(ranks)) != len(ranks):
            raise ValueError("degree_rank_patterns: ranks must be present and unique")
        for spec in self.degree_rank_patterns:
            spec.compiled()
        keys = [spec.key for spec in self.mainstream_stack_groups]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("mainstream_stack_groups: keys must be present and unique")
        for spec in self.mainstream_stack_groups:
            spec.build()
        validate_string_list(
            "advantage_title_tokens", self.advantage_title_tokens
        )
        validate_string_list("advantage_key_tokens", self.advantage_key_tokens)
        validate_string_list(
            "selfeval_title_tokens", self.selfeval_title_tokens
        )
        validate_string_list(
            "selfeval_key_tokens", self.selfeval_key_tokens
        )
        return self

    @functools.cached_property
    def regexes(self) -> dict[str, re.Pattern[str]]:
        """All named regexes, compiled once per process."""
        return compile_specs(self.regex_patterns)

    def regex(self, name: str) -> re.Pattern[str]:
        """Return one compiled regex, raising KeyError on unknown names."""
        return self.regexes[name]

    @functools.cached_property
    def mainstream_groups(self) -> tuple[StackGroup, ...]:
        """Ordered, compiled stack groups (artifact order is canonical)."""
        return tuple(spec.build() for spec in self.mainstream_stack_groups)

    @functools.cached_property
    def degree_rank_patterns_compiled(
        self,
    ) -> tuple[tuple[int, re.Pattern[str]], ...]:
        """Rank/regex pairs in the artifact's highest-first order."""
        return tuple((spec.rank, spec.compiled()) for spec in self.degree_rank_patterns)


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
    # The objective-checker data is mandatory in shipped artifacts: fail
    # loudly at load time instead of reverting to hidden code defaults.
    missing_sections = [
        name for name in ("parameters", "vocabularies") if name not in raw
    ]
    if missing_sections:
        raise ValueError(
            f"diagnosis_rules.json is missing section(s): {', '.join(missing_sections)}"
        )
    parameters = DiagnosisParameters.model_validate(raw["parameters"])
    vocabularies = DiagnosisVocabularies.model_validate(raw["vocabularies"])
    return DiagnosisRules(
        spec_version=raw["spec_version"],
        items=items,
        dimensions=dimensions,
        dimension_order=tuple(dim["key"] for dim in raw["dimensions"]),
        global_rules=raw.get("global_rules", []),
        competency_models=raw.get("competency_models", []),
        parameters=parameters,
        vocabularies=vocabularies,
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
        parameters: DiagnosisParameters | None = None,
        vocabularies: DiagnosisVocabularies | None = None,
    ) -> None:
        self.spec_version = spec_version
        self.items = items
        self.dimensions = dimensions
        self.dimension_order = dimension_order
        self.global_rules = global_rules or []
        self.competency_models = competency_models or []
        # Reduced constructions (competency expansion, focused unit tests)
        # may omit the objective-checker data; only get_rules() ships a fully
        # populated view, and diagnosis_checks imports that one.
        self.parameters = parameters
        self.vocabularies = vocabularies

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
