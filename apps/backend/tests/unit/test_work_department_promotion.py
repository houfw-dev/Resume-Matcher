"""Deterministic promotion of a standalone department line into ``department``.

Weak models file the org unit on its own source line ("武汉软通动力 /
全球资金部") as a "plain" work description row instead of the ``department``
field. ``promote_work_departments`` is the parse-time safety net; the frontend
renderer mirrors the same recognition for already-stored resumes.
"""

import pytest

from app.services.parser import _looks_like_department_line, promote_work_departments


def _entry(
    *,
    department: str | None = None,
    description: list[str] | None = None,
    styles: list[str] | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "company": "武汉软通动力",
        "title": "Java高级开发",
        "years": "2023.09 - 2026.04",
        "department": department,
        "description": description if description is not None else [],
    }
    if styles is not None:
        entry["descriptionStyles"] = styles
    return entry


def test_promotes_a_sole_plain_department_row() -> None:
    data = {
        "workExperience": [
            _entry(description=["全球资金部"], styles=["plain"]),
            _entry(description=["研发部"], styles=["plain"]),
            _entry(description=["云计算集成部"], styles=["plain"]),
        ]
    }

    promote_work_departments(data)

    entries = data["workExperience"]
    assert [entry["department"] for entry in entries] == [
        "全球资金部",
        "研发部",
        "云计算集成部",
    ]
    assert all(entry["description"] == [] for entry in entries)
    assert all(entry["descriptionStyles"] == [] for entry in entries)


def test_promotes_only_the_first_plain_row_and_keeps_following_bullets() -> None:
    data = {
        "workExperience": [
            _entry(
                description=["支付事业部", "负责清结算系统重构", "性能提升 2.5 倍"],
                styles=["plain", "bullet", "bullet"],
            )
        ]
    }

    promote_work_departments(data)

    entry = data["workExperience"][0]
    assert entry["department"] == "支付事业部"
    assert entry["description"] == ["负责清结算系统重构", "性能提升 2.5 倍"]
    assert entry["descriptionStyles"] == ["bullet", "bullet"]


def test_existing_department_field_is_never_overwritten() -> None:
    data = {
        "workExperience": [
            _entry(
                department="人工填写部门",
                description=["全球资金部"],
                styles=["plain"],
            )
        ]
    }

    promote_work_departments(data)

    entry = data["workExperience"][0]
    assert entry["department"] == "人工填写部门"
    assert entry["description"] == ["全球资金部"]


def test_bullet_styled_department_like_row_is_not_promoted() -> None:
    data = {"workExperience": [_entry(description=["研发部"], styles=["bullet"])]}

    promote_work_departments(data)

    entry = data["workExperience"][0]
    assert entry["department"] is None
    assert entry["description"] == ["研发部"]


def test_missing_styles_defaults_to_bullet_and_does_not_promote() -> None:
    data = {"workExperience": [{"company": "C", "department": None, "description": ["研发部"]}]}

    promote_work_departments(data)

    entry = data["workExperience"][0]
    assert entry["department"] is None
    assert entry["description"] == ["研发部"]


def test_sentence_like_plain_row_is_not_promoted() -> None:
    data = {
        "workExperience": [
            _entry(
                description=["对接外部合作部完成联调，推动项目上线。"],
                styles=["plain"],
            )
        ]
    }

    promote_work_departments(data)

    entry = data["workExperience"][0]
    assert entry["department"] is None
    assert entry["description"] == ["对接外部合作部完成联调，推动项目上线。"]


@pytest.mark.parametrize(
    "row",
    [
        "全球资金部",
        "研发部",
        "云计算集成部",
        "支付事业部",
        "保险事业群",
        "平台研发中心",
        "基础架构组",
        "评审一室",
        "Payments Department",
        "Platform Team",
        "Core Division",
    ],
)
def test_department_line_recognizer_accepts_org_units(row: str) -> None:
    assert _looks_like_department_line(row)


@pytest.mark.parametrize(
    "row",
    [
        "负责清结算系统的设计与研发工作",
        "对接外部合作部完成联调，推动项目上线。",
        "性能提升 2.5 倍",
        "JDK 1.8 升级",
        "",
        "部",
    ],
)
def test_department_line_recognizer_rejects_non_org_text(row: str) -> None:
    assert not _looks_like_department_line(row)


def test_no_work_section_is_a_noop() -> None:
    data: dict[str, object] = {"personalProjects": []}
    assert promote_work_departments(data) is data
