"""Tests for the Word (.docx) diagnosis report renderer (V4 checklist).

The document exposes the same public contract as the API: each finding shows
its short ``topic`` location label, resume-grounded evidence and a fix — the
confidential rubric standard (criteria, QC guidance, G-rules) is never rendered
anywhere (body or appendix).
"""

import io
from datetime import datetime

from docx import Document

from app.schemas.diagnosis import (
    CompetencyModelInfo,
    DiagnosisItemResult,
    DiagnosisReport,
    DimensionResult,
    RatingCounts,
    RedLineStatus,
)
from app.services.diagnosis_docx import (
    DOCX_MEDIA_TYPE,
    build_diagnosis_docx,
    diagnosis_docx_stem,
    docx_headers,
)


def _item(item_id: int, rating: str, **kwargs: object) -> DiagnosisItemResult:
    defaults: dict[str, object] = {
        "dimension": "content",
        "dimension_name": "撰写规范",
        "sub_dimension": "经历",
        "topic": f"检查位置 {item_id}",
        "severity": "normal",
        "judgment_method": "objective",
        "evidence": f"简历证据 {item_id}",
        "suggestion": f"优化动作 {item_id}",
    }
    defaults.update(kwargs)
    return DiagnosisItemResult(id=item_id, rating=rating, **defaults)  # type: ignore[arg-type]


def _report(**overrides: object) -> DiagnosisReport:
    data: dict[str, object] = {
        "resume_id": "r1",
        "spec_version": "V4",
        "language": "zh",
        "target_title": "Java 开发工程师",
        "competency_model": None,
        "counts": RatingCounts(conform=1, partial=1, nonconform=1, na=1, effective=3),
        "redline_passed": False,
        "failed_redline_ids": [15],
        "dimensions": [
            DimensionResult(
                key="appearance",
                name="简历外观",
                counts=RatingCounts(conform=1, effective=1),
            ),
            DimensionResult(
                key="content",
                name="撰写规范",
                counts=RatingCounts(partial=1, effective=1),
            ),
            DimensionResult(
                key="compliance",
                name="风险与合规",
                counts=RatingCounts(nonconform=1, effective=1),
            ),
            DimensionResult(
                key="competence",
                name="专业能力",
                counts=RatingCounts(na=1, effective=0),
            ),
        ],
        "redlines": [
            RedLineStatus(
                id=15,
                topic="风险与合规",
                passed=False,
                rating="nonconform",
                evidence="简历正文出现疑似身份证号 110101…34",
                suggestion="删除身份证号等敏感信息，改用必要的联系方式",
            )
        ],
        "items": [
            _item(
                1,
                "conform",
                dimension="appearance",
                dimension_name="简历外观",
                sub_dimension="格式规范",
                topic="格式规范",
                evidence="顺序正确",
                suggestion="",
            ),
            _item(
                11,
                "partial",
                topic="荣誉证书",
                evidence="证书与岗位相关性弱",
                suggestion="保留与目标岗位相关证书",
                judgment_method="subjective",
            ),
            _item(
                15,
                "nonconform",
                dimension="compliance",
                dimension_name="风险与合规",
                sub_dimension="风险与合规",
                severity="redline",
                topic="风险与合规",
                evidence="简历正文出现疑似身份证号 110101…34",
                suggestion="删除身份证号等敏感信息，改用必要的联系方式",
            ),
            _item(
                21,
                "na",
                dimension="competence",
                dimension_name="专业能力",
                sub_dimension="项目管理",
                topic="项目管理",
                evidence="未提供目标岗位 JD，不适用",
                suggestion="",
                judgment_method="subjective",
            ),
        ],
        "warnings": [],
    }
    data.update(overrides)
    return DiagnosisReport(**data)  # type: ignore[arg-type]


def _open_docx(blob: bytes) -> Document:
    return Document(io.BytesIO(blob))


def _doc_text(doc: Document) -> str:
    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def _table_text(doc: Document) -> str:
    return "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )


