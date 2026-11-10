"""Unit tests for the canonical Word (.docx) resume renderer.

The DOCX output is the display-side Python mirror of the on-screen
swiss-single template, so the tests pin the same content contract:
canonical section order, four-column entry headers, description-block
semantics with per-label numbering restarts, independent 培训与证书 /
荣誉奖项 modules, and Markdown-modifier stripping.
"""

import copy
import io
from typing import Any

import pytest
from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.table import Table

from app.schemas.models import DEFAULT_SECTION_META
from app.services.resume_docx import (
    DOCX_MEDIA_TYPE,
    _META_COLOR,
    build_resume_docx,
    resume_docx_headers,
)


def _custom_meta(key: str, name: str, section_type: str, order: int) -> dict[str, Any]:
    return {
        "id": key,
        "key": key,
        "displayName": name,
        "sectionType": section_type,
        "isDefault": False,
        "isVisible": True,
        "order": order,
    }


def _full_resume_data() -> dict[str, Any]:
    """Synthetic ResumeData exercising every renderer branch.

    Includes leaked ``**`` markers (one pair split across fields), source
    numbering, a glued legacy project label, empty department, independent
    cert/award lists, and all three custom-section shapes.
    """
    return {
        "personalInfo": {
            "name": "李勇",
            "gender": "男",
            "age": "38",
            "educationLevel": "统招本科（**985&211)**",
            "workYears": "15年+ **5年大型医院项目，3年电商）**",
            "title": "CTO",
            "location": "上海",
            "phone": "17888001016",
            "email": "a@qq.com",
            "website": "https://liyong.example.com/",
            "linkedin": "",
            "github": "",
        },
        "education": [
            {
                "years": "2006 - 2010",
                "institution": "某大学",
                "description": "计算机科学",
                "degree": "统招本科",
            }
        ],
        "summary": "**10年研发管理经验**\n主导过多个大型平台\n带过200人技术团队",
        "additional": {
            "technicalSkills": ["1、Java / Spring 生态", "**Python**", "团队管理"],
            "certificationsTraining": ["信息系统项目管理师（高项）证书"],
            "awards": ["上海市优秀工程师（2022）"],
            # Duplicate fact carried with different Markdown formatting; the
            # two collapse after stripping and must render only once.
            "languages": ["英语四级**", "英语四级", "日语N2"],
        },
        "workExperience": [
            {
                "years": "2020 - 至今",
                "company": "某科技公司",
                "department": "研发部",
                "location": "上海",
                "title": "架构师",
                "description": ["总体负责平台演进", "项目职责：", "负责核心架构", "推进微服务化"],
                "descriptionStyles": ["bullet", "label", "bullet", "bullet"],
            }
        ],
        "personalProjects": [
            {
                "name": "医院信息平台",
                "years": "2018 - 2020",
                "scale": "20人",
                "role": "核心开发",
                "github": "",
                "website": "",
                "description": [
                    "技术栈：",
                    "Spring Boot、MySQL",
                    "技术难点及亮点：实时时延<50ms",
                    "项目职责：",
                    "负责核心模块",
                    "解决性能瓶颈",
                ],
                "descriptionStyles": ["label", "plain", "plain", "label", "bullet", "bullet"],
            }
        ],
        "customSections": {
            "self_evaluation": {
                "sectionType": "text",
                "text": "踏实肯干\n持续学习",
            },
            "hobbies": {
                "sectionType": "stringList",
                "strings": ["阅读", "跑步"],
            },
            "papers": {
                "sectionType": "itemList",
                "items": [
                    {
                        "title": "某核心期刊论文",
                        "subtitle": "第一作者",
                        "years": "2019",
                        "location": "某期刊",
                        "description": ["提出一种新架构"],
                        "descriptionStyles": ["bullet"],
                    }
                ],
            },
        },
        "sectionMeta": [
            _custom_meta("self_evaluation", "个人总结", "text", 90),
            _custom_meta("hobbies", "兴趣爱好", "stringList", 91),
            _custom_meta("papers", "论文", "itemList", 92),
        ],
    }


def _build_doc(data: dict[str, Any], language: str | None = "zh") -> DocumentObject:
    raw = build_resume_docx(data, language=language)
    assert raw[:4] == b"PK\x03\x04"  # ZIP local file header = valid .docx
    return Document(io.BytesIO(raw))


def _paragraph_texts(document: DocumentObject) -> list[str]:
    return [paragraph.text for paragraph in document.paragraphs]


def _header_grid_texts(document: DocumentObject) -> list[str]:
    """Flattened cell texts of the borderless header fact/link grid (table 0)."""
    assert document.tables, "document has no tables"
    header_table = document.tables[0]
    return [cell.text for row in header_table.rows for cell in row.cells]


def _heading_index(texts: list[str], heading: str) -> int:
    return texts.index(heading)


def _table_with_cell(document: DocumentObject, cell_text: str) -> Table:
    matches = [
        table
        for table in document.tables
        if any(cell_text in cell.text for row in table.rows for cell in row.cells)
    ]
    assert len(matches) == 1, f"expected exactly one table containing {cell_text!r}"
    return matches[0]


def _run_is_bold(table: Table, cell_index: int) -> bool:
    runs = table.rows[0].cells[cell_index].paragraphs[0].runs
    assert runs, "cell has no runs"
    return any(bool(run.bold) for run in runs)


