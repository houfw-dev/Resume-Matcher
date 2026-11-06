"""Render a V4-optimized DiagnosisReport as a downloadable Word (.docx) document.

The document focuses on *where the problems are and how to fix them*: every
partial/nonconform item is listed with its short problem-location label
(``topic`` — the full rubric standard never leaves the server), the
resume-grounded evidence (the problem description) and the optimization action
(the fix). Checklist counts, the red-line verdict and a full-item appendix are
included for completeness; the appendix carries the same public labels, not
the rule text.

The November-2026 rubric carries no score, so there is no points/band section.

python-docx is already a runtime dependency (it backs the markitdown DOCX
reader), so this adds no new dependency.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.schemas.diagnosis import DiagnosisItemResult, DiagnosisReport

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# Static chrome translated for the languages the content pipeline can emit;
# anything outside these falls back to English. The dynamic content (criteria,
# evidence, suggestions) is already in the configured content language.
_CHROME: dict[str, dict[str, str]] = {
    "zh": {
        "title": "简历诊断报告",
        "subtitle": "依据《简历诊断规范 {version}》（{dimensions} 维度 / {items} 检查项 / {redlines} 红线）",
        "candidate": "候选人",
        "resume": "简历",
        "generated": "生成日期",
        "target": "诊断目标岗位",
        "competency_match": (
            "能力模型匹配：{name}：适用 {effective} 项 —— 符合 {conform}、"
            "部分符合 {partial}、不符合 {nonconform}；不适用 {na} 项。"
        ),
        "summary_heading": "一、总体结论",
        "counts_line": (
            "检查结果：适用 {effective} 项 —— 符合 {conform}、部分符合 {partial}、"
            "不符合 {nonconform}；不适用 {na} 项。"
        ),
        "redline_pass": "红线结论：{count} 条红线检查全部通过。",
        "redline_fail": "红线结论：{count} 条红线未通过，此简历不可直接投递，须优先整改。",
        "redlines_heading": "二、未通过红线项",
        "dimensions_heading": "三、各维度检查结果",
        "problems_heading": "四、问题描述与优化方案",
        "problems_intro": "下列检查项评级为「不符合」或「部分符合」，红线项优先、按维度排列；问题描述均结合本简历实际内容给出。",
        "appendix_heading": "五、全部检查项一览",
        "th_dimension": "维度",
        "th_applicable": "适用",
        "th_conform": "符合",
        "th_partial": "部分符合",
        "th_nonconform": "不符合",
        "th_na": "不适用",
        "th_id": "序号",
        "th_topic": "检查位置",
        "th_rating": "评级",
        "location_label": "检查位置",
        "problem_label": "问题描述",
        "fix_label": "优化方案",
        "na": "不适用",
        "no_problems": "所有检查项均符合或不适用，无需整改。",
    },
    "en": {
        "title": "Resume Diagnosis Report",
        "subtitle": "Rubric {version} ({dimensions} dimensions / {items} checks / {redlines} red lines)",
        "candidate": "Candidate",
        "resume": "Resume",
        "generated": "Generated",
        "target": "Target role",
        "competency_match": (
            "Competency match ({name}): {effective} applicable — {conform} conform, "
            "{partial} partial, {nonconform} nonconform; {na} N/A."
        ),
        "summary_heading": "1. Overall Result",
        "counts_line": (
            "Checklist: {effective} applicable — {conform} conform, {partial} partial, "
            "{nonconform} nonconform; {na} not applicable."
        ),
        "redline_pass": "Red lines: all {count} checks passed.",
        "redline_fail": "Red lines: {count} check(s) failed — do not deliver this resume as-is; fix these first.",
        "redlines_heading": "2. Failed Red Lines",
        "dimensions_heading": "3. Results by Dimension",
        "problems_heading": "4. Problems and Optimization Actions",
        "problems_intro": "Items rated Nonconform or Partial, red lines first and then by dimension. Problem descriptions cite the resume itself.",
        "appendix_heading": "5. All Checks",
        "th_dimension": "Dimension",
        "th_applicable": "Applicable",
        "th_conform": "Conform",
        "th_partial": "Partial",
        "th_nonconform": "Nonconform",
        "th_na": "N/A",
        "th_id": "#",
        "th_topic": "Area",
        "th_rating": "Rating",
        "location_label": "Area",
        "problem_label": "Problem",
        "fix_label": "Optimization action",
        "na": "N/A",
        "no_problems": "Every check conforms or is not applicable; no action needed.",
    },
}

_RATINGS: dict[str, dict[str, str]] = {
    "zh": {"conform": "符合", "partial": "部分符合", "nonconform": "不符合", "na": "不适用"},
    "en": {
        "conform": "Conforms",
        "partial": "Partial",
        "nonconform": "Nonconform",
        "na": "N/A",
    },
}

_SEVERITY_TAGS: dict[str, dict[str, str]] = {
    "zh": {"redline": "红线"},
    "en": {"redline": "Red line"},
}

_SEVERITY_ORDER = {"redline": 0, "normal": 1}
_RATING_ORDER = {"nonconform": 0, "partial": 1, "conform": 2, "na": 3}
_INK = RGBColor(0, 0, 0)
_RED = RGBColor(0xDC, 0x26, 0x26)
_ORANGE = RGBColor(0xC2, 0x57, 0x00)
_GREEN = RGBColor(0x15, 0x80, 0x3D)
_RATING_COLOR = {
    "conform": _GREEN,
    "partial": _ORANGE,
    "nonconform": _RED,
    "na": RGBColor(0x70, 0x70, 0x70),
}


def _chrome(language: str) -> dict[str, str]:
    return _CHROME.get(language, _CHROME["en"])


def _rating_label(language: str, rating: str) -> str:
    table = _RATINGS.get(language, _RATINGS["en"])
    return table.get(rating, rating)


def _severity_tag(language: str, severity: str) -> str:
    table = _SEVERITY_TAGS.get(language, _SEVERITY_TAGS["en"])
    return table.get(severity, "")


def _set_east_asian_font(document: Document) -> None:
    """Make Chinese characters render in a CJK-aware font in Word."""
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    run_font = style.element.rPr.rFonts
    run_font.set(qn("w:eastAsia"), "宋体")


def _style_run(run: object, *, east_asian: str = "宋体", size: float | None = None) -> None:
    """Assign an East Asian font to a run.

    python-docx only creates the rPr/rFonts node after ``font.name`` is set, so
    touching ``rFonts`` directly on a fresh run raises AttributeError.
    """
    run.font.name = "Calibri"  # type: ignore[attr-defined]
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east_asian)
    if size is not None:
        run.font.size = Pt(size)  # type: ignore[attr-defined]


def _add_heading(document: Document, text: str, level: int = 1) -> None:
    paragraph = document.add_heading(level=level)
    run = paragraph.add_run(text)
    run.font.color.rgb = _INK
    _style_run(run, east_asian="黑体")


def _add_label_value(
    document: Document,
    label: str,
    value: str,
    *,
    language: str = "zh",
    color: RGBColor | None = None,
    numbered: bool = False,
) -> None:
    separator = "：" if language == "zh" else ": "
    if not numbered:
        paragraph = document.add_paragraph()
        label_run = paragraph.add_run(f"{label}{separator}")
        label_run.bold = True
        value_run = paragraph.add_run(value)
        if color is not None:
            value_run.font.color.rgb = color
        return

    # Findings (problem description / optimization action) render as an
    # ordered list: bold label on its own line, one hanging-indented
    # numbered paragraph per newline-separated point.
    points = [point.strip() for point in value.splitlines() if point.strip()]
    if not points:
        return
    label_paragraph = document.add_paragraph()
    label_run = label_paragraph.add_run(f"{label}{separator}")
    label_run.bold = True
    for index, point in enumerate(points, start=1):
        point_paragraph = document.add_paragraph()
        point_paragraph.paragraph_format.left_indent = Cm(0.6)
        point_paragraph.paragraph_format.first_line_indent = Cm(-0.6)
        point_paragraph.add_run(f"{index}.")
        value_run = point_paragraph.add_run(f" {point}")
        if color is not None:
            value_run.font.color.rgb = color


def _problem_items(report: DiagnosisReport) -> list[DiagnosisItemResult]:
    """Nonconform first, then partial; red lines and lower item ids first."""
    problems = [item for item in report.items if item.rating in ("nonconform", "partial")]
    return sorted(
        problems,
        key=lambda item: (
            _RATING_ORDER[item.rating],
            _SEVERITY_ORDER.get(item.severity, 1),
            item.dimension,
            item.id,
        ),
    )


def _item_location(item: DiagnosisItemResult) -> str:
    """Public location label: dimension / sub-dimension (no rule text)."""
    if item.sub_dimension and item.sub_dimension != item.dimension_name:
        return f"{item.dimension_name} / {item.sub_dimension}"
    return item.dimension_name


def build_diagnosis_docx(
    report: DiagnosisReport,
    *,
    candidate_name: str | None = None,
    resume_title: str | None = None,
) -> bytes:
    """Render the report as .docx bytes. Static chrome follows report.language."""
    language = report.language or "zh"
    chrome = _chrome(language)
    document = Document()
    _set_east_asian_font(document)

    # --- Title block ------------------------------------------------------
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run(chrome["title"])
    title_run.bold = True
    title_run.font.color.rgb = _INK
    _style_run(title_run, east_asian="黑体", size=20)

    subtitle_text = chrome["subtitle"].format(
        version=report.spec_version,
        dimensions=len(report.dimensions),
        items=len(report.items),
        redlines=len(report.redlines),
    )
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle_run = subtitle.add_run(subtitle_text)
    subtitle_run.font.size = Pt(9)
    subtitle_run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    meta = document.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_parts = [f"{chrome['generated']}：{date.today().isoformat()}"]
    if candidate_name:
        meta_parts.append(f"{chrome['candidate']}：{candidate_name}")
    if resume_title:
        meta_parts.append(f"{chrome['resume']}：{resume_title}")
    meta_run = meta.add_run("　|　".join(meta_parts))
    meta_run.font.size = Pt(9)
    meta_run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # --- 1. Overall result ------------------------------------------------
    _add_heading(document, chrome["summary_heading"])
    counts = report.counts
    document.add_paragraph(
        chrome["counts_line"].format(
            effective=counts.effective,
            conform=counts.conform,
            partial=counts.partial,
            nonconform=counts.nonconform,
            na=counts.na,
        )
    )
    if report.target_title:
        _add_label_value(document, chrome["target"], report.target_title, language=language)
    competency_dim = next(
        (dim for dim in report.dimensions if dim.key == "competence"), None
    )
    if report.competency_model and competency_dim is not None:
        model_counts = competency_dim.counts
        document.add_paragraph(
            chrome["competency_match"].format(
                name=report.competency_model.name,
                effective=model_counts.effective,
                conform=model_counts.conform,
                partial=model_counts.partial,
                nonconform=model_counts.nonconform,
                na=model_counts.na,
            )
        )
    if report.redline_passed:
        passed_paragraph = document.add_paragraph()
        passed_run = passed_paragraph.add_run(
            chrome["redline_pass"].format(count=len(report.redlines))
        )
        passed_run.bold = True
        passed_run.font.color.rgb = _GREEN
    else:
        fail_count = len(report.failed_redline_ids)
        redline_paragraph = document.add_paragraph()
        redline_run = redline_paragraph.add_run(chrome["redline_fail"].format(count=fail_count))
        redline_run.bold = True
        redline_run.font.color.rgb = _RED

    # --- 2. Failed red lines ---------------------------------------------
    failed = [redline for redline in report.redlines if not redline.passed]
    items_by_id = {item.id: item for item in report.items}
    if failed:
        _add_heading(document, chrome["redlines_heading"])
        for redline in failed:
            heading = document.add_paragraph()
            tag = heading.add_run(f"#{redline.id} [{_severity_tag(language, 'redline')}] ")
            tag.bold = True
            tag.font.color.rgb = _RED
            heading.add_run(redline.topic).bold = True
            source_item = items_by_id.get(redline.id)
            if source_item is not None:
                _add_label_value(
                    document,
                    chrome["location_label"],
                    _item_location(source_item),
                    language=language,
                )
            _add_label_value(
                document,
                chrome["problem_label"],
                redline.evidence,
                language=language,
                numbered=True,
            )
            if redline.suggestion:
                _add_label_value(
                    document,
                    chrome["fix_label"],
                    redline.suggestion,
                    language=language,
                    numbered=True,
                )

    # --- 3. Per-dimension checklist counts --------------------------------
    _add_heading(document, chrome["dimensions_heading"])
    table = document.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for cell, text in zip(
        header_cells,
        (
            chrome["th_dimension"],
            chrome["th_applicable"],
            chrome["th_conform"],
            chrome["th_partial"],
            chrome["th_nonconform"],
            chrome["th_na"],
        ),
        strict=True,
    ):
        cell.paragraphs[0].add_run(text).bold = True
    for dimension in report.dimensions:
        counts = dimension.counts
        row = table.add_row().cells
        row[0].text = dimension.name
        row[1].text = str(counts.effective)
        row[2].text = str(counts.conform)
        row[3].text = str(counts.partial)
        row[4].text = str(counts.nonconform)
        row[5].text = str(counts.na)

    # --- 4. Problems and fixes -------------------------------------------
    _add_heading(document, chrome["problems_heading"])
    document.add_paragraph(chrome["problems_intro"])
    problems = _problem_items(report)
    if not problems:
        document.add_paragraph(chrome["no_problems"])
    else:
        current_dimension: str | None = None
        for item in problems:
            if item.dimension_name != current_dimension:
                current_dimension = item.dimension_name
                dimension_paragraph = document.add_paragraph()
                dimension_run = dimension_paragraph.add_run(current_dimension)
                dimension_run.bold = True
                dimension_run.font.size = Pt(12)

            heading = document.add_paragraph()
            if item.severity == "redline":
                tag_run = heading.add_run(f"#{item.id} [{_severity_tag(language, 'redline')}] ")
                tag_run.bold = True
                tag_run.font.color.rgb = _RED
            else:
                heading.add_run(f"#{item.id} ").bold = True
            heading.add_run(item.topic).bold = True
            rating_run = heading.add_run(f"  — {_rating_label(language, item.rating)}")
            rating_run.font.color.rgb = _RATING_COLOR[item.rating]
            rating_run.bold = True

            _add_label_value(
                document, chrome["location_label"], _item_location(item), language=language
            )
            if item.evidence:
                _add_label_value(
                    document,
                    chrome["problem_label"],
                    item.evidence,
                    language=language,
                    numbered=True,
                )
            if item.suggestion:
                _add_label_value(
                    document,
                    chrome["fix_label"],
                    item.suggestion,
                    language=language,
                    numbered=True,
                )

    # --- 5. Appendix: every checklist item --------------------------------
    _add_heading(document, chrome["appendix_heading"])
    appendix = document.add_table(rows=1, cols=4)
    appendix.style = "Table Grid"
    for cell, text in zip(
        appendix.rows[0].cells,
        (chrome["th_id"], chrome["th_dimension"], chrome["th_topic"], chrome["th_rating"]),
        strict=True,
    ):
        cell.paragraphs[0].add_run(text).bold = True
    for item in sorted(report.items, key=lambda entry: entry.id):
        row = appendix.add_row().cells
        row[0].text = str(item.id)
        row[1].text = item.dimension_name
        # Public location label only — the judged standard is never rendered.
        row[2].text = item.topic
        rating_paragraph = row[3].paragraphs[0]
        rating_run = rating_paragraph.add_run(_rating_label(language, item.rating))
        rating_run.font.color.rgb = _RATING_COLOR[item.rating]

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


_FILENAME_INVALID_RE = re.compile(r'[/\\:*?"<>|]')


def diagnosis_docx_stem(
    candidate_name: str | None,
    resume_id: str,
    now: datetime | None = None,
) -> str:
    """Filename stem for diagnosis Word exports.

    Format: 简历诊断报告-姓名-YYYYMMDD-HHMM (local time); without a name the
    id fragment is used so the download stays unique per resume. Characters
    illegal in filenames are replaced (mirrors the resume download helper).
    """
    moment = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    name_part = candidate_name.strip() if candidate_name else ""
    name_part = _FILENAME_INVALID_RE.sub("-", name_part)
    if not name_part:
        name_part = f"resume-{resume_id[:8]}"
    return f"简历诊断报告-{name_part}-{moment}"


def docx_headers(resume_id: str, filename_stem: str) -> dict[str, str]:
    """Content-Disposition with RFC 5987 UTF-8 filename plus ASCII fallback."""
    ascii_fallback = f"resume-diagnosis-{resume_id[:8]}.docx"
    quoted = quote(f"{filename_stem}.docx")
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"
        )
    }
