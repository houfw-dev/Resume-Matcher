"""Tests for the canonical section-ordering helper.

Backend mirror of ``apps/frontend/tests/section-order.test.ts``; the two
suites must stay in sync. A final cross-tree test reads every shipped locale
file from the frontend so a renamed default title in any of the 7 locales
that the alias table does not recognise fails here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.section_order import (
    CANONICAL_SEQUENCE_FORMAL,
    CANONICAL_SEQUENCE_OTHER,
    SELFEVAL_SYMBOL,
    canonicalize_section_meta,
    classify_highest_degree,
    heal_missing_default_sections,
    is_accepted_default_title,
    is_section_empty,
    place_sections,
    section_symbol,
)

FRONTEND_MESSAGES = Path(__file__).resolve().parents[3] / "frontend" / "messages"

# resume.sections.<key> -> default section key (see section-helpers.ts).
LOCALE_TITLE_KEYS: tuple[tuple[str, str], ...] = (
    ("personalInfo", "personalInfo"),
    ("summary", "summary"),
    ("experience", "workExperience"),
    ("education", "education"),
    ("projects", "personalProjects"),
    ("skills", "additional"),
)


def edu(degree: str) -> dict[str, Any]:
    return {"id": 0, "degree": degree}


def meta(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "x",
        "key": "x",
        "displayName": "X",
        "sectionType": "text",
        "isDefault": False,
        "isVisible": True,
        "order": 0,
    }
    if overrides:
        row.update(overrides)
    return row


def default_meta() -> list[dict[str, Any]]:
    return [
        meta({"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info",
              "sectionType": "personalInfo", "isDefault": True, "order": 0}),
        meta({"id": "summary", "key": "summary", "displayName": "Summary",
              "isDefault": True, "order": 1}),
        meta({"id": "workExperience", "key": "workExperience", "displayName": "Experience",
              "sectionType": "itemList", "isDefault": True, "order": 2}),
        meta({"id": "education", "key": "education", "displayName": "Education",
              "sectionType": "itemList", "isDefault": True, "order": 3}),
        meta({"id": "personalProjects", "key": "personalProjects", "displayName": "Projects",
              "sectionType": "itemList", "isDefault": True, "order": 4}),
        meta({"id": "additional", "key": "additional", "displayName": "Skills & Awards",
              "sectionType": "stringList", "isDefault": True, "order": 5}),
    ]


# --- degree classification ---------------------------------------------------


def test_doctorates_always_formal_even_without_formal_marker() -> None:
    assert classify_highest_degree([edu("博士")]) == "formal"
    assert classify_highest_degree([edu("在职博士")]) == "formal"
    assert classify_highest_degree([edu("博士研究生")]) == "formal"


def test_formal_bachelors_and_masters_require_tongzhao_marker() -> None:
    assert classify_highest_degree([edu("统招硕士")]) == "formal"
    assert classify_highest_degree([edu("全日制硕士研究生")]) == "formal"
    assert classify_highest_degree([edu("统招本科")]) == "formal"
    assert classify_highest_degree([edu("全日制本科")]) == "formal"


def test_markerless_masters_are_other() -> None:
    assert classify_highest_degree([edu("硕士")]) == "other"
    assert classify_highest_degree([edu("在职研究生")]) == "other"
    assert classify_highest_degree([edu("MBA 硕士")]) == "other"


def test_every_non_formal_marker_is_other() -> None:
    for marker in (
        "自考", "成教", "函授", "网络教育", "网教", "电大",
        "开放大学", "开放教育", "业余",
    ):
        assert classify_highest_degree([edu(f"{marker}本科")]) == "other"
    assert classify_highest_degree([edu("全日制自考本科")]) == "other"
    assert classify_highest_degree([edu("全日制专升本")]) == "other"


def test_junior_college_and_below_other_even_full_time() -> None:
    assert classify_highest_degree([edu("全日制大专")]) == "other"
    assert classify_highest_degree([edu("统招大专")]) == "other"
    assert classify_highest_degree([edu("大专")]) == "other"
    assert classify_highest_degree([edu("中专")]) == "other"
    assert classify_highest_degree([edu("高中")]) == "other"


def test_highest_level_wins_across_entries() -> None:
    assert classify_highest_degree([edu("大专"), edu("统招本科")]) == "formal"
    assert classify_highest_degree([edu("自考本科"), edu("大专")]) == "other"
    # A formal lower degree does not upgrade a non-formal higher one.
    assert classify_highest_degree([edu("全日制本科"), edu("在职硕士")]) == "other"


def test_missing_or_malformed_education_is_other() -> None:
    assert classify_highest_degree(None) == "other"
    assert classify_highest_degree([]) == "other"
    assert classify_highest_degree([{}]) == "other"
    assert classify_highest_degree([{"id": 1}]) == "other"
    assert classify_highest_degree([edu("")]) == "other"


# --- symbols ----------------------------------------------------------------


def test_section_symbol_default_keys_stay_default() -> None:
    assert section_symbol(meta({"key": "additional", "displayName": "技能与荣誉"})) == "additional"
    assert section_symbol(meta({"key": "education"})) == "education"


def test_section_symbol_recognises_selfeval_titles() -> None:
    assert section_symbol(meta({"displayName": "自我评价"})) == SELFEVAL_SYMBOL
    for title in (
        "自我介绍",
        "个人介绍",
        "个人简介",
        "个人简述",
        "个人评价",
        "自我评定",
        "个人总结",
    ):
        assert section_symbol(meta({"displayName": title})) == SELFEVAL_SYMBOL


def test_section_symbol_none_for_ordinary_custom() -> None:
    assert section_symbol(meta({"displayName": "兴趣爱好"})) is None


def test_section_symbol_legacy_honors_headings_ride_custom_cluster() -> None:
    # The legacy 荣誉证书 fixed slot was removed; such headings no longer
    # claim a canonical position and sort inside the custom cluster.
    for title in ("荣誉证书", "资格证书", "奖项经历", "获奖情况", "奖状"):
        assert section_symbol(meta({"displayName": title})) is None


# --- placement --------------------------------------------------------------


def full_meta() -> list[dict[str, Any]]:
    rows = default_meta()
    rows.extend([
        meta({"id": "custom_hobby", "key": "custom_hobby", "displayName": "兴趣爱好", "order": 6}),
        meta({"id": "custom_honors", "key": "custom_honors", "displayName": "荣誉证书", "order": 7}),
        meta({"id": "custom_eval", "key": "custom_eval", "displayName": "自我评价", "order": 8}),
    ])
    return rows


def test_place_formal_branch_full_sequence() -> None:
    ordered = place_sections(full_meta(), "formal")
    assert [r["key"] for r in ordered] == [
        "personalInfo",
        "education",
        "summary",
        "additional",
        "workExperience",
        "personalProjects",
        "custom_hobby",
        "custom_honors",
        "custom_eval",
    ]


def test_place_other_branch_moves_education_before_selfeval() -> None:
    ordered = place_sections(full_meta(), "other")
    assert [r["key"] for r in ordered] == [
        "personalInfo",
        "summary",
        "additional",
        "workExperience",
        "personalProjects",
        "custom_hobby",
        "custom_honors",
        "education",
        "custom_eval",
    ]


def test_place_education_directly_before_selfeval_without_extra_customs() -> None:
    rows = default_meta()
    rows.append(
        meta({"id": "custom_eval", "key": "custom_eval", "displayName": "自我评价", "order": 6})
    )
    ordered = place_sections(rows, "other")
    assert [r["key"] for r in ordered][-2:] == ["education", "custom_eval"]


def test_place_keeps_unknown_customs_in_relative_order() -> None:
    rows = default_meta()
    rows.extend([
        meta({"id": "custom_b", "key": "custom_b", "displayName": "出版物", "order": 7}),
        meta({"id": "custom_a", "key": "custom_a", "displayName": "志愿者", "order": 6}),
    ])
    ordered = place_sections(rows, "formal")
    assert [r["key"] for r in ordered][-2:] == ["custom_a", "custom_b"]


def test_place_duplicate_default_key_falls_into_custom_cluster() -> None:
    rows = default_meta()
    rows.append(
        meta({"id": "education_dup", "key": "education", "displayName": "培训经历", "order": 6})
    )
    ordered = place_sections(rows, "formal")
    ids = [r["id"] for r in ordered]
    # First education owns the fixed slot; the duplicate lands in the cluster.
    assert ids.index("education") < ids.index("education_dup")
    assert ids.index("education_dup") > ids.index("personalProjects")


def test_branch_sequences_keep_selfeval_last() -> None:
    assert CANONICAL_SEQUENCE_FORMAL[-1] == SELFEVAL_SYMBOL
    assert CANONICAL_SEQUENCE_OTHER[-1] == SELFEVAL_SYMBOL


# --- accepted titles --------------------------------------------------------


def test_accepted_default_titles_fold_whitespace_and_case() -> None:
    assert is_accepted_default_title("education", " 教育背景 ")
    assert is_accepted_default_title("personalInfo", "personal info")
    assert not is_accepted_default_title("summary", "我的故事")
    assert not is_accepted_default_title("unknown", "Summary")


def test_accepted_zh_upload_aliases_cover_imported_headings() -> None:
    # Uploaded resumes name the summary block 个人优势/… and the skills block
    # 专业技能/技能/技术能力/…; all must count as non-renamed defaults so title
    # lock localizes them instead of treating them as custom sections.
    for title in ("个人优势", "核心优势", "竞争优势", "综合优势", "个人亮点"):
        assert is_accepted_default_title("summary", title)
    # 个人简介 belongs to the self-introduction group, never summary.
    assert not is_accepted_default_title("summary", "个人简介")
    # 个人总结 now parses into the self_evaluation custom block, never summary.
    assert not is_accepted_default_title("summary", "个人总结")
    # 个人评价 is a self-introduction alias, never the summary block.
    assert not is_accepted_default_title("summary", "个人评价")
    for title in ("专业技能", "职业技能", "核心技能", "专业能力", "技能", "技能清单",
                  "技术能力", "技术技能", "技能与荣誉"):
        assert is_accepted_default_title("additional", title)
    for title in ("实习经历", "从业经历", "职业履历", "任职经历", "工作履历", "职场经历"):
        assert is_accepted_default_title("workExperience", title)
    for title in ("项目经历", "项目经验", "项目履历", "重点项目"):
        assert is_accepted_default_title("personalProjects", title)
    for title in ("教育经历", "教育背景", "学历信息", "求学履历"):
        assert is_accepted_default_title("education", title)


def test_self_introduction_canonical_alias_set() -> None:
    from app.services.section_order import SELF_INTRODUCTION_TITLE_ALIASES

    assert {
        "自我介绍",
        "个人介绍",
        "个人简介",
        "个人简述",
        "个人评价",
    } <= SELF_INTRODUCTION_TITLE_ALIASES
    # Legacy honors headings have no alias set anymore: they render verbatim
    # as ordinary custom sections.
    import app.services.section_order as section_order_module

    assert not hasattr(section_order_module, "HONORS_CERTIFICATES_TITLE_ALIASES")


# --- emptiness --------------------------------------------------------------


def test_is_section_empty_matrix() -> None:
    empty_resume: dict[str, Any] = {
        "summary": "",
        "education": [{}],
        "workExperience": [],
        "personalProjects": [{"id": 1}],
        "additional": {"technicalSkills": ["  "]},
        "customSections": {"custom_1": {"sectionType": "text", "text": "   "}},
    }
    assert is_section_empty(meta({"key": "summary"}), empty_resume)
    assert is_section_empty(meta({"key": "education"}), empty_resume)
    assert is_section_empty(meta({"key": "workExperience"}), empty_resume)
    assert is_section_empty(meta({"key": "personalProjects"}), empty_resume)
    assert is_section_empty(meta({"key": "additional"}), empty_resume)
    assert is_section_empty(meta({"key": "custom_1"}), empty_resume)

    filled_resume: dict[str, Any] = {
        "summary": "hello",
        "education": [{"id": 1, "degree": "BSc"}],
        "workExperience": [{"id": 1, "title": "Dev"}],
        "personalProjects": [{"id": 1, "name": "X"}],
        "additional": {"languages": ["EN"]},
        "customSections": {"custom_1": {"sectionType": "stringList", "strings": ["a"]}},
    }
    for key in ("summary", "education", "workExperience", "personalProjects", "additional", "custom_1"):
        assert not is_section_empty(meta({"key": key}), filled_resume)


# --- canonicalization -------------------------------------------------------


def test_canonicalize_rewrites_scrambled_order_to_dense_formal() -> None:
    rows = default_meta()
    for i, row in enumerate(rows):
        row["order"] = 10 - i
    out = canonicalize_section_meta(
        {"sectionMeta": rows, "education": [edu("统招本科")], "summary": "x"}
    )
    assert [r["key"] for r in out] == [
        "personalInfo", "education", "summary", "additional", "workExperience", "personalProjects",
    ]
    assert [r["order"] for r in out] == [0, 1, 2, 3, 4, 5]


def test_canonicalize_other_branch_dense_order() -> None:
    out = canonicalize_section_meta(
        {"sectionMeta": default_meta(), "education": [edu("大专")]}
    )
    assert [r["key"] for r in out] == [
        "personalInfo", "summary", "additional", "workExperience", "personalProjects", "education",
    ]
    assert [r["order"] for r in out] == [0, 1, 2, 3, 4, 5]


def test_canonicalize_resets_renamed_default_but_keeps_alias() -> None:
    rows = [
        meta({"id": "summary", "key": "summary", "displayName": "My Story", "isDefault": True}),
        meta({"id": "education", "key": "education", "displayName": "教育经历", "isDefault": True}),
    ]
    out = canonicalize_section_meta({"sectionMeta": rows, "summary": "x"})
    by_key = {row["key"]: row for row in out}
    assert by_key["summary"]["displayName"] == "Summary"
    assert by_key["education"]["displayName"] == "教育经历"


def test_canonicalize_hides_empty_optional_but_keeps_required_and_data() -> None:
    rows = default_meta()
    rows.extend([
        meta({"id": "custom_empty", "key": "custom_empty", "displayName": "荣誉证书"}),
        meta({"id": "custom_filled", "key": "custom_filled", "displayName": "自我评价"}),
    ])
    resume: dict[str, Any] = {
        "sectionMeta": rows,
        "customSections": {
            "custom_empty": {"sectionType": "text", "text": ""},
            "custom_filled": {"sectionType": "text", "text": "本人评价……"},
        },
    }
    out = canonicalize_section_meta(resume)
    by_key = {row["key"]: row for row in out}
    assert by_key["summary"]["isVisible"] is False
    assert by_key["custom_empty"]["isVisible"] is False
    assert by_key["custom_filled"]["isVisible"] is True
    # Required blocks stay visible even when empty.
    assert by_key["education"]["isVisible"] is True
    assert by_key["workExperience"]["isVisible"] is True
    # Content data is preserved, never deleted.
    assert resume["customSections"]["custom_empty"]["text"] == ""


def test_canonicalize_keeps_hidden_rows_in_slot_with_dense_order() -> None:
    rows = default_meta()
    rows[3] = {**rows[3], "isVisible": False}  # education hidden
    out = canonicalize_section_meta(
        {"sectionMeta": rows, "education": [edu("统招本科")]}
    )
    assert [r["key"] for r in out] == [
        "personalInfo", "education", "summary", "additional", "workExperience", "personalProjects",
    ]
    assert [r["order"] for r in out] == [0, 1, 2, 3, 4, 5]


def test_canonicalize_falls_back_to_defaults_when_meta_missing() -> None:
    formal = canonicalize_section_meta({"education": [edu("统招硕士")]})
    assert [r["key"] for r in formal][:2] == ["personalInfo", "education"]
    other = canonicalize_section_meta({"education": [edu("大专")]})
    assert [r["key"] for r in other][:2] == ["personalInfo", "summary"]


def test_canonicalize_does_not_mutate_input() -> None:
    rows = default_meta()
    snapshot = [dict(row) for row in rows]
    canonicalize_section_meta({"sectionMeta": rows})
    assert rows == snapshot


# --- meta/content reconciliation (LLM omitted-row safety net) ----------------


def _education_with_school() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "institution": "湖北理工学院",
            "degree": "本科",
            "years": "",
            "description": ["专业: 计算机科学"],
        }
    ]


def test_canonicalize_heals_education_row_omitted_by_llm() -> None:
    # Observed upload failure mode (resume 1905c3db): education data present,
    # but the model emitted no education meta row, so every template skipped
    # the whole section.
    rows = [
        meta({"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info",
              "sectionType": "personalInfo", "isDefault": True, "order": 0}),
        meta({"id": "summary", "key": "summary", "displayName": "Summary",
              "isDefault": True, "order": 1}),
        meta({"id": "additional", "key": "additional", "displayName": "Skills & Awards",
              "sectionType": "stringList", "isDefault": True, "order": 2}),
        meta({"id": "workExperience", "key": "workExperience", "displayName": "Experience",
              "sectionType": "itemList", "isDefault": True, "order": 3}),
        meta({"id": "personalProjects", "key": "personalProjects", "displayName": "Projects",
              "sectionType": "itemList", "isDefault": True, "order": 4}),
        meta({"id": "self_evaluation", "key": "self_evaluation", "displayName": "自我评价",
              "isDefault": False, "order": 5}),
    ]
    resume: dict[str, Any] = {
        "sectionMeta": rows,
        "personalInfo": {"name": "熊威"},
        "summary": "个人优势内容",
        "additional": {"technicalSkills": ["Java"]},
        "workExperience": [{"company": "某公司"}],
        "education": _education_with_school(),
        "customSections": {
            "self_evaluation": {"sectionType": "text", "text": "自我评价内容"}
        },
    }
    out = canonicalize_section_meta(resume)
    by_key = {row["key"]: row for row in out}
    assert "education" in by_key
    healed = by_key["education"]
    assert healed["isVisible"] is True
    assert healed["isDefault"] is True
    assert healed["displayName"] == "Education"
    # Non-formal 本科 → other branch: education lands immediately before
    # self-evaluation, not second.
    keys = [row["key"] for row in out]
    assert keys == [
        "personalInfo",
        "summary",
        "additional",
        "workExperience",
        "personalProjects",
        "education",
        "self_evaluation",
    ]
    assert healed["order"] == 5


def test_healed_education_goes_second_in_formal_branch() -> None:
    rows = [
        meta({"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info",
              "sectionType": "personalInfo", "isDefault": True, "order": 0}),
        meta({"id": "summary", "key": "summary", "displayName": "Summary",
              "isDefault": True, "order": 1}),
    ]
    resume: dict[str, Any] = {
        "sectionMeta": rows,
        "education": [{"degree": "统招本科", "institution": "某大学"}],
        "summary": "x",
    }
    out = canonicalize_section_meta(resume)
    assert [row["key"] for row in out] == [
        "personalInfo",
        "education",
        "summary",
    ]


def test_heal_synthesises_rows_for_all_content_bearing_missing_defaults() -> None:
    resume: dict[str, Any] = {
        "sectionMeta": [],
        "personalInfo": {"name": "张三"},
        "summary": "个人优势",
        "workExperience": [{"company": "A 公司"}],
        "education": _education_with_school(),
        "personalProjects": [{"name": "项目甲"}],
        "additional": {"technicalSkills": ["Python"]},
    }
    # Empty meta already falls back to defaults; exercise the helper
    # directly with a partial custom row set to prove each missing,
    # content-bearing default key is synthesised.
    healed = heal_missing_default_sections(
        [meta({"id": "personalInfo", "key": "personalInfo"})], resume
    )
    assert {row["key"] for row in healed} == {
        "personalInfo",
        "summary",
        "workExperience",
        "education",
        "personalProjects",
        "additional",
    }
    for row in healed:
        if row["key"] != "personalInfo":
            assert row["isVisible"] is True
            assert row["isDefault"] is True


def test_heal_never_adds_rows_for_empty_blocks() -> None:
    resume: dict[str, Any] = {
        "sectionMeta": [],
        "personalInfo": {"name": "张三"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {"technicalSkills": []},
    }
    healed = heal_missing_default_sections(
        [meta({"id": "personalInfo", "key": "personalInfo"})], resume
    )
    assert [row["key"] for row in healed] == ["personalInfo"]


def test_heal_does_not_mutate_input_rows_or_default_meta() -> None:
    from app.schemas.models import DEFAULT_SECTION_META

    snapshot = [dict(row) for row in DEFAULT_SECTION_META]
    rows = [
        meta({"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info",
              "sectionType": "personalInfo", "isDefault": True, "order": 0}),
    ]
    rows_snapshot = [dict(row) for row in rows]
    healed = heal_missing_default_sections(
        rows, {"personalInfo": {"name": "张三"}, "education": _education_with_school()}
    )
    assert rows == rows_snapshot
    assert [dict(row) for row in DEFAULT_SECTION_META] == snapshot
    # the appended row is a distinct object from the DEFAULT_SECTION_META row
    education_rows = [row for row in healed if row["key"] == "education"]
    assert len(education_rows) == 1
    default_education = next(
        row for row in DEFAULT_SECTION_META if row["key"] == "education"
    )
    assert education_rows[0] is not default_education


# --- cross-tree locale parity ------------------------------------------------


def test_every_shipped_locale_title_is_an_accepted_alias() -> None:
    locales = ("en", "es", "fr", "ja", "ko", "pt-BR", "zh")
    assert len(list(FRONTEND_MESSAGES.glob("*.json"))) >= len(locales)
    for locale in locales:
        data = json.loads((FRONTEND_MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))
        sections = data["resume"]["sections"]
        for message_key, section_key in LOCALE_TITLE_KEYS:
            title = sections[message_key]
            assert is_accepted_default_title(section_key, title), (
                f"{locale}.json ships {message_key}={title!r} but the alias table "
                f"does not accept it for {section_key}"
            )