def test_build_returns_valid_docx_with_header_facts() -> None:
    document = _build_doc(_full_resume_data())
    texts = _paragraph_texts(document)

    assert texts[0] == "李勇"
    # Facts live in the borderless three-column header grid, one labeled pair
    # per cell, so labels never split from their values across wrapped lines.
    header_cells = _header_grid_texts(document)
    fact_blob = "\n".join(header_cells)
    assert "性别：男" in header_cells
    assert "学历：统招本科（985&211)" in fact_blob
    assert "工作年限：15年+ 5年大型医院项目，3年电商）" in fact_blob
    assert "外语水平：英语四级、日语N2" in fact_blob
    assert "英语四级、英语四级" not in fact_blob
    assert fact_blob.count("英语四级") == 1
    # Nine facts fill three 3-cell rows; the link sits on its own fourth row.
    header_table = document.tables[0]
    assert (len(header_table.rows), len(header_table.columns)) == (4, 3)
    # The link is labeled and strips protocol / www / trailing slash.
    assert "个人网站：liyong.example.com" in header_cells
    assert "https://" not in "\n".join(header_cells)
    assert "https://" not in "\n".join(texts)


def test_header_grid_labels_every_personal_link() -> None:
    data = _full_resume_data()
    data["personalInfo"].update(
        {
            "website": "https://fengba.blog.csdn.net/",
            "linkedin": "linkedin.com/in/wanghao",
            "github": "github.com/wanghao",
        }
    )

    document = _build_doc(data)
    header_table = document.tables[0]
    link_row = [cell.text for cell in header_table.rows[-1].cells]

    # The three links share one labeled grid row, protocols stripped.
    assert link_row == [
        "个人网站：fengba.blog.csdn.net",
        "领英：linkedin.com/in/wanghao",
        "GitHub：github.com/wanghao",
    ]
    # Link cells render in the muted meta style (gray); fact runs carry no
    # explicit color and inherit the default ink-black body style.
    link_runs = [
        run
        for cell in header_table.rows[-1].cells
        for paragraph in cell.paragraphs
        for run in paragraph.runs
    ]
    assert all(run.font.color.rgb == _META_COLOR for run in link_runs if run.text)


