"""Label-region span extraction for fine-tune sub-module scoping.

The fixture matrix here is mirrored by the frontend parity test
(apps/frontend/tests/description-regions.test.ts).
"""

from app.services.description_regions import (
    REGION_ACHIEVEMENTS,
    REGION_BACKGROUND,
    REGION_DUTIES,
    REGION_HIGHLIGHTS,
    REGION_TECH_STACK,
    entry_label_regions,
    merged_entry_regions,
)

# A "超鹿运动"-shaped project: four canonical label regions.
PROJECT_DESCRIPTION = [
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
    "核心接口响应耗时降低40%。",
]
PROJECT_STYLES = [
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
]


def _regions(description: list[str], styles: list[str], kind: str):
    return entry_label_regions(description, styles, kind=kind)  # type: ignore[arg-type]


def test_project_regions_cover_rows_between_labels_excluding_label_row() -> None:
    regions = _regions(PROJECT_DESCRIPTION, PROJECT_STYLES, "project")

    assert [(r.region_id, r.label_index) for r in regions] == [
        (REGION_TECH_STACK, 0),
        (REGION_BACKGROUND, 4),
        (REGION_DUTIES, 6),
        (REGION_HIGHLIGHTS, 9),
    ]
    by_id = {r.region_id: r for r in regions}
    assert by_id[REGION_TECH_STACK].content_indices == (1, 2, 3)
    assert by_id[REGION_TECH_STACK].label_text == "技术栈："
    assert by_id[REGION_BACKGROUND].content_indices == (5,)
    assert by_id[REGION_DUTIES].content_indices == (7, 8)
    assert by_id[REGION_HIGHLIGHTS].content_indices == (10, 11)


def test_preamble_rows_before_first_label_belong_to_no_region() -> None:
    description = ["项目一句话简介。", *PROJECT_DESCRIPTION]
    styles = ["plain", *PROJECT_STYLES]

    regions = _regions(description, styles, "project")
    by_id = {r.region_id: r for r in regions}

    assert 0 not in by_id[REGION_TECH_STACK].content_indices
    assert by_id[REGION_TECH_STACK].content_indices == (2, 3, 4)
    assert by_id[REGION_HIGHLIGHTS].content_indices == (11, 12)


def test_project_alias_labels_canonicalize_to_region_ids() -> None:
    description = [
        "技术选型：",
        "Java",
        "项目成果：",
        "核心接口耗时降低40%。",
    ]
    styles = ["label", "plain", "label", "bullet"]

    by_id = {r.region_id: r for r in _regions(description, styles, "project")}

    assert set(by_id) == {REGION_TECH_STACK, REGION_HIGHLIGHTS}
    assert by_id[REGION_TECH_STACK].content_indices == (1,)
    assert by_id[REGION_HIGHLIGHTS].content_indices == (3,)
    # The stored label is never renamed by region extraction.
    assert by_id[REGION_TECH_STACK].label_text == "技术选型："


def test_combined_duty_result_label_opens_a_duties_region() -> None:
    # "项目职责与成果：" is a compound duty + result heading; its bullet rows
    # must be selectable as the duties sub-module in fine-tune.
    description = [
        "项目背景：",
        "面向应急管理部的大数据应用平台。",
        "技术栈：",
        "Spring Boot, Kafka, Redis",
        "项目职责与成果：",
        "负责智搜核心模块的设计与落地，QPS 提升 10 倍以上。",
        "基于 PaddleNLP 完成查询词实体抽取与语义匹配。",
    ]
    styles = ["label", "plain", "label", "plain", "label", "bullet", "bullet"]

    by_id = {r.region_id: r for r in _regions(description, styles, "project")}

    assert set(by_id) == {REGION_BACKGROUND, REGION_TECH_STACK, REGION_DUTIES}
    assert by_id[REGION_DUTIES].content_indices == (5, 6)
    assert by_id[REGION_DUTIES].label_text == "项目职责与成果："
    # The tech-stack region must be closed by the compound heading.
    assert by_id[REGION_TECH_STACK].content_indices == (3,)


def test_combined_duty_result_label_variants_all_map_to_duties() -> None:
    for label in (
        "项目职责和成果：",
        "项目职责及成果：",
        "工作职责与成果：",
        "职责与成果：",
    ):
        by_id = {
            r.region_id: r
            for r in _regions([label, "负责后端开发。"], ["label", "bullet"], "project")
        }
        assert set(by_id) == {REGION_DUTIES}, label
        assert by_id[REGION_DUTIES].content_indices == (1,), label

    # Work entries recognize the same family verbatim (never renamed).
    by_id = {
        r.region_id: r
        for r in _regions(
            ["工作职责与成果：", "负责核心系统。"], ["label", "bullet"], "work"
        )
    }
    assert set(by_id) == {REGION_DUTIES}
    assert by_id[REGION_DUTIES].label_text == "工作职责与成果："


