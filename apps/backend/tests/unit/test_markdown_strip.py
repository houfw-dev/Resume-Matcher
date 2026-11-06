"""Deterministic stripping of leaked Markdown emphasis modifiers.

LLM extraction (and some older stored rows) occasionally emits ``**bold**``
fragments, sometimes split across fields. Resume renderers never interpret
Markdown, so the markers must disappear while their enclosed text survives.
Single ``*`` / ``_`` are only treated as emphasis in matched pairs.
"""

from typing import Any

import pytest

from app.services.parser import (
    dedupe_resume_lists,
    dedupe_string_values,
    strip_markdown_emphasis,
    strip_markdown_emphasis_deep,
    strip_markdown_formatting,
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("**Python**", "Python"),
        ("统招本科（**985&211)**", "统招本科（985&211)"),
        ("__bold__", "bold"),
        ("*italic*", "italic"),
        ("_italic_", "italic"),
        ("`code`", "code"),
        ("``code``", "code"),
        ("~~removed~~", "removed"),
        ("mixed **bold** and *italic*", "mixed bold and italic"),
        ("英语四级**", "英语四级"),
        ("**5年大型医院项目，3年电商）**", "5年大型医院项目，3年电商）"),
        ("a**", "a"),
        ("**", ""),
        ("~~", ""),
        ("__", ""),
        # Single-character emphasis boundary safety: multiplication, grades
        # and identifier underscores are not formatting.
        ("A*", "A*"),
        ("5*8", "5*8"),
        ("my_var", "my_var"),
        ("2 * 3 * 4", "2 * 3 * 4"),
        # Non-strings pass through untouched.
        ("", ""),
    ],
)
def test_strip_markdown_emphasis(source: Any, expected: Any) -> None:
    assert strip_markdown_emphasis(source) == expected


def test_strip_markdown_emphasis_preserves_non_strings() -> None:
    assert strip_markdown_emphasis(3) == 3
    assert strip_markdown_emphasis(None) is None


def test_strip_markdown_emphasis_deep_rebuilds_nested_containers() -> None:
    data = {
        "personalInfo": {"name": "**李勇**", "age": 38},
        "additional": {
            "technicalSkills": ["**Java**", "Python"],
            "languages": ["英语四级**"],
        },
        "workExperience": [
            {"company": "某**公司**", "description": ["**负责**架构", "plain"]}
        ],
    }
    result = strip_markdown_emphasis_deep(data)
    assert result == {
        "personalInfo": {"name": "李勇", "age": 38},
        "additional": {
            "technicalSkills": ["Java", "Python"],
            "languages": ["英语四级"],
        },
        "workExperience": [
            {"company": "某公司", "description": ["负责架构", "plain"]}
        ],
    }


def test_strip_markdown_emphasis_deep_does_not_mutate_input() -> None:
    data = {"a": ["**x**"], "b": {"c": "y__"}}
    snapshot = {"a": ["**x**"], "b": {"c": "y__"}}
    strip_markdown_emphasis_deep(data)
    assert data == snapshot


def test_strip_markdown_formatting_cleans_top_level_values() -> None:
    parsed = {"summary": "**优点**", "personalInfo": {"name": "王浩"}}
    returned = strip_markdown_formatting(parsed)
    assert returned is parsed
    assert parsed["summary"] == "优点"
    assert parsed["personalInfo"] == {"name": "王浩"}


def test_dedupe_string_values_keeps_first_occurrence_and_order() -> None:
    values = ["英语四级", " 英语四级", "日语N2"]
    assert dedupe_string_values(values) == ["英语四级", "日语N2"]


def test_dedupe_string_values_keeps_empty_entries_and_non_strings() -> None:
    assert dedupe_string_values(["Java", " Java ", "", "Python"]) == [
        "Java",
        "",
        "Python",
    ]
    mixed = ["Java", 2, "Java"]
    assert dedupe_string_values(mixed) is mixed


def test_dedupe_resume_lists_targets_rendered_fields_only() -> None:
    data = {
        "additional": {
            "languages": ["英语四级", " 英语四级 ", "日语N2"],
            "technicalSkills": ["Java", "Java", "Python"],
            "certificationsTraining": ["PMP", "PMP"],
            "awards": ["最佳员工"],
        },
        "customSections": {
            "hobbies": {"sectionType": "stringList", "strings": ["阅读", "阅读"]}
        },
        "workExperience": [
            # Index-aligned arrays must not be collapsed, even when a style
            # marker ("bullet") legitimately repeats.
            {
                "description": ["负责架构", "负责架构"],
                "descriptionStyles": ["bullet", "bullet"],
            }
        ],
    }

    dedupe_resume_lists(data)

    assert data["additional"]["languages"] == ["英语四级", "日语N2"]
    assert data["additional"]["technicalSkills"] == ["Java", "Python"]
    assert data["additional"]["certificationsTraining"] == ["PMP"]
    assert data["customSections"]["hobbies"]["strings"] == ["阅读"]
    assert data["workExperience"][0]["description"] == ["负责架构", "负责架构"]
    assert data["workExperience"][0]["descriptionStyles"] == ["bullet", "bullet"]


def test_strip_markdown_formatting_dedupes_collapsed_language_rows() -> None:
    parsed = {"additional": {"languages": ["英语四级**", "英语四级", "日语N2"]}}
    strip_markdown_formatting(parsed)
    assert parsed["additional"]["languages"] == ["英语四级", "日语N2"]
