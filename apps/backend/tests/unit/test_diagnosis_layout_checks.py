"""Tests for measured-layout support in the deterministic diagnosis checks.

When the client uploads a browser-measured render of the resume in the
builder's chosen template, items 1 (paragraph density) and 2 (page count)
must judge real pagination instead of the 46-chars/950-chars text estimates.
These tests pin:

* measured page/line values win over char estimates;
* measured-and-short lines are never re-flagged by the estimate fallback;
* the measured -> structured-source resolver's three attribution paths;
* locator parity with the frontend enumerator (flattened per entry);
* usability gates (template / page-size mismatch -> estimate fallback);
* the compact ``facts["layout"]`` packet.
"""

import pytest

from app.schemas.diagnosis import (
    LayoutLocatorIn,
    LayoutPointIn,
    RenderedLayoutIn,
    TemplateSettingsIn,
)
from app.services.diagnosis_checks import (
    _check_page_length,
    _check_paragraph_length,
    _located_line_table,
    _resolve_layout_point,
    run_objective_checks,
)
from app.services.diagnosis_rules import (
    RATING_CONFORM,
    RATING_NA,
    RATING_NONCONFORM,
)


def _resume(**overrides: object) -> dict:
    base: dict = {
        "personalInfo": {"name": "王浩"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
        "sectionMeta": [
            {"key": "personalInfo", "displayName": "基本信息", "isVisible": True},
            {"key": "workExperience", "displayName": "工作经历", "isVisible": True},
            {"key": "personalProjects", "displayName": "项目经验", "isVisible": True},
            {"key": "summary", "displayName": "个人优势", "isVisible": True},
        ],
    }
    base.update(overrides)
    return base


def _settings(**overrides: object) -> TemplateSettingsIn:
    return TemplateSettingsIn(**overrides)  # type: ignore[arg-type]


def _layout(**overrides: object) -> RenderedLayoutIn:
    base: dict = {"template": "swiss-single", "page_size": "A4", "page_count": 1}
    base.update(overrides)
    return RenderedLayoutIn(**base)  # type: ignore[arg-type]


def _point(
    locator: dict[str, object],
    visual_lines: int,
    *,
    text: str = "",
    location: str = "",
    page: int = 1,
) -> LayoutPointIn:
    return LayoutPointIn(
        locator=LayoutLocatorIn(**locator),  # type: ignore[arg-type]
        text=text,
        location=location,
        visual_lines=visual_lines,
        page=page,
    )


# --- item 2: measured page count -------------------------------------------


def test_page_length_measured_four_pages_nonconform() -> None:
    resume = _resume()
    finding = _check_page_length(resume, _layout(page_count=4))
    assert finding[0] == RATING_NONCONFORM
    assert "实际渲染" in finding[1]
    assert "4 页" in finding[1]
    assert "估算" not in finding[1]
    # The chosen template and paper size are named explicitly.
    assert "经典单栏" in finding[1]
    assert "A4" in finding[1]


def test_page_length_measured_three_pages_conform_empty_evidence() -> None:
    finding = _check_page_length(_resume(), _layout(page_count=3))
    assert finding == (RATING_CONFORM, "", "")


def test_page_length_without_layout_keeps_estimate_wording() -> None:
    # 4 pages worth of text (over 3 * 950 chars).
    long_text = "字" * (950 * 3 + 1)
    resume = _resume(summary=long_text)
    finding = _check_page_length(resume, None)
    assert finding[0] == RATING_NONCONFORM
    assert "估算" in finding[1]


# --- item 1: measured visual lines win over char estimates -----------------


def _long_line_resume() -> dict:
    # One 300-char point: 300/46 -> 7 estimated lines, so without a snapshot
    # the estimate path must flag it.
    long_line = "负责核心系统的设计与开发工作" * 15  # 210 CJK chars... ensure 300
    long_line = ("甲" * 300)
    return _resume(
        workExperience=[
            {
                "company": "某科技公司",
                "title": "高级工程师",
                "years": "2020.01 至今",
                "description": [long_line],
            }
        ]
    )


def test_paragraph_estimate_path_flags_300_char_line() -> None:
    finding = _check_paragraph_length(_long_line_resume(), None)
    assert finding[0] == RATING_NONCONFORM
    assert "单段约 7 行" in finding[1]


def test_paragraph_measured_short_line_overrides_char_estimate() -> None:
    resume = _long_line_resume()
    # The two-column/condensed template really wraps this point in 5 lines.
    layout = _layout(
        points=[
            _point(
                {
                    "kind": "entry",
                    "section": "workExperience",
                    "entry_index": 0,
                    "point_index": 0,
                },
                5,
                text="甲" * 120,
                location="工作经历 / 某科技公司 / 高级工程师",
            )
        ]
    )
    finding = _check_paragraph_length(resume, layout)
    assert finding == (RATING_CONFORM, "", "")


def test_paragraph_measured_long_point_nonconform_with_location() -> None:
    resume = _long_line_resume()
    layout = _layout(
        points=[
            _point(
                {
                    "kind": "entry",
                    "section": "workExperience",
                    "entry_index": 0,
                    "point_index": 0,
                },
                7,
                text="甲" * 120,
                location="工作经历 / 某科技公司 / 高级工程师",
            )
        ]
    )
    finding = _check_paragraph_length(resume, layout)
    assert finding[0] == RATING_NONCONFORM
    assert "实际渲染约 7 行" in finding[1]
    assert "工作经历 / 某科技公司 / 高级工程师" in finding[1]
    assert "甲甲甲" in finding[1]


def test_paragraph_unmeasured_long_line_still_falls_back_to_estimate() -> None:
    # Snapshot covers one short point; a second source line it could not align
    # must still be caught by the estimate fallback.
    long_line = "乙" * 300
    resume = _resume(
        workExperience=[
            {
                "company": "A 公司",
                "title": "工程师",
                "years": "2021.01 至今",
                "description": ["短点，只有十几个字", long_line],
            }
        ]
    )
    layout = _layout(
        points=[
            _point(
                {
                    "kind": "entry",
                    "section": "workExperience",
                    "entry_index": 0,
                    "point_index": 0,
                },
                1,
                text="短点，只有十几个字",
            )
        ]
    )
    finding = _check_paragraph_length(resume, layout)
    assert finding[0] == RATING_NONCONFORM
    assert "单段约 7 行" in finding[1]
    assert "乙乙乙" in finding[1]


def test_paragraph_no_text_blocks_is_na() -> None:
    assert _check_paragraph_length(_resume(), _layout())[0] == RATING_NA


# --- resolver: locator / text-search / unverified --------------------------


def test_resolve_locator_exact_for_all_four_kinds() -> None:
    resume = _resume(
        summary="个人优势第一条\n个人优势第二条",
        workExperience=[
            {
                "company": "甲公司",
                "title": "开发",
                "years": "2022.01 至今",
                "description": ["工作第一个要点\n工作第二个要点"],
            }
        ],
        personalProjects=[
            {"name": "智能平台", "years": "2023.01-2023.12", "description": ["项目第一点"]}
        ],
        customSections={
            "honors": {"sectionType": "text", "text": "荣誉正文第一行\n荣誉正文第二行"},
            "certs": {
                "sectionType": "itemList",
                "items": [
                    {"title": "证书条目", "description": ["证书条目第一点\n证书条目第二点"]}
                ],
            },
            "tags": {"sectionType": "stringList", "items": ["英语四级"]},
        },
    )
    table = _located_line_table(resume)

    cases = [
        ({"kind": "summary", "point_index": 1}, "个人优势第二条"),
        (
            {
                "kind": "entry",
                "section": "workExperience",
                "entry_index": 0,
                "point_index": 1,
            },
            "工作第二个要点",
        ),
        (
            {
                "kind": "entry",
                "section": "personalProjects",
                "entry_index": 0,
                "point_index": 0,
            },
            "项目第一点",
        ),
        ({"kind": "custom_text", "key": "honors", "point_index": 1}, "荣誉正文第二行"),
        (
            {
                "kind": "custom_item",
                "key": "certs",
                "entry_index": 0,
                "point_index": 1,
            },
            "证书条目第二点",
        ),
    ]
    for locator, expected_text in cases:
        point = _point(locator, 2, text=expected_text)
        resolved = _resolve_layout_point(resume, point, table)
        assert resolved.verified is True, locator
        assert resolved.line is not None
        assert expected_text in resolved.source_text
        assert resolved.line.text == expected_text


def test_entry_description_bullets_are_flattened_per_entry() -> None:
    # Frontend flattens description[*] lines and indexes them continuously.
    resume = _resume(
        workExperience=[
            {
                "company": "甲公司",
                "title": "开发",
                "years": "2022.01 至今",
                "description": ["第一行\n第二行", "第三行"],
            }
        ]
    )
    table = _located_line_table(resume)
    point = _point(
        {
            "kind": "entry",
            "section": "workExperience",
            "entry_index": 0,
            "point_index": 2,
        },
        1,
        text="第三行",
    )
    resolved = _resolve_layout_point(resume, point, table)
    assert resolved.verified is True
    assert resolved.line is not None
    assert resolved.line.text == "第三行"


def test_stringlist_custom_section_not_enumerated() -> None:
    resume = _resume(
        customSections={"tags": {"sectionType": "stringList", "items": ["英语四级", "英语六级"]}}
    )
    assert _located_line_table(resume) == []


def test_resolve_falls_back_to_full_text_search() -> None:
    resume = _resume(
        workExperience=[
            {
                "company": "甲公司",
                "title": "开发",
                "years": "2022.01-2023.01",
                "description": ["第一家公司的独特要点内容"],
            },
            {
                "company": "乙公司",
                "title": "高级开发",
                "years": "2023.02 至今",
                "description": ["第二家公司的普通要点"],
            },
        ]
    )
    table = _located_line_table(resume)
    # Client sends entry_index=1 (display order); the text actually lives in
    # stored entry 0. Locator-exact fails, text search must find it.
    point = _point(
        {
            "kind": "entry",
            "section": "workExperience",
            "entry_index": 1,
            "point_index": 0,
        },
        3,
        text="第一家公司的独特要点内容",
    )
    resolved = _resolve_layout_point(resume, point, table)
    assert resolved.verified is True
    assert resolved.line is not None
    assert "甲公司" in resolved.location


def test_resolve_unverified_when_text_unknown() -> None:
    resume = _resume(summary="真实存在的个人优势内容")
    table = _located_line_table(resume)
    point = _point(
        {"kind": "summary", "point_index": 0},
        9,
        text="快照里有但原文找不到的内容",
        location="个人优势",
    )
    resolved = _resolve_layout_point(resume, point, table)
    assert resolved.verified is False
    assert resolved.line is None
    assert resolved.source_text == "快照里有但原文找不到的内容"
    assert resolved.location == "个人优势"


def test_paragraph_unverified_evidence_is_tagged() -> None:
    resume = _resume(summary="真实存在的个人优势内容")
    layout = _layout(
        points=[
            _point(
                {"kind": "summary", "point_index": 0},
                9,
                text="快照里有但原文找不到的内容",
                location="个人优势",
            )
        ]
    )
    finding = _check_paragraph_length(resume, layout)
    assert finding[0] == RATING_NONCONFORM
    assert "（内容位置待核）" in finding[1]
    assert "实际渲染约 9 行" in finding[1]


# --- run_objective_checks wiring + usability gates -------------------------


def test_run_objective_checks_uses_measured_layout() -> None:
    resume = _long_line_resume()
    settings = _settings()
    layout = _layout(
        page_count=4,
        points=[
            _point(
                {
                    "kind": "entry",
                    "section": "workExperience",
                    "entry_index": 0,
                    "point_index": 0,
                },
                5,
                text="甲" * 120,
                location="工作经历 / 某科技公司",
            )
        ],
    )
    verdicts, facts = run_objective_checks(
        resume, rendered_layout=layout, template_settings=settings
    )
    assert verdicts[2][0] == RATING_NONCONFORM
    assert "实际渲染" in verdicts[2][1]
    # Measured 5 lines: conform even though the estimate says 7.
    order_para_evidence = verdicts[1][1]
    assert "密度过高" not in order_para_evidence
    assert facts["layout"]["page_count"] == 4
    assert facts["layout"]["points_measured"] == 1
    assert facts["layout"]["long_points"] == []


def test_run_objective_checks_layout_facts_shape() -> None:
    long_point = _point(
        {"kind": "summary", "point_index": 0},
        8,
        text="很长的个人优势",
        location="个人优势",
        page=2,
    )
    layout = _layout(
        page_count=2,
        two_column=True,
        template="swiss-two-column",
        points=[long_point],
        sections=[],
    )
    settings = _settings(template="swiss-two-column")
    _, facts = run_objective_checks(
        _resume(summary="很长的个人优势"),
        rendered_layout=layout,
        template_settings=settings,
    )
    packet = facts["layout"]
    assert set(packet) == {
        "template",
        "page_size",
        "two_column",
        "page_count",
        "points_measured",
        "header",
        "sections",
        "long_points",
    }
    assert packet["template"] == "swiss-two-column"
    assert packet["two_column"] is True
    assert packet["header"] == {"cell_count": 0, "rows": 0, "height_px": 0}
    assert packet["long_points"] == [
        {"location": "个人优势", "visual_lines": 8, "page": 2}
    ]


def test_run_objective_checks_without_snapshot_has_no_layout_fact() -> None:
    _, facts = run_objective_checks(_resume())
    assert "layout" not in facts


def test_template_mismatch_rejects_snapshot() -> None:
    # Snapshot claims vivid while the request settings say swiss-single: the
    # measurements cannot belong to the chosen template — fall back silently.
    resume = _long_line_resume()
    layout = _layout(template="vivid", page_count=9, points=[])
    verdicts, facts = run_objective_checks(
        resume, rendered_layout=layout, template_settings=_settings()
    )
    # 300-char line would be nonconform under the estimate path; the 9-page
    # snapshot must NOT be trusted.
    assert "估算" in verdicts[2][1] or verdicts[2][1] == ""
    assert "实际渲染" not in verdicts[2][1]
    assert "layout" not in facts


def test_page_size_mismatch_rejects_snapshot() -> None:
    layout = _layout(page_size="LETTER", page_count=9)
    settings = _settings(pageSize="A4")
    verdicts, facts = run_objective_checks(
        _resume(), rendered_layout=layout, template_settings=settings
    )
    assert "实际渲染" not in verdicts[2][1]
    assert "layout" not in facts


def test_settings_without_snapshot_uses_estimates() -> None:
    verdicts, facts = run_objective_checks(
        _long_line_resume(), template_settings=_settings()
    )
    assert "layout" not in facts
    assert verdicts[1][0] == RATING_NONCONFORM


# --- pydantic bounds --------------------------------------------------------


def test_layout_page_count_bounds() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        RenderedLayoutIn(template="swiss-single", page_size="A4", page_count=0)
    with pytest.raises(pydantic.ValidationError):
        RenderedLayoutIn(template="swiss-single", page_size="A4", page_count=13)


def test_layout_unknown_fields_ignored() -> None:
    layout = RenderedLayoutIn(
        template="swiss-single",  # type: ignore[call-arg]
        page_size="A4",
        page_count=2,
        injected="whatever",
    )
    assert layout.page_count == 2