def test_docx_is_valid_zip_and_contains_location_problem_and_fix() -> None:
    blob = build_diagnosis_docx(_report(), candidate_name="王浩", resume_title="后端简历")

    # Office Open XML: ZIP local file header starts with PK\x03\x04.
    assert blob[:4] == b"PK\x03\x04"

    doc = _open_docx(blob)
    text = _doc_text(doc)

    assert "简历诊断报告" in text
    assert "王浩" in text
    # The score-era wording is gone.
    assert "/100" not in text
    assert "总分" not in text
    # Counts line with na excluded from the applicable total.
    assert "适用 3 项" in text
    assert "不适用 1" in text
    # Target job title is surfaced in the overall section.
    assert "诊断目标岗位" in text
    assert "Java 开发工程师" in text
    # Failed red line: public topic heading + location + problem + fix.
    assert "风险与合规" in text
    assert "检查位置" in text
    assert "问题描述" in text
    assert "简历正文出现疑似身份证号 110101…34" in text
    assert "优化方案" in text
    assert "删除身份证号等敏感信息" in text
    # Problems ordered nonconform (#15, red line) before partial (#11); the
    # conforming item is excluded from the problems section but stays in the
    # appendix table.
    assert text.index("#15") < text.index("#11")
    assert "顺序正确" not in text


def test_findings_render_as_numbered_paragraphs_one_point_per_line() -> None:
    report = _report(
        redlines=[
            RedLineStatus(
                id=15,
                topic="风险与合规",
                passed=False,
                rating="nonconform",
                evidence="疑似身份证号 110101…34\n疑似手机号 138****0000",
                suggestion="删除身份证号\n删除手机号",
            )
        ],
        items=[
            _item(
                9,
                "partial",
                dimension="projects",
                dimension_name="项目经历",
                topic="技术栈",
                evidence="项目 A 缺少技术栈字段。\n项目 B 职责没有量化结果。",
                suggestion="为每个项目补一行技术栈。\n在职责中补充数字结果。",
            )
        ],
    )
    texts = [paragraph.text for paragraph in _open_docx(build_diagnosis_docx(report)).paragraphs]

    # Per-item finding: each point is its own "N. …" paragraph restarting at 1.
    assert "1. 项目 A 缺少技术栈字段。" in texts
    assert "2. 项目 B 职责没有量化结果。" in texts
    assert "1. 为每个项目补一行技术栈。" in texts
    assert "2. 在职责中补充数字结果。" in texts
    # Failed red line problem/fix are numbered lists too.
    assert "1. 疑似身份证号 110101…34" in texts
    assert "2. 疑似手机号 138****0000" in texts
    assert "1. 删除身份证号" in texts
    assert "2. 删除手机号" in texts


def test_single_point_finding_is_numbered_too() -> None:
    texts = [
        paragraph.text
        for paragraph in _open_docx(build_diagnosis_docx(_report())).paragraphs
    ]
    # Default fixture item #11 carries single-line evidence/suggestion.
    assert "1. 证书与岗位相关性弱" in texts
    assert "1. 保留与目标岗位相关证书" in texts


def test_docx_never_renders_rubric_standards() -> None:
    doc = _open_docx(build_diagnosis_docx(_report()))
    whole = _doc_text(doc) + "\n" + _table_text(doc)
    # No criterion/qc field exists on the schema; guard against rule-style text
    # leaking through evidence/topic strings as well.
    assert "判定标准" not in whole
    assert "检查项细则" not in whole
    assert "质检违规" not in whole
    assert "一票否决" not in whole
    assert "全局通用规则" not in whole


def test_dimension_table_uses_counts_with_zero_effective_row() -> None:
    doc = _open_docx(build_diagnosis_docx(_report()))
    dimension_table = doc.tables[0]
    assert [cell.text for cell in dimension_table.rows[0].cells] == [
        "维度",
        "适用",
        "符合",
        "部分符合",
        "不符合",
        "不适用",
    ]
    rows = {row.cells[0].text: [cell.text for cell in row.cells] for row in dimension_table.rows[1:]}
    assert rows["风险与合规"] == ["风险与合规", "1", "0", "0", "1", "0"]
    assert rows["专业能力"] == ["专业能力", "0", "0", "0", "0", "1"]


