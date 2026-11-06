"""Unit tests for the fine-tune scope gate, prompts and service pipeline."""

import copy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.fine_tune import FineTuneScope
from app.schemas.models import ResumeData
from app.services import fine_tune
from app.services.fine_tune import (
    build_scope_description,
    restrict_to_scope,
    run_fine_tune,
)
from app.services.parser import normalize_text_hygiene


def _canonical(data: dict[str, Any]) -> dict[str, Any]:
    # Mirrors the fine-tune output boundary: presentation hygiene runs before
    # schema validation (bullet endings unified, summary endings stripped).
    return ResumeData.model_validate(
        normalize_text_hygiene(copy.deepcopy(data))
    ).model_dump()


def _source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Jane Doe", "email": "jane@example.com"},
        "summary": "Backend engineer with Python experience.",
        "workExperience": [
            {
                "id": 1,
                "title": "Senior Engineer",
                "company": "Acme",
                "years": "2021 - Present",
                "description": ["Built APIs", "Led migrations"],
                "descriptionStyles": ["bullet", "bullet"],
            },
            {
                "id": 2,
                "title": "Engineer",
                "company": "Startup",
                "years": "2018 - 2020",
                "description": ["Wrote tests"],
                "descriptionStyles": ["bullet"],
            },
        ],
        "education": [
            {"id": 1, "institution": "MIT", "degree": "BSc", "years": "2014 - 2018"}
        ],
        "personalProjects": [],
        "additional": {
            "technicalSkills": ["Python"],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
        "sectionMeta": [
            {
                "id": "workExperience",
                "key": "workExperience",
                "displayName": "Work Experience",
                "sectionType": "itemList",
                "isDefault": True,
                "isVisible": True,
                "order": 0,
            }
        ],
    }


# --- Scope schema ----------------------------------------------------------


def test_scope_rejects_unknown_tokens() -> None:
    with pytest.raises(ValidationError):
        FineTuneScope(kind="modules", targets=["personalInfo"])


def test_scope_kind_combinations() -> None:
    assert FineTuneScope(kind="all").targets == []
    with pytest.raises(ValidationError):
        FineTuneScope(kind="all", targets=["summary"])
    with pytest.raises(ValidationError):
        FineTuneScope(kind="modules", targets=[])
    scope = FineTuneScope(
        kind="modules", targets=["work_1", "summary", "work_1"]
    )
    assert scope.targets == ["work_1", "summary"]


# --- Scope description -----------------------------------------------------


def test_build_scope_description_lists_modules_and_item_labels() -> None:
    source = _source()
    description = build_scope_description(source, "modules", ["summary", "work_1"])
    assert "summary" in description
    assert "workExperience[1]" in description
    assert "Engineer" in description and "Startup" in description
    assert build_scope_description(source, "all", []).startswith("ALL sections")


# --- restrict_to_scope -----------------------------------------------------


def test_all_scope_replaces_sections_but_freezes_identity_and_meta() -> None:
    source = _source()
    candidate = copy.deepcopy(source)
    candidate["summary"] = "A completely rewritten summary."
    candidate["personalInfo"]["name"] = "Impostor"
    candidate["sectionMeta"].append({"id": "x"})

    result, ignored, _ = restrict_to_scope(source, candidate, "all", [])
    canonical = _canonical(source)

    # Hygiene strips the trailing period: summary lines render as list points.
    assert result["summary"] == "A completely rewritten summary"
    assert result["personalInfo"] == canonical["personalInfo"]
    assert result["sectionMeta"] == canonical["sectionMeta"]
    assert ignored == []


def test_module_scope_freezes_unselected_sections() -> None:
    source = _source()
    candidate = copy.deepcopy(source)
    candidate["summary"] = "New summary."
    candidate["workExperience"][0]["description"] = ["Newly rewritten bullet"]

    result, _, _ = restrict_to_scope(source, candidate, "modules", ["summary"])

    assert result["summary"] == "New summary"
    assert result["workExperience"] == _canonical(source)["workExperience"]


def test_item_scope_replaces_only_the_identity_matched_entry_even_if_reordered() -> (
    None
):
    source = _source()
    candidate = copy.deepcopy(source)
    # Model reordered entries: id 2 now first with rewritten descriptions.
    candidate["workExperience"] = [
        candidate["workExperience"][1],
        candidate["workExperience"][0],
    ]
    candidate["workExperience"][0]["description"] = ["Wrote tests at 800 stores"]

    result, ignored, _ = restrict_to_scope(source, candidate, "modules", ["work_1"])
    canonical = _canonical(source)

    assert ignored == []
    assert [entry["id"] for entry in result["workExperience"]] == [1, 2]
    assert result["workExperience"][0] == canonical["workExperience"][0]
    assert result["workExperience"][1]["description"] == [
        "Wrote tests at 800 stores"
    ]