def test_unknown_standalone_heading_closes_the_current_region() -> None:
    description = [
        "项目职责：",
        "负责后端开发。",
        "解决方案：",
        "采用补偿事务保证一致性。",
        "项目亮点：",
        "接口耗时降低40%。",
    ]
    styles = ["label", "bullet", "label", "bullet", "label", "bullet"]

    by_id = {r.region_id: r for r in _regions(description, styles, "project")}

    assert by_id[REGION_DUTIES].content_indices == (1,)
    assert by_id[REGION_HIGHLIGHTS].content_indices == (5,)
    # Rows 3 (under 解决方案） are selectable in no region.
    assert 3 not in by_id[REGION_DUTIES].content_indices


def test_nested_bold_head_inside_bullet_region_stays_in_region() -> None:
    # Unknown bold colon headings inside duties/highlights render as nested
    # numbered point heads, so they (and their detail rows) stay in-region.
    description = [
        "项目亮点：",
        "重大生产问题解决：",
        "通过补偿机制恢复数据。",
        "性能优化：",
        "核心接口耗时降低40%。",
    ]
    styles = ["label", "label", "plain", "label", "plain"]

    by_id = {r.region_id: r for r in _regions(description, styles, "project")}
    assert by_id[REGION_HIGHLIGHTS].content_indices == (1, 2, 3, 4)


def test_descriptive_only_label_names_act_as_separators_without_region() -> None:
    description = [
        "项目职责：",
        "负责后端开发。",
        "项目描述：",
        "一套数字化平台。",
        "项目亮点：",
        "耗时降低40%。",
    ]
    styles = ["label", "bullet", "label", "plain", "label", "bullet"]

    regions = _regions(description, styles, "project")

    assert [r.region_id for r in regions] == [REGION_DUTIES, REGION_HIGHLIGHTS]
    by_id = {r.region_id: r for r in regions}
    assert by_id[REGION_DUTIES].content_indices == (1,)
    assert by_id[REGION_HIGHLIGHTS].content_indices == (5,)


def test_bullet_styled_label_shaped_row_is_not_a_heading() -> None:
    description = ["项目职责：", "项目亮点：客户端零故障。"]
    styles = ["label", "bullet"]

    by_id = {r.region_id: r for r in _regions(description, styles, "project")}

    assert REGION_HIGHLIGHTS not in by_id
    assert by_id[REGION_DUTIES].content_indices == (1,)


def test_work_regions_recognize_curated_labels_without_renaming() -> None:
    description = [
        "工作职责：",
        "完成日常开发。",
        "工作业绩：",
        "年度优秀员工。",
    ]
    styles = ["label", "bullet", "label", "bullet"]

    regions = _regions(description, styles, "work")
    by_id = {r.region_id: r for r in regions}

    assert by_id[REGION_DUTIES].content_indices == (1,)
    assert by_id[REGION_DUTIES].label_text == "工作职责："
    assert by_id[REGION_ACHIEVEMENTS].content_indices == (3,)
    assert by_id[REGION_ACHIEVEMENTS].label_text == "工作业绩："


def test_work_unknown_heading_closes_region_and_tech_aliases_map() -> None:
    description = [
        "技术栈：",
        "Java",
        "带团队：",
        "管理5人小组。",
        "主要职责：",
        "负责架构设计。",
    ]
    styles = ["label", "plain", "label", "bullet", "label", "bullet"]

    by_id = {r.region_id: r for r in _regions(description, styles, "work")}

    assert by_id[REGION_TECH_STACK].content_indices == (1,)
    assert by_id[REGION_DUTIES].content_indices == (5,)
    # Rows under the unknown heading 带团队 belong to no selectable region.
    assert all(3 not in region.content_indices for region in by_id.values())


def test_merged_regions_union_same_id_blocks() -> None:
    description = [
        "项目职责：",
        "负责A模块。",
        "项目职责：",
        "负责B模块。",
        "项目亮点：",
        "零故障。",
    ]
    styles = ["label", "bullet", "label", "bullet", "label", "bullet"]

    merged = merged_entry_regions(description, styles, kind="project")

    assert set(merged) == {REGION_DUTIES, REGION_HIGHLIGHTS}
    assert merged[REGION_DUTIES].content_indices == (1, 3)
    assert merged[REGION_DUTIES].label_index == 0
    assert merged[REGION_DUTIES].label_text == "项目职责："


def test_missing_or_empty_description_yields_no_regions() -> None:
    assert entry_label_regions(None, None, kind="project") == []
    assert entry_label_regions([], [], kind="work") == []
    assert entry_label_regions(["普通条目，没有标签。"], ["bullet"], kind="project") == []