def test_markdown_emphasis_is_stripped_everywhere() -> None:
    document = _build_doc(_full_resume_data())
    blob = "\n".join(
        _paragraph_texts(document)
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    assert "**" not in blob
    assert "__" not in blob
    assert "10年研发管理经验" in blob
    assert "Python" in blob


def test_certifications_and_awards_are_independent_modules() -> None:
    document = _build_doc(_full_resume_data())
    texts = _paragraph_texts(document)

    i_skills = _heading_index(texts, "专业技能")
    i_work = _heading_index(texts, "工作经历")
    i_papers = _heading_index(texts, "论文")
    i_certs = _heading_index(texts, "培训与证书")
    i_awards = _heading_index(texts, "荣誉奖项")
    i_selfeval = _heading_index(texts, "个人总结")
    assert i_skills < i_certs < i_awards

    # The two modules are projected to the BACK: after the custom-section
    # cluster (论文), directly before the self-evaluation row.
    assert i_papers < i_certs < i_awards < i_selfeval

    # Cert/award entries live under their own headings, never in the skills
    # numbered list (which sits at the early additional slot).
    skills_block = texts[i_skills + 1 : i_work]
    assert not any("信息系统项目管理师" in line for line in skills_block)
    assert not any("优秀工程师" in line for line in skills_block)
    cert_block = texts[i_certs + 1 : i_awards]
    assert any("信息系统项目管理师" in line for line in cert_block)
    # A lone entry renders as a plain paragraph (numbering needs 2+ points).
    assert texts[i_awards + 1] == "上海市优秀工程师（2022）"
    assert not texts[i_awards + 1].startswith("1.")


def test_formal_section_order() -> None:
    document = _build_doc(_full_resume_data())
    texts = _paragraph_texts(document)
    indices = [
        _heading_index(texts, title)
        for title in (
            "教育背景",
            "个人优势",
            "专业技能",
            "工作经历",
            "项目经验",
            "兴趣爱好",
            "论文",
            "培训与证书",
            "荣誉奖项",
            "个人总结",
        )
    ]
    assert indices == sorted(indices)
    # The self-evaluation custom title stays verbatim (no 自我介绍 alias).
    assert "自我介绍" not in texts


def test_other_degree_branch_places_education_after_projects() -> None:
    data = _full_resume_data()
    data["personalInfo"]["educationLevel"] = "本科"
    data["education"][0]["degree"] = "本科"
    document = _build_doc(data)
    texts = _paragraph_texts(document)
    assert (
        _heading_index(texts, "个人优势")
        < _heading_index(texts, "工作经历")
        < _heading_index(texts, "项目经验")
        < _heading_index(texts, "培训与证书")
        < _heading_index(texts, "荣誉奖项")
        < _heading_index(texts, "教育背景")
        < _heading_index(texts, "个人总结")
    )


def test_work_header_is_four_columns_with_regular_weight() -> None:
    document = _build_doc(_full_resume_data())
    table = _table_with_cell(document, "某科技公司")
    cells = [cell.text for cell in table.rows[0].cells]
    assert cells[0].startswith("2020")
    assert cells[1] == "某科技公司 · 上海"
    assert cells[2] == "研发部"
    assert cells[3] == "架构师"
    # Date is metadata; company, department and role are all regular weight.
    assert not any(_run_is_bold(table, index) for index in range(4))
    # The date track (3.3cm) starts the company a little right of the date
    # glyphs; tracks stay 17cm total (widths round-trip through twips).
    assert [cell.width.cm for cell in table.rows[0].cells] == pytest.approx(
        [3.3, 4.5, 3.8, 5.4],
        abs=0.01,
    )


def test_work_header_without_department_is_three_columns() -> None:
    data = _full_resume_data()
    data["workExperience"][0]["department"] = ""

    document = _build_doc(data)
    table = _table_with_cell(document, "某科技公司")

    # A 1x3 grid (not the four-column row with an empty track).
    assert len(table.columns) == 3
    cells = [cell.text for cell in table.rows[0].cells]
    assert cells[0].startswith("2020")
    assert cells[1] == "某科技公司 · 上海"
    assert cells[2] == "架构师"
    assert not any(_run_is_bold(table, index) for index in range(3))
    # The company keeps its four-column track (3.3/4.5 start); the role fills
    # the freed department band plus the old role track (3.8 + 5.4 = 9.2cm)
    # and is flush right (两端对齐): date at the left edge, role at the right.
    # Widths round-trip through twips in the XML, so compare centimetres.
    assert [cell.width.cm for cell in table.rows[0].cells] == pytest.approx(
        [3.3, 4.5, 9.2],
        abs=0.01,
    )
    assert all(
        paragraph.alignment == WD_ALIGN_PARAGRAPH.RIGHT
        for paragraph in table.rows[0].cells[2].paragraphs
    )


def test_education_header_four_columns_institution_bold() -> None:
    document = _build_doc(_full_resume_data())
    table = _table_with_cell(document, "某大学")
    cells = [cell.text for cell in table.rows[0].cells]
    assert cells == ["2006~2010", "某大学", "计算机科学", "统招本科"]
    assert not _run_is_bold(table, 0)
    assert _run_is_bold(table, 1)
    assert not _run_is_bold(table, 3)


def test_project_header_four_columns() -> None:
    document = _build_doc(_full_resume_data())
    table = _table_with_cell(document, "医院信息平台")
    assert [cell.text for cell in table.rows[0].cells] == [
        "医院信息平台",
        "2018~2020",
        "20人",
        "核心开发",
    ]
    assert _run_is_bold(table, 0)
    assert _run_is_bold(table, 3)
    assert not _run_is_bold(table, 1)


def _paragraph_bold(document: DocumentObject, text: str) -> bool:
    for paragraph in document.paragraphs:
        if paragraph.text == text:
            return all(bool(run.bold) for run in paragraph.runs) and bool(paragraph.runs)
    raise AssertionError(f"paragraph {text!r} not found")


def _paragraph_left_indent_cm(document: DocumentObject, text: str) -> float | None:
    """Left indent in cm (None inherits the page edge; explicit Cm(0) is 0.0)."""
    for paragraph in document.paragraphs:
        if paragraph.text == text:
            indent = paragraph.paragraph_format.left_indent
            return None if indent is None else round(indent.cm, 3)
    raise AssertionError(f"paragraph {text!r} not found")


def test_label_is_bold_standalone_and_restarts_numbering() -> None:
    document = _build_doc(_full_resume_data())
    texts = _paragraph_texts(document)

    # Work: one bullet, then a label, then bullets restart at 1.
    assert "1. 总体负责平台演进" in texts
    i_work_label = texts.index("项目职责：")
    assert texts[i_work_label + 1] == "1. 负责核心架构"
    assert texts[i_work_label + 2] == "2. 推进微服务化"
    assert _paragraph_bold(document, "项目职责：")

    # Project: the descriptive label 技术栈 owns unnumbered body rows; the
    # glued legacy "技术难点及亮点：…" row is renamed to 项目亮点 and, being
    # inside that body block, stays unnumbered. The next label restarts the
    # bullet counter at 1.
    i_stack = texts.index("技术栈：")
    assert texts[i_stack + 1] == "Spring Boot、MySQL"
    assert texts[i_stack + 2] == "项目亮点：实时时延<50ms"
    assert not texts[i_stack + 2].startswith(("1.", "2."))
    i_project_label = texts.index("项目职责：", i_stack)
    assert texts[i_project_label + 1] == "1. 负责核心模块"
    assert texts[i_project_label + 2] == "2. 解决性能瓶颈"


def test_tech_stack_body_renders_as_one_inline_paragraph() -> None:
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "技术栈：",
        "Spring Boot",
        "Nacos",
        "Kafka",
        "项目职责：",
        "负责核心模块",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "plain",
        "plain",
        "plain",
        "label",
        "bullet",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    i_stack = texts.index("技术栈：")
    # All-ASCII stack joins with ", " in ONE paragraph, not one row per line.
    assert texts[i_stack + 1] == "Spring Boot, Nacos, Kafka"
    assert texts[i_stack + 2] == "项目职责："

    # CJK stack entries join with the enumeration comma 、.
    data["personalProjects"][0]["description"] = ["技术栈：", "Java", "Redis 缓存"]
    data["personalProjects"][0]["descriptionStyles"] = ["label", "plain", "plain"]
    texts = _paragraph_texts(_build_doc(data))
    i_stack = texts.index("技术栈：")
    assert texts[i_stack + 1] == "Java、Redis 缓存"


def test_tech_stack_category_rows_render_as_ordered_list() -> None:
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "技术栈：",
        "后端：Java 8、Spring Boot、Spring Cloud",
        "数据库：MySQL、Redis",
        "前端：Vue.js、Element UI",
        "运维/监控：Docker、Prometheus",
    ]
    data["personalProjects"][0]["descriptionStyles"] = ["label"] + ["plain"] * 4
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    i_stack = texts.index("技术栈：")
    # One number per category row; names inside a category stay inline with 、.
    assert texts[i_stack + 1 : i_stack + 5] == [
        "1. 后端：Java 8、Spring Boot、Spring Cloud",
        "2. 数据库：MySQL、Redis",
        "3. 前端：Vue.js、Element UI",
        "4. 运维/监控：Docker、Prometheus",
    ]
    # Category rows are regular weight (only sub-module heads are bold).
    assert not _paragraph_bold(document, "1. 后端：Java 8、Spring Boot、Spring Cloud")