def test_item_scope_ignores_out_of_range_and_unmatched_tokens() -> None:
    source = _source()
    candidate = copy.deepcopy(source)

    result, ignored, _ = restrict_to_scope(source, candidate, "modules", ["work_9"])

    assert ignored == ["work_9"]
    assert result["workExperience"] == _canonical(source)["workExperience"]


def test_whole_section_token_supersedes_item_tokens() -> None:
    source = _source()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["Changed"]

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["workExperience", "work_0"]
    )

    assert ignored == []
    assert result["workExperience"][0]["description"] == ["Changed"]


# --- Label-region tokens (project_N:<region>, work_N:<region>) -------------


def _labeled_project_source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Hou Fuwen"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [
            {
                "id": 1,
                "name": "超鹿运动",
                "role": "后端开发",
                "years": "2023 - 2024",
                "description": [
                    "技术栈：",
                    "Java",
                    "Spring Boot",
                    "Redis",
                    "项目背景：",
                    "面向连锁健身场景的数字化平台。",
                    "项目职责：",
                    "负责核心模块的后端设计与开发。",
                    "统筹需求拆解与版本交付。",
                    "项目亮点：",
                    "订单重构方案落地，降低迁移风险。",
                    "核心接口响应耗时降低四成。",
                ],
                "descriptionStyles": [
                    "label",
                    "plain",
                    "plain",
                    "plain",
                    "label",
                    "plain",
                    "label",
                    "bullet",
                    "bullet",
                    "label",
                    "bullet",
                    "bullet",
                ],
            }
        ],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


_STAR_HIGHLIGHT_1 = (
    "S：旧订单系统耦合严重迁移风险高；T：主导订单重构方案设计；"
    "A：制定灰度切换与回滚策略；R：重构方案平稳落地，显著降低迁移风险。"
)
_STAR_HIGHLIGHT_2 = (
    "S：核心接口响应耗时偏高；T：负责接口性能优化；"
    "A：引入缓存并改造慢查询；R：核心接口响应耗时降低四成。"
)


def test_scope_accepts_region_tokens() -> None:
    scope = FineTuneScope(
        kind="modules", targets=["project_0:highlights", "work_2:achievements"]
    )
    assert scope.targets == ["project_0:highlights", "work_2:achievements"]


@pytest.mark.parametrize(
    "token",
    [
        "work_0:bogus",
        "project_x:highlights",
        "project_0:unknown",
        "project_:highlights",
        "education_0:duties",
    ],
)
def test_scope_rejects_malformed_region_tokens(token: str) -> None:
    with pytest.raises(ValidationError):
        FineTuneScope(kind="modules", targets=[token])


def test_region_overlay_replaces_only_rows_owned_by_the_label() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    candidate["personalProjects"][0]["description"][10] = _STAR_HIGHLIGHT_1
    candidate["personalProjects"][0]["description"][11] = _STAR_HIGHLIGHT_2

    result, ignored, dropped = restrict_to_scope(
        source, candidate, "modules", ["project_0:highlights"]
    )

    assert ignored == []
    assert dropped is False
    canonical = _canonical(source)
    expected = copy.deepcopy(canonical)
    # STAR rows land on bullet styles, so hygiene strips their final period.
    expected["personalProjects"][0]["description"][10] = _STAR_HIGHLIGHT_1[:-1]
    expected["personalProjects"][0]["description"][11] = _STAR_HIGHLIGHT_2[:-1]
    assert result == expected
    # The label row itself and every other region are byte-identical...
    entry = result["personalProjects"][0]
    assert entry["description"][9] == "项目亮点："
    assert entry["description"][:9] == canonical["personalProjects"][0]["description"][:9]
    # ...and styles are taken from the source: plain tech/background rows are
    # never promoted to bullets, label styles survive.
    assert entry["descriptionStyles"] == canonical["personalProjects"][0][
        "descriptionStyles"
    ]


