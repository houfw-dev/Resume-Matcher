"""Read-time self-healing in :func:`normalize_resume_data`.

Old stored rows bypass the current parse pipeline: they may still carry
leaked Markdown markers and list entries that collapse into duplicates once
those markers are removed on read (observed: additional.languages
["英语四级", "英语四级**"] rendering twice in the header fact grid).
"""

import copy
from typing import Any

from app.schemas.models import normalize_resume_data


def test_normalize_dedupes_language_rows_after_stripping_markers() -> None:
    data: dict[str, Any] = {
        "personalInfo": {"name": "李勇"},
        "additional": {"languages": ["英语四级", "英语四级**", "日语N2"]},
    }

    normalized = normalize_resume_data(data)

    assert normalized["additional"]["languages"] == ["英语四级", "日语N2"]


def test_normalize_dedupes_skills_with_surrounding_whitespace() -> None:
    data: dict[str, Any] = {
        "personalInfo": {"name": "王浩"},
        "additional": {"technicalSkills": ["Java", " Java ", "Python"]},
    }

    normalized = normalize_resume_data(data)

    assert normalized["additional"]["technicalSkills"] == ["Java", "Python"]


def test_normalize_strips_markers_and_adds_section_meta() -> None:
    data: dict[str, Any] = {
        "personalInfo": {"name": "**王浩**", "educationLevel": "统招本科（**985&211)**"},
        "additional": {"languages": ["英语四级**"]},
    }

    normalized = normalize_resume_data(data)

    assert normalized["personalInfo"]["name"] == "王浩"
    assert normalized["personalInfo"]["educationLevel"] == "统招本科（985&211)"
    assert isinstance(normalized["sectionMeta"], list)
    assert normalized["sectionMeta"]


def test_normalize_heals_misfiled_work_credentials() -> None:
    # Stored work descriptions with trapped labeled credential rows heal on
    # read/save even though the upload predates the parser rule.
    data: dict[str, Any] = {
        "personalInfo": {"name": "张三"},
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": "Acme",
                "description": ["奖项：国家奖学金", "语言：英语六级"],
                "descriptionStyles": ["bullet", "bullet"],
            }
        ],
    }

    normalized = normalize_resume_data(data)

    work = normalized["workExperience"][0]
    assert work["description"] == []
    assert work["descriptionStyles"] == []
    assert normalized["additional"]["awards"] == ["国家奖学金"]
    assert normalized["additional"]["languages"] == ["英语六级"]


def test_normalize_reconciles_custom_section_container_mismatch() -> None:
    # A stringList custom section whose entries were stored as items renders
    # as a title-only block in every template. The read-path heal migrates
    # the item titles into strings so the content becomes visible, without
    # requiring a re-upload (real case: leo resume's 「其它」 block).
    data: dict[str, Any] = {
        "personalInfo": {"name": "张三"},
        "customSections": {
            "other": {
                "sectionType": "stringList",
                "strings": None,
                "items": [
                    {"id": 1, "title": "GitHub 开源项目：https://example.com/repo"},
                    {"id": 2, "title": "个人技术站点：https://example.com/blog"},
                ],
                "text": None,
            }
        },
        "sectionMeta": [
            {
                "id": "other",
                "key": "other",
                "displayName": "其它",
                "sectionType": "stringList",
                "isDefault": False,
                "isVisible": True,
                "order": 0,
            }
        ],
    }

    normalized = normalize_resume_data(copy.deepcopy(data))

    section = normalized["customSections"]["other"]
    assert section["strings"] == [
        "GitHub 开源项目：https://example.com/repo",
        "个人技术站点：https://example.com/blog",
    ]
    assert section["items"] is None
    meta = next(row for row in normalized["sectionMeta"] if row["key"] == "other")
    assert meta["isVisible"] is True


def test_normalize_heals_presentation_hygiene_on_read() -> None:
    # Uploads predating the hygiene pass heal on read: bullet rows lose their
    # trailing sentence period (plain prose keeps it), blank rows/styles drop
    # in lockstep, summary lines trim and unify endings.
    data: dict[str, Any] = {
        "personalInfo": {"name": " 张三 "},
        "summary": " 十年研发经验。\n\n主导架构演进。\n",
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": " Acme ",
                "description": ["负责支付系统。", " ", "散文式职责说明。"],
                "descriptionStyles": ["bullet", "plain", "plain"],
            }
        ],
        "additional": {"technicalSkills": [" Java。", ""]},
    }

    normalized = normalize_resume_data(data)

    assert normalized["personalInfo"]["name"] == "张三"
    assert normalized["summary"] == "十年研发经验\n主导架构演进"
    work = normalized["workExperience"][0]
    assert work["company"] == "Acme"
    assert work["description"] == ["负责支付系统", "散文式职责说明。"]
    assert work["descriptionStyles"] == ["bullet", "plain"]
    assert normalized["additional"]["technicalSkills"] == ["Java"]


def test_normalize_is_deep_equal_idempotent() -> None:
    data: dict[str, Any] = {
        "personalInfo": {"name": "张三"},
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": "Acme",
                "description": ["奖项：", "国家奖学金", "工作职责：", "负责支付系统"],
                "descriptionStyles": ["label", "bullet", "label", "bullet"],
            }
        ],
    }

    normalize_resume_data(data)
    snapshot = copy.deepcopy(data)
    normalize_resume_data(data)

    assert data == snapshot