def test_nested_highlight_heads_hierarchical_numbering_plain_vs_bullet() -> None:
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目亮点",
        "重大生产环境问题解决：",
        "成功解决明细下载系统卡死问题。",
        "明细下载过程中超时重试机制生效。",
        "性能调优：",
        "通过索引优化和SQL重构降低耗时。",
        "利用Redis做缓存缩短响应时间。",
        "cpu飙升问题：",
        "由于某个省数据量突然飙升。",
        "通过linux命令top、jstack找出慢逻辑。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "label",
        "plain",
        "plain",
        "label",
        "bullet",
        "bullet",
        "label",
        "plain",
        "plain",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    i = texts.index("项目亮点")
    # Every nested head is a bold level-1 point (1. 2. 3.); EVERY detail row
    # below a head renders as a level-2 sub-point (1.1/1.2, 2.1/2.2, 3.1/3.2),
    # regardless of the stored plain/bullet style — layered content under a
    # sub-module is always an ordered list. Hygiene strips trailing sentence
    # punctuation from bullet points only: plain rows (1.1/1.2, 3.1/3.2) keep
    # their periods, bullet rows (2.1/2.2) render without the final 。.
    assert texts[i + 1 : i + 10] == [
        "1. 重大生产环境问题解决：",
        "1.1 成功解决明细下载系统卡死问题。",
        "1.2 明细下载过程中超时重试机制生效。",
        "2. 性能调优：",
        "2.1 通过索引优化和SQL重构降低耗时",
        "2.2 利用Redis做缓存缩短响应时间",
        "3. cpu飙升问题：",
        "3.1 由于某个省数据量突然飙升。",
        "3.2 通过Linux命令top、jstack找出慢逻辑。",
    ]
    assert _paragraph_bold(document, "1. 重大生产环境问题解决：")
    assert _paragraph_bold(document, "2. 性能调优：")
    assert _paragraph_bold(document, "3. cpu飙升问题：")
    assert not _paragraph_bold(document, "2.1 通过索引优化和SQL重构降低耗时")


def test_nested_highlight_heads_with_all_bullet_details_use_composite_markers() -> None:
    # The user's "render as an ordered list" reformat: every detail row under
    # the nested heads is stored as "bullet". Heads stay level-1 points and
    # their bullets render as 1.1/1.2 then 2.1/2.2.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目亮点",
        "重大生产环境问题解决：",
        "成功解决明细下载系统卡死问题。",
        "明细下载过程中超时重试机制生效。",
        "性能调优：",
        "通过索引优化和SQL重构降低耗时。",
        "利用Redis做缓存缩短响应时间。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "label",
        "bullet",
        "bullet",
        "label",
        "bullet",
        "bullet",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    i = texts.index("项目亮点")
    # All details are stored "bullet", so hygiene strips their trailing
    # sentence punctuation before the numbered sub-points render.
    assert texts[i + 1 : i + 7] == [
        "1. 重大生产环境问题解决：",
        "1.1 成功解决明细下载系统卡死问题",
        "1.2 明细下载过程中超时重试机制生效",
        "2. 性能调优：",
        "2.1 通过索引优化和SQL重构降低耗时",
        "2.2 利用Redis做缓存缩短响应时间",
    ]
    assert _paragraph_bold(document, "1. 重大生产环境问题解决：")
    assert _paragraph_bold(document, "2. 性能调优：")
    assert not _paragraph_bold(document, "1.1 成功解决明细下载系统卡死问题")