def test_competency_match_line_uses_competence_dimension_counts() -> None:
    report = _report(
        competency_model=CompetencyModelInfo(key="java-p5", name="P5 高级Java开发工程师能力模型"),
        dimensions=[
            DimensionResult(key="content", name="撰写规范", counts=RatingCounts(effective=0)),
            DimensionResult(
                key="competence",
                name="专业能力",
                counts=RatingCounts(conform=2, partial=2, nonconform=1, effective=5),
            ),
        ],
    )
    text = _doc_text(_open_docx(build_diagnosis_docx(report)))
    assert "能力模型匹配：P5 高级Java开发工程师能力模型" in text
    assert "适用 5 项" in text


def test_appendix_lists_every_item_with_topics_not_standards() -> None:
    doc = _open_docx(build_diagnosis_docx(_report()))
    appendix = doc.tables[1]
    assert [cell.text for cell in appendix.rows[0].cells] == [
        "序号",
        "维度",
        "检查位置",
        "评级",
    ]
    ids = {row.cells[0].text for row in appendix.rows}
    assert ids == {"序号", "1", "11", "15", "21"}
    table_text = _table_text(doc)
    # Public topic labels are shown; the confidential standards are not.
    assert "格式规范" in table_text
    assert "项目管理" in table_text
    assert "风险与合规" in table_text
    assert "判定标准" not in table_text


def test_passed_redlines_omit_failure_section() -> None:
    report = _report()
    report.redline_passed = True
    report.failed_redline_ids = []
    report.redlines = [
        RedLineStatus(
            id=15,
            topic="风险与合规",
            passed=True,
            rating="conform",
            evidence="未发现身份证号等敏感信息",
            suggestion="",
        )
    ]
    doc = _open_docx(build_diagnosis_docx(report))
    text = _doc_text(doc)
    assert "1 条红线检查全部通过" in text
    assert "二、未通过红线项" not in text


def test_english_chrome_used_for_english_report() -> None:
    report = _report(language="en")
    doc = _open_docx(build_diagnosis_docx(report))
    text = _doc_text(doc)
    assert "Resume Diagnosis Report" in text
    assert "3 applicable" in text
    assert "Nonconform" in text
    assert "Target role" in text
    assert "Area" in text


def test_docx_headers_include_rfc5987_utf8_filename() -> None:
    headers = docx_headers("abcdef123456", "简历诊断报告-王浩-20261030-2156")
    disposition = headers["Content-Disposition"]
    assert 'filename="resume-diagnosis-abcdef12.docx"' in disposition
    assert "filename*=UTF-8''" in disposition
    assert "%E7%AE%80%E5%8E%86" in disposition
    assert DOCX_MEDIA_TYPE.startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_diagnosis_docx_stem_uses_report_name_and_minute_stamp() -> None:
    # 简历诊断报告-姓名-时间
    now = datetime(2026, 10, 30, 21, 56)
    assert (
        diagnosis_docx_stem("王浩", "abcdef123456", now=now)
        == "简历诊断报告-王浩-20261030-2156"
    )


def test_diagnosis_docx_stem_trims_and_sanitizes_illegal_characters() -> None:
    now = datetime(2026, 10, 30, 9, 5)
    assert diagnosis_docx_stem(" 王/浩:X ", "abcdef123456", now=now) == (
        "简历诊断报告-王-浩-X-20261030-0905"
    )


def test_diagnosis_docx_stem_falls_back_to_resume_id_without_name() -> None:
    now = datetime(2026, 10, 30, 21, 56)
    assert diagnosis_docx_stem(None, "abcdef123456", now=now) == (
        "简历诊断报告-resume-abcdef12-20261030-2156"
    )
    assert diagnosis_docx_stem("   ", "abcdef123456", now=now) == (
        "简历诊断报告-resume-abcdef12-20261030-2156"
    )
