"""Canonical resume section ordering and section-title governance.

Backend mirror of ``apps/frontend/lib/utils/section-order.ts``. The two
implementations must stay behaviour-identical; cross-tree tests guard the
shared multilingual default-title table and the degree classifier.

Canonical blocks (two legal orderings, chosen by highest degree):

formal (统招本科/统招硕士/博士):
    基础信息 教育背景 个人优势 专业技能 工作经历 项目经验
    [其他自定义区块] 自我评价
other (all other degrees, incl. 非统招本科/大专):
    基础信息 个人优势 专业技能 工作经历 项目经验
    [其他自定义区块] 教育背景 自我评价
"""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from app.schemas.models import DEFAULT_SECTION_META

DegreeClass = Literal["formal", "other"]

# ---------------------------------------------------------------------------
# Degree classification
# ---------------------------------------------------------------------------

FORMAL_DEGREE_MARKERS: tuple[str, ...] = ("统招", "全日制")
NON_FORMAL_DEGREE_MARKERS: tuple[str, ...] = (
    "自考",
    "成教",
    "函授",
    "网络教育",
    "网教",
    "电大",
    "开放大学",
    "开放教育",
    "业余",
    "专升本",
)

# Highest-first: 博士 must be checked before 硕士 (博士研究生 contains 研究生).
_DEGREE_LEVEL_PATTERNS: tuple[tuple[int, re.Pattern[str]], ...] = (
    (5, re.compile(r"博士")),
    (4, re.compile(r"硕士|研究生")),
    (3, re.compile(r"本科")),
    (2, re.compile(r"大专|专科|高职")),
    (1, re.compile(r"中专|中职|技校|高中")),
)


def _degree_level(text: str) -> int:
    for level, pattern in _DEGREE_LEVEL_PATTERNS:
        if pattern.search(text):
            return level
    return 0


def _is_formal_entry(level: int, text: str) -> bool:
    # Doctorates always take the education-second branch.
    if level == 5:
        return True
    if level not in (3, 4):
        return False
    if not any(marker in text for marker in FORMAL_DEGREE_MARKERS):
        return False
    return not any(marker in text for marker in NON_FORMAL_DEGREE_MARKERS)


def classify_highest_degree(
    education: list[dict[str, Any]] | None,
) -> DegreeClass:
    """Classify the resume's highest degree (formal/other).

    The highest level across entries wins; among entries at that level a
    single formal one makes the resume formal. Unrecognisable/missing
    education resolves to ``other``.
    """
    if not isinstance(education, list):
        return "other"

    levels: list[int] = []
    for entry in education:
        if not isinstance(entry, dict):
            continue
        degree = entry.get("degree")
        text = degree if isinstance(degree, str) else ""
        levels.append(_degree_level(text))

    max_level = max(levels, default=0)
    if max_level == 0:
        return "other"

    for entry in education:
        if not isinstance(entry, dict):
            continue
        degree = entry.get("degree")
        text = degree if isinstance(degree, str) else ""
        if _degree_level(text) == max_level and _is_formal_entry(max_level, text):
            return "formal"
    return "other"


# ---------------------------------------------------------------------------
# Symbols and sequences
# ---------------------------------------------------------------------------

SELFEVAL_SYMBOL = "__selfeval__"
CUSTOM_CLUSTER_SYMBOL = "__custom__"

SELFEVAL_TOKENS: tuple[str, ...] = (
    "自我评价",
    "自我评定",
    "个人评价",
    "自我介绍",
    "个人介绍",
    "个人简介",
    "个人简述",
    "个人总结",
)

DEFAULT_SECTION_KEYS: tuple[str, ...] = (
    "personalInfo",
    "summary",
    "workExperience",
    "education",
    "personalProjects",
    "additional",
)
_DEFAULT_KEY_SET = frozenset(DEFAULT_SECTION_KEYS)

CANONICAL_SEQUENCE_FORMAL: tuple[str, ...] = (
    "personalInfo",
    "education",
    "summary",
    "additional",
    "workExperience",
    "personalProjects",
    CUSTOM_CLUSTER_SYMBOL,
    SELFEVAL_SYMBOL,
)

CANONICAL_SEQUENCE_OTHER: tuple[str, ...] = (
    "personalInfo",
    "summary",
    "additional",
    "workExperience",
    "personalProjects",
    CUSTOM_CLUSTER_SYMBOL,
    "education",
    SELFEVAL_SYMBOL,
)

# English canonical titles — reset target for renamed default blocks.
CANONICAL_DEFAULT_TITLES: dict[str, str] = {
    "personalInfo": "Personal Info",
    "summary": "Summary",
    "workExperience": "Experience",
    "education": "Education",
    "personalProjects": "Projects",
    "additional": "Skills & Awards",
}