def test_region_overlay_unions_two_regions_of_one_entry() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    rows = candidate["personalProjects"][0]["description"]
    rows[1] = "Java 21"  # inside techStack
    rows[10] = _STAR_HIGHLIGHT_1  # inside highlights
    rows[11] = _STAR_HIGHLIGHT_2

    result, ignored, dropped = restrict_to_scope(
        source,
        candidate,
        "modules",
        ["project_0:techStack", "project_0:highlights"],
    )

    assert ignored == []
    assert dropped is False
    final_rows = result["personalProjects"][0]["description"]
    assert final_rows[1] == "Java 21"
    assert final_rows[10] == _STAR_HIGHLIGHT_1[:-1]
    assert final_rows[11] == _STAR_HIGHLIGHT_2[:-1]
    # Rows between the two regions (background index 5, duties 7-8) stay frozen.
    canonical = _canonical(source)["personalProjects"][0]["description"]
    for index in (0, 2, 3, 4, 5, 6, 7, 8, 9):
        assert final_rows[index] == canonical[index]


def test_item_token_supersedes_region_tokens_for_same_entry() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    candidate["personalProjects"][0]["description"][5] = "改写后的项目背景。"

    result, ignored, dropped = restrict_to_scope(
        source,
        candidate,
        "modules",
        ["project_0", "project_0:highlights"],
    )

    assert ignored == []
    assert dropped is False
    assert result["personalProjects"][0] == _canonical(candidate)["personalProjects"][0]


def test_whole_section_token_supersedes_region_tokens() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    candidate["personalProjects"][0]["description"][5] = "改写后的项目背景。"

    result, ignored, _ = restrict_to_scope(
        source,
        candidate,
        "modules",
        ["personalProjects", "project_0:highlights"],
    )

    assert ignored == []
    assert result["personalProjects"] == _canonical(candidate)["personalProjects"]


def test_region_token_ignored_when_region_absent_or_entry_out_of_range() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)

    result, ignored, dropped = restrict_to_scope(
        source,
        candidate,
        "modules",
        ["project_0:achievements", "project_9:highlights"],
    )

    assert ignored == ["project_0:achievements", "project_9:highlights"]
    assert dropped is False
    assert result == _canonical(source)


def test_region_overlay_drops_appended_rows_and_sets_flag() -> None:
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    entry = candidate["personalProjects"][0]
    entry["description"][10] = _STAR_HIGHLIGHT_1
    entry["description"][11] = _STAR_HIGHLIGHT_2
    # Model produced two extra STAR rows; region edits keep the source count.
    entry["description"].extend(["追加的亮点行甲。", "追加的亮点行乙。"])
    entry["descriptionStyles"].extend(["bullet", "bullet"])

    result, ignored, dropped = restrict_to_scope(
        source, candidate, "modules", ["project_0:highlights"]
    )

    assert ignored == []
    assert dropped is True
    final_entry = result["personalProjects"][0]
    assert len(final_entry["description"]) == 12
    assert final_entry["description"][10] == _STAR_HIGHLIGHT_1[:-1]
    assert final_entry["description"][11] == _STAR_HIGHLIGHT_2[:-1]
    assert "追加的亮点行甲。" not in final_entry["description"]
    assert "追加的亮点行乙。" not in final_entry["description"]