def test_outcome_label_renders_as_peer_module_not_nested_head() -> None:
    # Real upload (resume de8ce72b): in the source PDF 项目成效 is a same-level
    # peer of 项目亮点. It must render as its own bold module label followed by
    # an unnumbered prose paragraph — never as a bold "4." nested head with a
    # "4.1" sub-point inside the 项目亮点 module.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目亮点：",
        "使用 Scala 编写 Spark Streaming 作业承接多源数据采集。",
        "用 Spark SQL 构建格式校验与逻辑校验两层规则。",
        "项目成效：",
        "平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "bullet",
        "bullet",
        "label",
        "plain",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("项目亮点：", section)
    # Hygiene strips the trailing period from bullet points only; the plain
    # outcome prose keeps its period and renders without any number marker.
    assert texts[i : i + 5] == [
        "项目亮点：",
        "1. 使用 Scala 编写 Spark Streaming 作业承接多源数据采集",
        "2. 用 Spark SQL 构建格式校验与逻辑校验两层规则",
        "项目成效：",
        "平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。",
    ]
    assert _paragraph_bold(document, "项目成效：")
    assert not _paragraph_bold(
        document, "平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。"
    )
    # No nested-head composite markers may mention the outcome module.
    assert not any(
        text.startswith(("3.", "4.")) and "项目成效" in text for text in texts
    )
    # Flush geometry: the peer-module prose starts exactly at the label edge
    # (no 0.6cm gutter; Cm(0) round-trips as 0.0), while big-four highlight
    # bullets keep their hanging indent so their marker sits at the label edge.
    assert _paragraph_left_indent_cm(
        document, "平台稳定支撑多家金融机构的数据报送，错报率下降约 70%。"
    ) in (None, 0.0)
    assert (
        _paragraph_left_indent_cm(
            document, "1. 使用 Scala 编写 Spark Streaming 作业承接多源数据采集"
        )
        == 0.6
    )


def test_peer_module_keeps_numbered_markers_but_flushes_plain_rows() -> None:
    # A non-big-four peer (责任描述， seen in stored resumes) can mix bullets and
    # prose: numbered rows keep their hanging marker at the label edge, while
    # unnumbered plain rows render flush with the label instead of indenting.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目亮点：",
        "完成核心链路重构。",
        "责任描述：",
        "参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理。",
        "参与流程引擎底层设计，支持可插拔的流程扩展。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "bullet",
        "label",
        "bullet",
        "plain",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("责任描述：", section)
    # Hygiene strips the bullet's trailing period; the plain row keeps it.
    assert texts[i : i + 3] == [
        "责任描述：",
        "1. 参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理",
        "参与流程引擎底层设计，支持可插拔的流程扩展。",
    ]
    assert (
        _paragraph_left_indent_cm(
            document, "1. 参与异步任务链路重构，基于 RabbitMQ 实现任务异步处理"
        )
        == 0.6
    )
    assert _paragraph_left_indent_cm(
        document, "参与流程引擎底层设计，支持可插拔的流程扩展。"
    ) in (None, 0.0)


@pytest.mark.parametrize(
    "outcome_label",
    ["项目效果：", "工作成效：", "落地效果：", "量化成效：", "业务成效："],
)
def test_outcome_aliases_render_as_peer_module_labels(outcome_label: str) -> None:
    # Every 成效/效果 outcome name is a known sub-label: it opens a peer module
    # whose list restarts at 1 instead of continuing the highlight numbering.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目亮点：",
        "完成核心链路重构。",
        outcome_label,
        "交付周期缩短 40%。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = ["label", "bullet", "label", "plain"]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("项目亮点：", section)
    assert texts[i : i + 4] == [
        "项目亮点：",
        "1. 完成核心链路重构",
        outcome_label,
        "交付周期缩短 40%。",
    ]
    assert _paragraph_bold(document, outcome_label)
    # The peer prose is flush with the label; the highlight bullet keeps the
    # hanging gutter.
    assert _paragraph_left_indent_cm(document, "交付周期缩短 40%。") in (
        None,
        0.0,
    )
    assert _paragraph_left_indent_cm(document, "1. 完成核心链路重构") == 0.6


def test_bare_group_headings_render_as_hierarchical_numbered_heads() -> None:
    # Bare bold sub-headings without a colon ("架构演进与技术债务治理"),
    # stored as plain rows followed by bullets, render as level-1 bold
    # numbered points with 1.1/1.2 composite sub-points (邹利平.pdf shape).
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "核心职责与成果：",
        "架构演进与技术债务治理",
        "担任商城板块技术负责人，主导架构设计与版本迭代。",
        "梳理历史技术债务，建立代码质量规范。",
        "主导促销中心组件设计",
        "将营销活动流程组件化，提升代码复用性。",
        "新活动接入周期缩短 30%，支撑十万级 GMV 交易。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "plain",
        "bullet",
        "bullet",
        "plain",
        "bullet",
        "bullet",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    # "项目职责：" also appears under 工作经历; anchor on the 项目经验 section.
    section = texts.index("项目经验")
    i = texts.index("项目职责：", section)
    assert texts[i + 1 : i + 7] == [
        "1. 架构演进与技术债务治理",
        "1.1 担任商城板块技术负责人，主导架构设计与版本迭代",
        "1.2 梳理历史技术债务，建立代码质量规范",
        "2. 主导促销中心组件设计",
        "2.1 将营销活动流程组件化，提升代码复用性",
        "2.2 新活动接入周期缩短 30%，支撑十万级 GMV 交易",
    ]
    assert _paragraph_bold(document, "1. 架构演进与技术债务治理")
    assert _paragraph_bold(document, "2. 主导促销中心组件设计")
    assert not _paragraph_bold(
        document, "1.1 担任商城板块技术负责人，主导架构设计与版本迭代"
    )