# Titles that count as a NON-renamed default block: English canonical, every
# shipped 7-locale title, and common zh aliases from uploaded resumes.
DEFAULT_TITLE_ALIASES: dict[str, frozenset[str]] = {
    "personalInfo": frozenset(
        {
            "Personal Info",
            "Información Personal",
            "个人信息",
            "個人情報",
            "개인 정보",
            "Informações Pessoais",
            "Informations personnelles",
            "基础信息",
            "基本信息",
        }
    ),
    "summary": frozenset(
        {
            "Summary",
            "Resumen",
            "概要",
            "요약",
            "Resumo",
            "Résumé",
            "个人优势",
            "核心优势",
            "竞争优势",
            "综合优势",
            "个人亮点",
        }
    ),
    "workExperience": frozenset(
        {
            "Experience",
            "Experiencia",
            "工作经历",
            "職歴",
            "경력",
            "Experiência",
            "Expérience",
            "工作经验",
            "实习经历",
            "从业经历",
            "职业履历",
            "任职经历",
            "工作履历",
            "职场经历",
        }
    ),
    "education": frozenset(
        {
            "Education",
            "Educación",
            "教育背景",
            "学歴",
            "학력",
            "Formação",
            "Formation",
            "教育经历",
            "学历信息",
            "求学履历",
        }
    ),
    "personalProjects": frozenset(
        {
            "Projects",
            "Proyectos",
            "项目经历",
            "プロジェクト",
            "프로젝트",
            "Projetos",
            "Projets",
            "项目经验",
            "项目履历",
            "重点项目",
        }
    ),
    "additional": frozenset(
        {
            "Skills & Awards",
            "Habilidades y Premios",
            "技能与荣誉",
            "スキル・受賞歴",
            "기술 및 수상 내역",
            "Habilidades e Prêmios",
            "Compétences et récompenses",
            "专业技能",
            "职业技能",
            "核心技能",
            "专业能力",
            "技能",
            "技能清单",
            "技术能力",
            "技术技能",
        }
    ),
}

# zh headings that identify the canonical self-introduction custom block.
# The frontend render layer rewrites them to the locale canonical title
# (自我介绍); the backend keeps them for token parity and save-time slot
# placement.
SELF_INTRODUCTION_TITLE_ALIASES: frozenset[str] = frozenset(
    {
        "自我介绍",
        "个人介绍",
        "个人简介",
        "个人简述",
        "个人评价",
    }
)

# Required blocks stay visible even when empty (diagnosis item 3).
REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "personalInfo",
        "education",
        "workExperience",
        "personalProjects",
        "additional",
    }
)