def _nested_heads_project_source() -> dict[str, Any]:
    # Shape of the reported resume: a 项目亮点 module whose unknown bold colon
    # heads （重大生产环境问题解决：/性能调优：) own plain detail paragraphs.
    return {
        "personalInfo": {"name": "Hou Fuwen"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [
            {
                "id": 1,
                "name": "包块结算系统项目",
                "role": "后端开发",
                "years": "2023 - 2025",
                "description": [
                    "项目背景：",
                    "面向医保包块结算场景的系统平台。",
                    "技术栈：",
                    "Java",
                    "项目职责：",
                    "负责核心结算模块开发。",
                    "项目亮点：",
                    "重大生产环境问题解决：",
                    "成功解决明细下载系统卡死问题。",
                    "明细下载过程中超时重试机制生效。",
                    "性能调优：",
                    "通过索引优化和SQL重构降低耗时。",
                    "利用Redis做缓存缩短响应时间。",
                ],
                "descriptionStyles": [
                    "label",
                    "plain",
                    "label",
                    "plain",
                    "label",
                    "bullet",
                    "label",
                    "label",
                    "plain",
                    "plain",
                    "label",
                    "plain",
                    "plain",
                ],
            }
        ],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


def test_region_overlay_honours_plain_to_bullet_flip_only_inside_region() -> None:
    source = _nested_heads_project_source()
    candidate = copy.deepcopy(source)
    styles = candidate["personalProjects"][0]["descriptionStyles"]
    # The model answers "render the sub-head details as an ordered list":
    # texts untouched, the four plain detail rows flipped to bullet.
    for index in (8, 9, 11, 12):
        styles[index] = "bullet"

    result, ignored, dropped = restrict_to_scope(
        source, candidate, "modules", ["project_0:highlights"]
    )

    assert ignored == []
    assert dropped is False
    entry = result["personalProjects"][0]
    # Source-canonical shape, plus the final periods stripped from the four
    # rows flipped to bullet (indices 8/9/11/12); the pre-existing bullet row
    # 5 was already stripped by the canonical helper.
    expected_rows = _canonical(source)["personalProjects"][0]["description"]
    for index in (8, 9, 11, 12):
        assert expected_rows[index].endswith("。")
        expected_rows[index] = expected_rows[index][:-1]
    assert entry["description"] == expected_rows
    assert entry["descriptionStyles"] == [
        "label",
        "plain",
        "label",
        "plain",
        "label",
        "bullet",
        "label",
        "label",
        "bullet",
        "bullet",
        "label",
        "bullet",
        "bullet",
    ]


def test_region_overlay_never_moves_label_styles() -> None:
    source = _nested_heads_project_source()
    candidate = copy.deepcopy(source)
    styles = candidate["personalProjects"][0]["descriptionStyles"]
    # Injection attempts: promote a nested head to bullet and demote a detail
    # row to label. Neither may survive the overlay.
    styles[7] = "bullet"
    styles[8] = "label"

    result, _, _ = restrict_to_scope(
        source, candidate, "modules", ["project_0:highlights"]
    )

    final_styles = result["personalProjects"][0]["descriptionStyles"]
    assert final_styles[7] == "label"
    assert final_styles[8] == "plain"
    assert final_styles == _canonical(source)["personalProjects"][0][
        "descriptionStyles"
    ]


def test_build_scope_description_names_region_label_and_row_count() -> None:
    source = _canonical(_labeled_project_source())

    description = build_scope_description(
        source, "modules", ["project_0:highlights", "project_0:achievements"]
    )

    assert 'sub-module "项目亮点："' in description
    assert "(project highlights)" in description
    assert "rewrite ONLY the 2 row(s)" in description
    assert 'no "achievements" sub-module in this entry' in description


def test_work_region_overlay_replaces_only_achievement_rows() -> None:
    source = {
        "personalInfo": {"name": "Li Si"},
        "summary": "",
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": "Acme",
                "years": "2020 - 2024",
                "description": [
                    "工作职责：",
                    "负责日常后端开发。",
                    "工作业绩：",
                    "获评年度优秀员工。",
                ],
                "descriptionStyles": ["label", "bullet", "label", "bullet"],
            }
        ],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][1] = "职责行不应被采纳。"
    candidate["workExperience"][0]["description"][3] = "主导核心系统升级，获评年度优秀员工。"

    result, ignored, dropped = restrict_to_scope(
        source, candidate, "modules", ["work_0:achievements"]
    )

    assert ignored == []
    assert dropped is False
    rows = result["workExperience"][0]["description"]
    # Both duty/achievement rows are bullets, so hygiene drops the final
    # period; the frozen row keeps its source text minus that period and the
    # adopted candidate row is punctuated the same way.
    assert rows[0] == "工作职责："
    assert rows[1] == "负责日常后端开发"
    assert rows[2] == "工作业绩："
    assert rows[3] == "主导核心系统升级，获评年度优秀员工"
    assert result["workExperience"][0]["descriptionStyles"] == [
        "label",
        "bullet",
        "label",
        "bullet",
    ]


async def test_run_fine_tune_emits_drop_warning_for_region_extra_rows() -> None:
    resume = {"processed_data": _labeled_project_source(), "original_markdown": ""}
    candidate = copy.deepcopy(_labeled_project_source())
    entry = candidate["personalProjects"][0]
    entry["description"][10] = _STAR_HIGHLIGHT_1
    entry["description"][11] = _STAR_HIGHLIGHT_2
    entry["description"].extend(["追加的亮点行甲。", "追加的亮点行乙。"])
    entry["descriptionStyles"].extend(["bullet", "bullet"])

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["project_0:highlights"],
            instruction="rewrite highlights with STAR, four rows is wrong",
        )

    final_rows = result.improved_data["personalProjects"][0]["description"]
    assert len(final_rows) == 12
    assert final_rows[10] == _STAR_HIGHLIGHT_1[:-1]
    assert final_rows[11] == _STAR_HIGHLIGHT_2[:-1]
    assert any(
        w.startswith("REGION_APPEND_DROPPED") for w in result.warnings
    ), result.warnings