def test_source_numbered_plain_rows_are_not_promoted_to_group_heads() -> None:
    # "2）机审"-style enumeration rows stay ordinary numbered points; they are
    # never bold nested heads.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目职责：",
        "1）系统需求调研",
        "2）功能设计",
        "负责核心模块开发。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = [
        "label",
        "plain",
        "plain",
        "bullet",
    ]
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("项目职责：", section)
    assert texts[i + 1 : i + 4] == [
        "1. 系统需求调研",
        "2. 功能设计",
        "3. 负责核心模块开发",
    ]
    assert not _paragraph_bold(document, "1. 系统需求调研")


def test_bullet_styled_group_heads_render_as_hierarchical_heads() -> None:
    # 邹利平.pdf 沃尔沃内领商城 shape: the weak model stored group titles as
    # ordinary bullets. The structural planner (>=2 heads per module, each
    # followed by detail-shaped rows) still renders them as bold level-1
    # points with 1.1/1.2 composite sub-points.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目职责",
        "系统从 0 到 1 搭建",
        "主导内领商城架构设计与核心模块开发，负责需求评审与落地。",
        "设计并实现三方系统对接的高可用方案",
        "履约层策略化重构",
        "基于策略模式重构订单履约层，新增履约方式零侵入。",
        "自研轻量级流程编排框架",
        "将业务流程拆解为可复用原子节点并支持多流程共享。",
        "新订单类型接入周期缩短 40%。",
        "商品初始化同步方案",
        "通过分类治理与多轮对账，保障商品同步准确率 100%。",
    ]
    data["personalProjects"][0]["descriptionStyles"] = ["label"] + ["bullet"] * 10
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("项目职责", section)
    assert texts[i + 1 : i + 11] == [
        "1. 系统从 0 到 1 搭建",
        "1.1 主导内领商城架构设计与核心模块开发，负责需求评审与落地",
        "1.2 设计并实现三方系统对接的高可用方案",
        "2. 履约层策略化重构",
        "2.1 基于策略模式重构订单履约层，新增履约方式零侵入",
        "3. 自研轻量级流程编排框架",
        "3.1 将业务流程拆解为可复用原子节点并支持多流程共享",
        "3.2 新订单类型接入周期缩短 40%",
        "4. 商品初始化同步方案",
        "4.1 通过分类治理与多轮对账，保障商品同步准确率 100%",
    ]
    assert _paragraph_bold(document, "1. 系统从 0 到 1 搭建")
    assert _paragraph_bold(document, "4. 商品初始化同步方案")
    assert not _paragraph_bold(
        document, "1.1 主导内领商城架构设计与核心模块开发，负责需求评审与落地"
    )


def test_flat_peer_bullets_never_render_as_nested_heads() -> None:
    # 叶宏汉.pdf shape: uniformly short "负责…" peer duties with no
    # head/detail alternation stay a flat level-1 numbered list.
    data = _full_resume_data()
    data["personalProjects"][0]["description"] = [
        "项目职责：",
        "负责内网穿透项目单连接多路复用通信架构的设计与实现",
        "负责自定义二进制通信协议设计与帧解析实现",
        "负责高吞吐传输与反压机制建设",
        "负责分布式长连接注册与路由方案设计",
        "负责长连接重连与服务滚动升级机制实现",
    ]
    data["personalProjects"][0]["descriptionStyles"] = ["label"] + ["bullet"] * 5
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    section = texts.index("项目经验")
    i = texts.index("项目职责：", section)
    assert texts[i + 1 : i + 6] == [
        "1. 负责内网穿透项目单连接多路复用通信架构的设计与实现",
        "2. 负责自定义二进制通信协议设计与帧解析实现",
        "3. 负责高吞吐传输与反压机制建设",
        "4. 负责分布式长连接注册与路由方案设计",
        "5. 负责长连接重连与服务滚动升级机制实现",
    ]
    assert not _paragraph_bold(document, "3. 负责高吞吐传输与反压机制建设")


def test_source_numbering_stripped_from_skills_and_single_points_unnumbered() -> None:
    data = _full_resume_data()
    document = _build_doc(data)
    texts = _paragraph_texts(document)
    i_skills = _heading_index(texts, "专业技能")
    assert texts[i_skills + 1] == "1. Java / Spring 生态"
    assert texts[i_skills + 2] == "2. Python"
    assert texts[i_skills + 3] == "3. 团队管理"

    # Single-point custom stringLists render as one plain paragraph.
    data["customSections"]["hobbies"]["strings"] = ["只有一项"]
    document_single = _build_doc(data)
    texts_single = _paragraph_texts(document_single)
    assert "只有一项" in texts_single
    assert "1. 只有一项" not in texts_single


def test_custom_sections_keep_source_shape_and_verbatim_titles() -> None:
    document = _build_doc(_full_resume_data())
    texts = _paragraph_texts(document)

    i_eval = _heading_index(texts, "个人总结")
    assert "1. 踏实肯干" in texts[i_eval + 1 :]
    assert "2. 持续学习" in texts[i_eval + 1 :]

    i_hobbies = _heading_index(texts, "兴趣爱好")
    assert texts[i_hobbies + 1] == "1. 阅读"
    assert texts[i_hobbies + 2] == "2. 跑步"

    # itemList: title/year line, bold subtitle, then description.
    i_papers = _heading_index(texts, "论文")
    tail = texts[i_papers + 1 :]
    assert any("某核心期刊论文" in line and "2019" in line for line in tail)
    # subtitle and location share one tab-separated line.
    assert any("第一作者" in line and "某期刊" in line for line in tail)
    assert "1. 提出一种新架构" in tail