def _collapse_title(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def is_accepted_default_title(key: str, name: str) -> bool:
    """Whether ``name`` is a shipped/alias title for default block ``key``."""
    accepted = DEFAULT_TITLE_ALIASES.get(key)
    if accepted is None or not isinstance(name, str):
        return False
    folded = _collapse_title(name)
    return any(_collapse_title(title) == folded for title in accepted)


def section_symbol(meta: dict[str, Any]) -> str | None:
    """Resolve a meta row to a canonical slot symbol, or None (custom cluster)."""
    key = meta.get("key")
    if isinstance(key, str) and key in _DEFAULT_KEY_SET:
        return key
    name = meta.get("displayName")
    name = name if isinstance(name, str) else ""
    if any(token in name for token in SELFEVAL_TOKENS):
        return SELFEVAL_SYMBOL
    return None


def place_sections(
    rows: list[dict[str, Any]], degree_class: DegreeClass
) -> list[dict[str, Any]]:
    """Place visible meta rows into the branch-specific canonical sequence."""
    sorted_rows = sorted(rows, key=lambda row: _safe_order(row))
    fixed_slots: dict[str, dict[str, Any]] = {}
    custom_cluster: list[dict[str, Any]] = []
    selfeval_claimed = False

    for row in sorted_rows:
        key = row.get("key")
        if isinstance(key, str) and key in _DEFAULT_KEY_SET:
            if key not in fixed_slots:
                fixed_slots[key] = row
            else:
                custom_cluster.append(row)
            continue
        name = row.get("displayName")
        name = name if isinstance(name, str) else ""
        if not selfeval_claimed and any(
            token in name for token in SELFEVAL_TOKENS
        ):
            fixed_slots[SELFEVAL_SYMBOL] = row
            selfeval_claimed = True
            continue
        custom_cluster.append(row)

    sequence = (
        CANONICAL_SEQUENCE_FORMAL
        if degree_class == "formal"
        else CANONICAL_SEQUENCE_OTHER
    )
    ordered: list[dict[str, Any]] = []
    for symbol in sequence:
        if symbol == CUSTOM_CLUSTER_SYMBOL:
            ordered.extend(custom_cluster)
        elif symbol in fixed_slots:
            ordered.append(fixed_slots[symbol])
    return ordered


def _safe_order(row: dict[str, Any]) -> int:
    order = row.get("order", 0)
    return order if isinstance(order, int) else 0


# ---------------------------------------------------------------------------
# Emptiness
# ---------------------------------------------------------------------------


def _meaningful(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


_SCALAR_CONTENT_FIELDS = (
    "title",
    "name",
    "company",
    "department",
    "role",
    "subtitle",
    "location",
    "years",
    "institution",
    "degree",
    "github",
    "website",
)


def _entry_has_content(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    if any(_meaningful(entry.get(field)) for field in _SCALAR_CONTENT_FIELDS):
        return True
    description = entry.get("description")
    return isinstance(description, list) and any(
        _meaningful(point) for point in description
    )


def _collection_has_content(value: Any) -> bool:
    return isinstance(value, list) and any(_entry_has_content(entry) for entry in value)


def is_section_empty(meta: dict[str, Any], resume: dict[str, Any]) -> bool:
    """Whether a titled section currently has any renderable content."""
    key = meta.get("key")
    if key == "personalInfo":
        info = resume.get("personalInfo")
        if not isinstance(info, dict):
            return True
        return not any(_meaningful(value) for value in info.values())
    if key == "summary":
        return not _meaningful(resume.get("summary"))
    if key == "workExperience":
        return not _collection_has_content(resume.get("workExperience"))
    if key == "education":
        return not _collection_has_content(resume.get("education"))
    if key == "personalProjects":
        return not _collection_has_content(resume.get("personalProjects"))
    if key == "additional":
        additional = resume.get("additional")
        if not isinstance(additional, dict):
            return True
        return not any(
            isinstance(additional.get(field), list)
            and any(_meaningful(item) for item in additional[field])
            for field in (
                "technicalSkills",
                "languages",
                "certificationsTraining",
                "awards",
            )
        )

    custom_sections = resume.get("customSections")
    custom = (
        custom_sections.get(key)
        if isinstance(custom_sections, dict)
        else None
    )
    if not isinstance(custom, dict):
        return True
    section_type = custom.get("sectionType")
    if section_type == "text":
        return not _meaningful(custom.get("text"))
    if section_type == "itemList":
        return not _collection_has_content(custom.get("items"))
    if section_type == "stringList":
        strings = custom.get("strings")
        return not (
            isinstance(strings, list) and any(_meaningful(item) for item in strings)
        )
    return True


# ---------------------------------------------------------------------------
# Save / response canonicalization
# ---------------------------------------------------------------------------


def _is_meta_row(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("key"), str)


_DEFAULT_META_ROWS: dict[str, dict[str, Any]] = {
    str(row["key"]): row for row in DEFAULT_SECTION_META if "key" in row
}


def heal_missing_default_sections(
    rows: list[dict[str, Any]], resume: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reconcile meta rows with resume content.

    The LLM is instructed to emit one meta row per content-bearing section
    but occasionally omits one (observed: education data present, no
    education meta row), which made the section unrenderable in every
    template. Every default block that currently holds renderable content
    gets a canonical visible row appended; empty blocks are left untouched
    and custom sections are never synthesised. ``place_sections`` afterwards
    moves appended rows into their canonical slots.
    """
    present = {
        row.get("key") for row in rows if isinstance(row, dict)
    }
    healed = list(rows)
    for key in DEFAULT_SECTION_KEYS:
        if key in present:
            continue
        if is_section_empty({"key": key}, resume):
            continue
        template = _DEFAULT_META_ROWS.get(key)
        if template is None:
            continue
        healed.append({**copy.deepcopy(template), "isVisible": True})
    return healed


def canonicalize_section_meta(
    resume: dict[str, Any],
    *,
    reset_names: bool = True,
    hide_empty_optional: bool = True,
) -> list[dict[str, Any]]:
    """Return canonicalized sectionMeta for save/response.

    - falls back to the canonical default meta when missing/empty;
    - resets renamed DEFAULT blocks to the English canonical title when
      ``reset_names`` (locale/localization layer renders the local name);
    - heals content-bearing default blocks whose meta row the LLM omitted
      (appends a canonical visible row; empty blocks stay untouched);
    - hides empty OPTIONAL blocks (summary + custom) when
      ``hide_empty_optional`` — never deletes content data;
    - rewrites ``order`` to dense ints of the degree-branch sequence (hidden
      rows keep their slot).

    Input rows are never mutated.
    """
    raw_meta = resume.get("sectionMeta")
    source = raw_meta if isinstance(raw_meta, list) and raw_meta else DEFAULT_SECTION_META
    rows: list[dict[str, Any]] = [
        copy.deepcopy(row) for row in source if _is_meta_row(row)
    ]
    if not rows:
        rows = copy.deepcopy(DEFAULT_SECTION_META)

    # LLM safety net: a content-bearing default block must have a meta row
    # even when the model omitted it, or no template can render it.
    rows = heal_missing_default_sections(rows, resume)

    for row in rows:
        key = row.get("key")
        if (
            reset_names
            and isinstance(key, str)
            and key in _DEFAULT_KEY_SET
            and not is_accepted_default_title(key, row.get("displayName", ""))
        ):
            row["displayName"] = CANONICAL_DEFAULT_TITLES[key]
        if (
            hide_empty_optional
            and row.get("isVisible", True)
            and isinstance(key, str)
            and key not in REQUIRED_KEYS
            and is_section_empty(row, resume)
        ):
            row["isVisible"] = False

    degree_class = classify_highest_degree(resume.get("education"))
    ordered = place_sections(rows, degree_class)
    for index, row in enumerate(ordered):
        row["order"] = index
    return ordered