async def test_run_fine_tune_reformats_nested_head_details_as_ordered_list() -> None:
    # The reported request: only 项目亮点 checked, instruction "render the
    # content under 重大生产环境问题解决 and 性能调优 as an ordered list". The
    # model keeps every row byte-for-byte and flips plain detail rows to
    # bullet; the finalizer/overlay used to freeze styles, so nothing changed.
    source = _nested_heads_project_source()
    resume = {"processed_data": source, "original_markdown": ""}
    candidate = copy.deepcopy(source)
    styles = candidate["personalProjects"][0]["descriptionStyles"]
    for index in (8, 9, 11, 12):
        styles[index] = "bullet"

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["project_0:highlights"],
            instruction=(
                '请把子项"重大生产环境问题解决"和"性能调优"下面的内容，'
                "用有序列表重新格式化一遍"
            ),
        )

    entry = result.improved_data["personalProjects"][0]
    # Styles flipped only on the four region detail rows. The read-time heal
    # chain then unifies list-point endings: every bullet row (the pre-existing
    # index 5 plus the four flipped rows) loses its trailing sentence period;
    # plain prose rows keep theirs.
    expected_rows = list(source["personalProjects"][0]["description"])
    for index in (5, 8, 9, 11, 12):
        assert expected_rows[index].endswith("。")
        expected_rows[index] = expected_rows[index][:-1]
    assert entry["description"] == expected_rows
    assert entry["descriptionStyles"] == [
        "label",
        "plain",
        "label",
        "plain",
        "label",
        "bullet",
        "label",
        "label",
        "bullet",
        "bullet",
        "label",
        "bullet",
        "bullet",
    ]
    assert not [w for w in result.warnings if w.startswith("REGION_APPEND_DROPPED")]


# --- run_fine_tune end to end (LLM mocked) ---------------------------------


async def test_run_fine_tune_restores_metric_grounded_only_in_original_text() -> (
    None
):
    resume = {
        "processed_data": _source(),
        "original_markdown": (
            "# Jane Doe\nBackend engineer leading 800 engineers across teams.\n"
            "- Mentored 3 junior developers\n"
        ),
    }
    candidate = copy.deepcopy(_source())
    candidate["summary"] = "Backend engineer leading 800 engineers across teams."

    captured: dict[str, str] = {}

    async def fake_complete_json(**kwargs: Any) -> dict[str, Any]:
        captured["prompt"] = kwargs["prompt"]
        return copy.deepcopy(candidate)

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(side_effect=fake_complete_json),
    ):
        result = await run_fine_tune(
            resume=resume, kind="all", targets=[], instruction="emphasize impact"
        )

    # Hygiene strips the trailing period: summary lines render as list points.
    assert result.improved_data["summary"] == (
        "Backend engineer leading 800 engineers across teams"
    )
    # personalInfo is always restored by the finalizer.
    assert result.improved_data["personalInfo"]["name"] == "Jane Doe"
    assert "ORIGINAL UPLOAD TEXT:" in captured["prompt"]
    assert "emphasize impact" in captured["prompt"]
    # The grounded summary rewrite must not produce a grounding warning.
    assert not [w for w in result.warnings if "summary" in w]
    assert result.diff_summary is not None


async def test_run_fine_tune_without_structured_data_raises() -> None:
    with pytest.raises(ValueError, match="structured data"):
        await run_fine_tune(
            resume={"processed_data": None},
            kind="all",
            targets=[],
            instruction="",
        )


async def test_run_fine_tune_honours_format_only_date_rewrite() -> None:
    # Instruction: render education dates as yyyy.MM. The model complies while
    # keeping the exact same date points; the finalizer used to force the
    # Chinese-formatted source value back ("改不了").
    source = _education_source()
    source["education"][0]["years"] = "2016 年 06 月 - 2020 年 09 月"
    resume = {"processed_data": source, "original_markdown": ""}
    candidate = copy.deepcopy(source)
    candidate["education"][0]["years"] = "2016.06 - 2020.09"

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["education"],
            instruction="受教育的时间改成 yyyy.MM - yyyy.MM 格式",
        )

    assert result.improved_data["education"][0]["years"] == "2016.06 - 2020.09"


async def test_run_fine_tune_reverts_factual_date_change_even_if_formatted() -> None:
    source = _education_source()
    source["education"][0]["years"] = "2016 年 06 月 - 2020 年 09 月"
    resume = {"processed_data": source, "original_markdown": ""}
    candidate = copy.deepcopy(source)
    # Dotted presentation, but the dates themselves moved.
    candidate["education"][0]["years"] = "2017.09 - 2021.06"

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["education"],
            instruction="统一日期格式",
        )

    # The factual change is reverted; the restored value comes from the
    # canonicalized source copy, so it renders in canonical date presentation.
    assert result.improved_data["education"][0]["years"] == "2016.06~2020.09"