def test_mismatched_string_list_items_render_their_content() -> None:
    # Weak extraction declared a stringList section but stored its entries in
    # ``items`` while strings stayed null: the DOCX heal chain must migrate
    # them so the block renders its entries instead of a title-only heading
    # (real case: leo resume's 「其它」 block with GitHub/blog links).
    data = copy.deepcopy(_full_resume_data())
    data["customSections"]["hobbies"] = {
        "sectionType": "stringList",
        "strings": None,
        "items": [
            {"id": 1, "title": "GitHub 开源项目：https://example.com/repo"},
            {"id": 2, "title": "个人技术站点：https://example.com/blog"},
        ],
        "text": None,
    }
    document = _build_doc(data)
    texts = _paragraph_texts(document)

    i_hobbies = _heading_index(texts, "兴趣爱好")
    assert texts[i_hobbies + 1] == "1. GitHub 开源项目：https://example.com/repo"
    assert texts[i_hobbies + 2] == "2. 个人技术站点：https://example.com/blog"


def test_personal_evaluation_alias_renders_as_self_introduction() -> None:
    # A source heading 「个人评价」 is the self-introduction block: the DOCX
    # chrome renders it 自我介绍 (never the verbatim source title) and it keeps
    # the terminal slot after the custom-section cluster.
    data = copy.deepcopy(_full_resume_data())
    for row in data["sectionMeta"]:
        if row["key"] == "self_evaluation":
            row["displayName"] = "个人评价"
    document = _build_doc(data, language="zh")
    texts = _paragraph_texts(document)
    assert "自我介绍" in texts
    assert "个人评价" not in texts
    assert _heading_index(texts, "论文") < _heading_index(texts, "自我介绍")


def test_chrome_follows_content_language_when_language_omitted() -> None:
    zh_data = _full_resume_data()
    document = _build_doc(zh_data, language=None)
    assert "工作经历" in _paragraph_texts(document)

    en_data = copy.deepcopy(zh_data)
    en_data["personalInfo"] = {
        "name": "John Doe",
        "gender": "",
        "age": "",
        "educationLevel": "",
        "workYears": "",
        "title": "Backend Engineer",
        "location": "",
        "email": "john@example.com",
    }
    en_data["workExperience"][0]["company"] = "Acme"
    en_data["workExperience"][0]["department"] = "Platform"
    en_data["workExperience"][0]["title"] = "Engineer"
    en_data["workExperience"][0]["location"] = ""
    en_data["workExperience"][0]["years"] = "2020 - 2024"
    en_data["workExperience"][0]["description"] = ["Owned the platform"]
    en_data["workExperience"][0]["descriptionStyles"] = ["bullet"]
    en_data["personalProjects"] = []
    en_data["education"][0]["institution"] = "Some University"
    en_data["education"][0]["description"] = "CS"
    en_data["education"][0]["degree"] = "BSc"
    en_data["summary"] = "Years of backend experience"
    en_data["additional"] = {"technicalSkills": ["Python", "Go"]}
    en_data["customSections"] = {}
    en_data["sectionMeta"] = []
    en_document = _build_doc(en_data, language=None)
    en_text = _paragraph_texts(en_document)
    assert "Experience" in en_text
    assert "工作经历" not in en_text


def test_english_chrome() -> None:
    document = _build_doc(_full_resume_data(), language="en-US")
    texts = _paragraph_texts(document)
    for heading in (
        "Education",
        "Summary",
        "Skills",
        "Training & Certifications",
        "Awards",
        "Experience",
        "Projects",
    ):
        assert heading in texts
    # Late modules land after Projects even under English chrome.
    en_indices = [
        _heading_index(texts, title)
        for title in (
            "Skills",
            "Experience",
            "Projects",
            "Training & Certifications",
            "Awards",
        )
    ]
    assert en_indices == sorted(en_indices)
    # Facts live in the borderless header grid with English chrome labels.
    header_cells = _header_grid_texts(document)
    assert "Gender: 男" in header_cells
    assert "Foreign Languages: 英语四级、日语N2" in header_cells
    assert "Website: liyong.example.com" in header_cells
    # Custom Chinese titles stay verbatim even under English chrome.
    assert "个人总结" in texts


def test_input_dict_is_not_mutated() -> None:
    data = _full_resume_data()
    snapshot = copy.deepcopy(data)
    build_resume_docx(data, language="zh")
    assert data == snapshot


def test_non_dict_input_rejected() -> None:
    with pytest.raises(ValueError, match="must be a dict"):
        build_resume_docx("not-a-dict")  # type: ignore[arg-type]


def test_empty_optional_sections_do_not_render_headings() -> None:
    data = _full_resume_data()
    data["additional"]["certificationsTraining"] = []
    data["additional"]["awards"] = []
    document = _build_doc(data)
    texts = _paragraph_texts(document)
    assert "培训与证书" not in texts
    assert "荣誉奖项" not in texts
    assert "专业技能" in texts