# --- Misplacement hints, relocation prompt and pipeline behavior ----------


def _education_source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Li Si"},
        "summary": "",
        "workExperience": [
            {
                "id": 1,
                "title": "Intern",
                "company": "Acme",
                "years": "2020",
                "description": ["维护内部系统"],
                "descriptionStyles": ["bullet"],
            },
            {
                "id": 2,
                "title": "QA",
                "company": "Beta",
                "years": "2021",
                "description": ["持有 PMP 证书的轮岗"],
                "descriptionStyles": ["bullet"],
            },
        ],
        "education": [
            {
                "id": 3,
                "institution": "TJU",
                "degree": "BSc",
                "years": "2017 - 2021",
                "description": (
                    "专业：计算机科学与技术\n"
                    "奖项：国家励志奖学金、校二等奖\n"
                    "证书：PMP项目管理证书"
                ),
            }
        ],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


def test_misplacement_hints_only_for_module_scope_without_additional() -> None:
    source = _education_source()

    hint = fine_tune._misplacement_hints(source, "modules", ["education"])
    assert len(hint) == 1
    assert hint[0] == "SCOPE_RELOCATION_HINT: awards,certifications"

    assert fine_tune._misplacement_hints(source, "all", []) == []
    assert (
        fine_tune._misplacement_hints(
            source, "modules", ["education", "additional"]
        )
        == []
    )
    clean = copy.deepcopy(source)
    clean["education"][0]["description"] = "专业：计算机科学与技术"
    assert fine_tune._misplacement_hints(clean, "modules", ["education"]) == []


def test_misplacement_hints_respect_checked_item_tokens() -> None:
    source = _education_source()

    # Only work_0 is in scope; its description is clean, so no hint even
    # though work_1 mentions a certificate.
    assert fine_tune._misplacement_hints(source, "modules", ["work_0"]) == []

    hint = fine_tune._misplacement_hints(source, "modules", ["work_1"])
    assert hint == ["SCOPE_RELOCATION_HINT: certifications"]


async def test_prompt_carries_relocation_rule_per_scope_and_rank_rule() -> None:
    resume = {"processed_data": _source(), "original_markdown": ""}
    captured: dict[str, str] = {}

    async def fake_complete_json(**kwargs: Any) -> dict[str, Any]:
        captured["prompt"] = kwargs["prompt"]
        return copy.deepcopy(_source())

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(side_effect=fake_complete_json),
    ):
        await run_fine_tune(resume=resume, kind="all", targets=[], instruction="")
        assert "MOVE it into the matching additional array" in captured["prompt"]
        assert "一等奖 stays 一等奖" in captured["prompt"]

        await run_fine_tune(
            resume=resume, kind="modules", targets=["education"], instruction=""
        )
        assert "do not move content between sections" in captured["prompt"].lower()


async def test_all_scope_relocates_trapped_awards_via_structured_evidence() -> None:
    resume = {"processed_data": _education_source(), "original_markdown": ""}
    candidate = copy.deepcopy(_education_source())
    candidate["education"][0]["description"] = "专业：计算机科学与技术"
    candidate["additional"]["awards"] = ["国家励志奖学金", "校二等奖"]
    candidate["additional"]["certificationsTraining"] = ["PMP项目管理证书"]

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume, kind="all", targets=[], instruction=""
        )

    awards = result.improved_data["additional"]["awards"]
    certs = result.improved_data["additional"]["certificationsTraining"]
    assert "国家励志奖学金" in awards and "校二等奖" in awards
    assert "PMP项目管理证书" in certs
    education_text = result.improved_data["education"][0]["description"]
    assert "奖项" not in education_text and "证书" not in education_text
    assert not [w for w in result.warnings if w.startswith("SCOPE_RELOCATION_HINT")]


async def test_module_scope_gets_deterministic_relocation_from_normalized_source() -> None:
    # The canonical source now runs through normalize_resume_data: trapped
    # education labels are relocated BEFORE the LLM, so module scope (which
    # freezes additional) still starts from the healed shape and emits no
    # relocation hint for label-shaped misfiles.
    resume = {"processed_data": _education_source(), "original_markdown": ""}
    # Adversarial model echoes the old trapped shape it was not given.
    candidate = copy.deepcopy(_education_source())

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["education"],
            instruction="",
        )

    awards = result.improved_data["additional"]["awards"]
    assert "国家励志奖学金" in awards and "校二等奖" in awards
    assert "PMP项目管理证书" in result.improved_data["additional"][
        "certificationsTraining"
    ]
    assert "奖项" not in result.improved_data["education"][0]["description"]
    assert "校三等奖" not in result.improved_data["education"][0]["description"]
    assert not [
        w for w in result.warnings if w.startswith("SCOPE_RELOCATION_HINT")
    ]