def test_late_modules_anchor_before_selfeval_with_legacy_honors_custom_row() -> None:
    """A legacy 荣誉证书 row rides the custom cluster before the late modules."""
    data = _full_resume_data()
    data["customSections"]["honors_cert"] = {
        "sectionType": "stringList",
        "strings": ["国家科技进步二等奖"],
    }
    data["sectionMeta"].append(
        _custom_meta("honors_cert", "荣誉证书", "stringList", 93)
    )
    document = _build_doc(data)
    texts = _paragraph_texts(document)
    indices = [
        _heading_index(texts, title)
        for title in ("论文", "荣誉证书", "培训与证书", "荣誉奖项", "个人总结")
    ]
    assert indices == sorted(indices)


def test_hidden_additional_section_hides_skills_certs_and_awards() -> None:
    """Hiding the additional meta row hides all three additional modules."""
    data = _full_resume_data()
    additional_template = next(
        copy.deepcopy(row) for row in DEFAULT_SECTION_META if row["key"] == "additional"
    )
    additional_template["isVisible"] = False
    data["sectionMeta"].insert(0, additional_template)
    document = _build_doc(data)
    texts = _paragraph_texts(document)
    assert "专业技能" not in texts
    assert "培训与证书" not in texts
    assert "荣誉奖项" not in texts
    blob = "\n".join(texts)
    assert "信息系统项目管理师" not in blob
    assert "上海市优秀工程师" not in blob


def test_late_modules_render_independently_when_only_one_present() -> None:
    # Only certifications: the cert module renders late, Awards is absent.
    certs_only = _full_resume_data()
    certs_only["additional"]["awards"] = []
    document = _build_doc(certs_only)
    texts = _paragraph_texts(document)
    assert "培训与证书" in texts
    assert "荣誉奖项" not in texts
    assert _heading_index(texts, "论文") < _heading_index(texts, "培训与证书")

    # Only awards: symmetric.
    awards_only = _full_resume_data()
    awards_only["additional"]["certificationsTraining"] = []
    document = _build_doc(awards_only)
    texts = _paragraph_texts(document)
    assert "荣誉奖项" in texts
    assert "培训与证书" not in texts
    assert _heading_index(texts, "论文") < _heading_index(texts, "荣誉奖项")


def test_resume_docx_headers_uses_utf8_filename_and_ascii_fallback() -> None:
    headers = resume_docx_headers("abcdef12-3456", "简历-李勇")
    disposition = headers["Content-Disposition"]
    assert disposition.startswith(
        'attachment; filename="resume-abcdef12.docx"; filename*=UTF-8\'\''
    )
    assert "%E7%AE%80%E5%8E%86-%E6%9D%8E%E5%8B%87.docx" in disposition
    assert DOCX_MEDIA_TYPE.startswith("application/vnd.openxmlformats")


def _misfiled_credentials_resume() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "王五"},
        "workExperience": [
            {
                "id": 1,
                "years": "2020 - 2024",
                "company": "某科技公司",
                "department": "",
                "location": "",
                "title": "工程师",
                "description": [
                    "负责支付系统开发",
                    "奖项：国家励志奖学金",
                    "证书：PMP项目管理证书",
                    "语言：英语六级",
                ],
                "descriptionStyles": ["bullet", "bullet", "bullet", "bullet"],
            }
        ],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "certificationsTraining": [],
            "awards": [],
            "languages": [],
        },
        "customSections": {},
    }


def test_docx_self_heal_relocates_misfiled_work_credentials() -> None:
    document = _build_doc(_misfiled_credentials_resume())
    texts = _paragraph_texts(document)

    # Award/cert items render in their independent late modules.
    i_certs = _heading_index(texts, "培训与证书")
    i_awards = _heading_index(texts, "荣誉奖项")
    assert i_certs < i_awards
    assert any("PMP项目管理证书" in text for text in texts[i_certs + 1 : i_awards])
    assert any("国家励志奖学金" in text for text in texts[i_awards + 1 :])

    # The language item reaches the header fact grid.
    header_cells = _header_grid_texts(document)
    assert "外语水平：英语六级" in header_cells

    # Nothing credential-related survives inside the work tables (the header
    # grid is tables[0] and legitimately holds the relocated language fact).
    cell_blob = "\n".join(
        cell.text
        for table in document.tables[1:]
        for row in table.rows
        for cell in row.cells
    )
    assert "某科技公司" in cell_blob  # the work entry itself still renders
    assert "国家励志奖学金" not in cell_blob
    assert "PMP项目管理证书" not in cell_blob
    assert "英语六级" not in cell_blob
    assert "奖项：" not in cell_blob
    assert "语言：" not in cell_blob


def test_docx_self_heal_relocates_language_under_english_fact_label() -> None:
    document = _build_doc(_misfiled_credentials_resume(), language="en")
    texts = _paragraph_texts(document)

    header_cells = _header_grid_texts(document)
    assert any(cell.startswith("Foreign Languages:") and "英语六级" in cell for cell in header_cells)
    i_awards = _heading_index(texts, "Awards")
    assert any("国家励志奖学金" in text for text in texts[i_awards + 1 :])