async def test_pipeline_reverts_chinese_rank_swap_in_work_bullet() -> None:
    # Rank mutation guard for an unlabeled work bullet (rules cannot relocate
    # it, so the finalizer is still the line of defense).
    source = _source()
    source["workExperience"][0]["description"] = ["获校二等奖学金一次"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    resume = {"processed_data": source, "original_markdown": ""}
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["获校三等奖学金一次"]

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume, kind="all", targets=[], instruction=""
        )

    descriptions = result.improved_data["workExperience"][0]["description"]
    assert "获校二等奖学金一次" in descriptions
    assert not any("三等奖学金" in row for row in descriptions)


# --- Canonical source normalization (parser rules heal before fine-tune) --


def _misfiled_work_source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Zhang San"},
        "summary": "",
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": "Acme",
                "years": "2020 - 2024",
                "description": ["负责支付系统开发", "奖项：国家奖学金"],
                "descriptionStyles": ["bullet", "bullet"],
            }
        ],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


def test_canonical_source_normalizes_without_mutating_input() -> None:
    raw = _misfiled_work_source()
    snapshot = copy.deepcopy(raw)

    canonical = fine_tune._canonical_source({"processed_data": raw})

    assert raw == snapshot
    assert canonical["additional"]["awards"] == ["国家奖学金"]
    assert canonical["workExperience"][0]["description"] == ["负责支付系统开发"]
    assert canonical["workExperience"][0]["descriptionStyles"] == ["bullet"]

    with pytest.raises(ValueError, match="structured data"):
        fine_tune._canonical_source({"processed_data": None})


async def test_module_scope_deterministically_relocates_work_misfile() -> None:
    raw = _misfiled_work_source()
    resume = {"processed_data": raw, "original_markdown": ""}
    # The model receives the healed canonical source and echoes it, as a real
    # model working from healed JSON would.
    candidate = fine_tune._canonical_source({"processed_data": raw})

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(candidate)),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["work_0"],
            instruction="",
        )

    assert result.improved_data["additional"]["awards"] == ["国家奖学金"]
    assert result.improved_data["workExperience"][0]["description"] == [
        "负责支付系统开发"
    ]
    assert not [
        w for w in result.warnings if w.startswith("SCOPE_RELOCATION_HINT")
    ]


async def test_module_scope_still_warns_for_unlabeled_prose() -> None:
    # work_1 in this fixture is "持有 PMP 证书的轮岗": no label, so rules leave
    # it alone and the long-tail hint must still reach the user.
    resume = {"processed_data": _education_source(), "original_markdown": ""}
    candidate = copy.deepcopy(_education_source())

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=candidate),
    ):
        result = await run_fine_tune(
            resume=resume,
            kind="modules",
            targets=["work_1"],
            instruction="",
        )

    assert result.warnings == ["SCOPE_RELOCATION_HINT: certifications"]


async def test_all_scope_healed_source_and_model_output_do_not_duplicate_items() -> None:
    raw = _misfiled_work_source()
    resume = {"processed_data": raw, "original_markdown": ""}
    healed = fine_tune._canonical_source({"processed_data": raw})

    with patch(
        "app.services.fine_tune.complete_json",
        new=AsyncMock(return_value=copy.deepcopy(healed)),
    ):
        result = await run_fine_tune(
            resume=resume, kind="all", targets=[], instruction=""
        )

    assert result.improved_data["additional"]["awards"] == ["国家奖学金"]
    assert result.improved_data["workExperience"][0]["description"] == [
        "负责支付系统开发"
    ]


# --- Per-custom-section tokens (custom_<key>) ------------------------------


def _custom_source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Wang Wu"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {
            "self_evaluation": {"sectionType": "text", "text": "踏实肯干"},
            "publications": {
                "sectionType": "itemList",
                "items": [
                    {
                        "id": 1,
                        "title": "某核心期刊论文",
                        "years": "2019",
                        "description": ["提出一种新架构"],
                        "descriptionStyles": ["bullet"],
                    }
                ],
            },
            # Builder-created keys are themselves custom_N, so the scope token
            # carries a double prefix: custom_custom_1.
            "custom_1": {"sectionType": "stringList", "strings": ["阅读", "跑步"]},
        },
        "sectionMeta": [
            {
                "id": "self_evaluation",
                "key": "self_evaluation",
                "displayName": "自我评价",
                "sectionType": "text",
                "isDefault": False,
                "isVisible": True,
                "order": 0,
            },
            {
                "id": "publications",
                "key": "publications",
                "displayName": "Publications",
                "sectionType": "itemList",
                "isDefault": False,
                "isVisible": True,
                "order": 1,
            },
            {
                "id": "custom_1",
                "key": "custom_1",
                "displayName": "兴趣爱好",
                "sectionType": "stringList",
                "isDefault": False,
                "isVisible": True,
                "order": 2,
            },
        ],
    }


def test_scope_accepts_custom_section_tokens() -> None:
    scope = FineTuneScope(
        kind="modules",
        targets=[
            "custom_self_evaluation",
            "custom_publications",
            "custom_custom_1",
            "custom_兴趣爱好",
            "custom_self_evaluation",
        ],
    )
    assert scope.targets == [
        "custom_self_evaluation",
        "custom_publications",
        "custom_custom_1",
        "custom_兴趣爱好",
    ]


@pytest.mark.parametrize(
    "token", ["custom_", "custom", "custom_foo bar", "customSections_x"]
)
def test_scope_rejects_malformed_custom_tokens(token: str) -> None:
    with pytest.raises(ValidationError):
        FineTuneScope(kind="modules", targets=[token])


def test_custom_token_overlay_replaces_only_targeted_key() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)
    candidate["customSections"]["publications"]["items"][0]["title"] = "Changed Paper"
    candidate["customSections"]["self_evaluation"]["text"] = "Changed self eval"
    candidate["customSections"]["custom_1"]["strings"] = ["游泳"]

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["custom_publications"]
    )

    assert ignored == []
    assert (
        result["customSections"]["publications"]
        == candidate["customSections"]["publications"]
    )
    assert (
        result["customSections"]["self_evaluation"]
        == source["customSections"]["self_evaluation"]
    )
    assert result["customSections"]["custom_1"] == source["customSections"]["custom_1"]


def test_builder_style_double_prefix_token_resolves() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)
    candidate["customSections"]["custom_1"]["strings"] = ["游泳"]
    candidate["customSections"]["self_evaluation"]["text"] = "Changed"

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["custom_custom_1"]
    )

    assert ignored == []
    assert result["customSections"]["custom_1"]["strings"] == ["游泳"]
    assert (
        result["customSections"]["self_evaluation"]
        == source["customSections"]["self_evaluation"]
    )


def test_custom_token_ignored_when_key_missing_in_source() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["custom_ghost"]
    )

    assert ignored == ["custom_ghost"]
    assert result["customSections"] == source["customSections"]


def test_custom_token_ignored_when_missing_in_candidate() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)
    del candidate["customSections"]["publications"]

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["custom_publications"]
    )

    assert ignored == ["custom_publications"]
    assert (
        result["customSections"]["publications"]
        == source["customSections"]["publications"]
    )


def test_whole_custom_sections_supersedes_per_key_tokens() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)
    candidate["customSections"]["self_evaluation"]["text"] = "Changed"
    candidate["customSections"]["publications"]["items"][0]["title"] = "Changed"
    candidate["customSections"]["volunteer_work"] = {
        "sectionType": "text",
        "text": "Volunteer",
    }

    result, ignored, _ = restrict_to_scope(
        source,
        candidate,
        "modules",
        ["customSections", "custom_self_evaluation"],
    )

    assert ignored == []
    assert result["customSections"] == _canonical(candidate)["customSections"]


def test_custom_overlay_does_not_merge_candidate_only_new_key() -> None:
    source = _canonical(_custom_source())
    candidate = copy.deepcopy(source)
    candidate["customSections"]["publications"]["items"][0]["title"] = "Changed"
    candidate["customSections"]["volunteer_work"] = {
        "sectionType": "text",
        "text": "Volunteer",
    }

    result, ignored, _ = restrict_to_scope(
        source, candidate, "modules", ["custom_publications"]
    )

    assert ignored == []
    assert "volunteer_work" not in result["customSections"]
    assert (
        result["customSections"]["publications"]
        == candidate["customSections"]["publications"]
    )


def test_build_scope_description_resolves_custom_display_names() -> None:
    source = _canonical(_custom_source())

    description = build_scope_description(
        source,
        "modules",
        ["custom_self_evaluation", "custom_publications", "custom_ghost"],
    )

    assert "customSections[self_evaluation] (自我评价): only this custom section" in description
    assert "customSections[publications] (Publications): only this custom section" in description
    assert "customSections[ghost]: only this custom section" in description
