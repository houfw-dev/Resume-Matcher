"""Render structured ResumeData as a downloadable Word (.docx) resume.

Single canonical Word layout — it does NOT follow the seven visual
templates; every resume gets the same editable, ATS-friendly document.
Content semantics mirror the on-screen swiss-single template (and therefore
the PDF, which renders that template), so screen and export never disagree:

- section order / omitted-section healing come from
  :func:`app.services.section_order.canonicalize_section_meta` (the same
  canonicalizer the save path and the frontend renderer use);
- legacy plain department rows are lifted into the work header by
  :func:`app.services.parser.promote_work_departments`;
- description rows honour their ``descriptionStyles``: ``label`` renders as
  a bold standalone heading whose following bullets restart numbering at 1,
  ``plain`` renders unnumbered, ``bullet`` renders with hanging numbers;
- work headers are four columns (time | company | department | role, role
  NOT bold); projects (name | time | scale | role); education
  (time | institution | major | degree);
- technical skills render as an ordered list at the early ``additional``
  slot; certifications/awards each render as their own independent ordered
  list PROJECTED TO THE BACK of the resume (after the custom-section
  cluster, anchored before the other-branch education / the self-evaluation
  / the document end — the DOCX mirror of the frontend
  ``getRenderSections`` projection); languages only appear in the header
  fact grid;
- custom sections keep their source shape (text / stringList / itemList),
  and custom titles are verbatim except the one localized alias block
  (自我介绍).

This is the display-side Python mirror of the frontend renderers
(components/resume/list-format.ts, point-text-list.tsx,
resume-single-column.tsx); the sub-label sets below intentionally duplicate
the frontend copies, which themselves mirror parser.py. Keep all three in
sync.

python-docx is already a runtime dependency (it backs the markitdown DOCX
reader), so this adds no new dependency. Pure CPU: no LLM, no Chromium.
"""

from __future__ import annotations

import copy
import io
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.parser import (
    PROJECT_SUB_LABEL_CANONICAL,
    canonicalize_date_period,
    dedupe_resume_lists,
    extract_education_credentials,
    extract_misfiled_credentials,
    normalize_cjk_compat_deep,
    normalize_date_periods,
    normalize_text_hygiene,
    promote_work_departments,
    reconcile_custom_section_shapes,
    repair_project_label_regions,
    strip_markdown_emphasis_deep,
    strip_source_point_marker,
)
from app.services.section_order import (
    DEFAULT_SECTION_KEYS,
    SELF_INTRODUCTION_TITLE_ALIASES,
    SELFEVAL_SYMBOL,
    canonicalize_section_meta,
    classify_highest_degree,
    section_symbol,
)
from app.services.tech_terms import canonicalize_tech_terms

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# A4 content width with 2cm left/right margins.
_CONTENT_WIDTH_CM = 17.0
_META_COLOR = RGBColor(0x66, 0x66, 0x66)

# ---------------------------------------------------------------------------
# Static chrome — zh content gets Chinese chrome, everything else English.
# Mirrors resume.sections.* / resume.personalInfo.* / resume.additionalLabels.*
# in messages/{zh,en}.json.
# ---------------------------------------------------------------------------

_CHROME: dict[str, dict[str, str]] = {
    "zh": {
        # Header fact labels
        "gender": "性别",
        "age": "年龄",
        "education": "学历",
        "workYears": "工作年限",
        "jobIntention": "求职意向",
        "desiredCity": "意向城市",
        "phone": "电话",
        "email": "电子邮箱",
        "foreignLanguage": "外语水平",
        # Section titles
        "summary": "个人优势",
        "workExperience": "工作经历",
        "education_section": "教育背景",
        "personalProjects": "项目经验",
        "additional": "专业技能",
        # Independent modules (each gets its own section heading)
        "certifications": "培训与证书",
        "awards": "荣誉奖项",
        # Localized custom alias title
        "selfIntroduction": "自我介绍",
        # Filename prefix
        "file_prefix": "简历",
    },
    "en": {
        "gender": "Gender",
        "age": "Age",
        "education": "Education",
        "workYears": "Years of Experience",
        "jobIntention": "Job Objective",
        "desiredCity": "Desired City",
        "phone": "Phone",
        "email": "Email",
        "foreignLanguage": "Foreign Languages",
        "summary": "Summary",
        "workExperience": "Experience",
        "education_section": "Education",
        "personalProjects": "Projects",
        "additional": "Skills",
        "certifications": "Training & Certifications",
        "awards": "Awards",
        "selfIntroduction": "Self Introduction",
        "file_prefix": "Resume",
    },
}

_DEFAULT_SECTION_CHROME_KEY: dict[str, str] = {
    "summary": "summary",
    "workExperience": "workExperience",
    "education": "education_section",
    "personalProjects": "personalProjects",
    "additional": "additional",
}

# Mirrors components/resume/list-format.ts SUB_LABEL_CANDIDATES, which
# mirrors parser.py::_SUB_LABEL_CANDIDATES. Only used to promote LEGACY
# "plain" rows that are really bold sub-module headings.
_SUB_LABEL_CANDIDATES: frozenset[str] = frozenset(
    {
        "技术难点及亮点",
        "技术难度及解决方案",
        "技术架构",
        "系统架构",
        "架构说明",
        "项目背景",
        "项目概述",
        "业务背景",
        "项目描述",
        "项目简介",
        "需求背景",
        "项目概况",
        "项目介绍",
        "工作职责",
        "工作内容",
        "项目职责",
        "个人职责",
        "项目责任",
        "核心职责与成果",
        "项目职责与成果",
        "项目职责和成果",
        "项目职责及成果",
        "工作职责与成果",
        "工作职责和成果",
        "工作职责及成果",
        "个人职责与成果",
        "职责与成果",
        "职责和成果",
        "职责及成果",
        "主要职责",
        "核心职责",
        "核心工作",
        "责任描述",
        "技术栈",
        "技术列表",
        "技术选型",
        "所用技术",
        "技术清单",
        "技术方案",
        "技术亮点",
        "技术难点",
        "难点及亮点",
        "难点与解决",
        "难点与方案",
        "解决方案",
        "项目亮点",
        "项目难点",
        "负责内容",
        "项目成果",
        "个人成果",
        "工作业绩",
        "项目业绩",
        "主要成果",
        "核心成果",
        "项目角色",
        "担任角色",
    }
)

# A label-only row ending in a colon: short CJK/latin heading, no sentence
# punctuation. Mirrors parser.py::_STANDALONE_SUB_LABEL_RE / the frontend
# STANDALONE_LABEL_RE.
_STANDALONE_LABEL_RE = re.compile(
    r"^\s*(?:[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,11}"
    r"|[A-Za-z][A-Za-z /-]{0,20})"
    r"\s*[：:]\s*$"
)
_SENTENCE_PUNCTUATION_RE = re.compile(r"[，。；！？、,.!?;：]")

# Project descriptive (unnumbered body) sub-labels. Mirror the two frontend
# sets in list-format.ts (PROJECT_INLINE_PLAIN_LABELS /
# PROJECT_DESCRIPTIVE_LABELS).
_PROJECT_INLINE_PLAIN_LABELS: frozenset[str] = frozenset(
    {
        "项目简介",
        "项目描述",
        "项目概况",
        "项目背景",
        "项目概述",
        "业务背景",
        "需求背景",
        "项目介绍",
        "技术架构",
        "系统架构",
        "架构说明",
        "技术栈",
        "技术列表",
        "技术选型",
        "所用技术",
        "技术清单",
    }
)
_PROJECT_DESCRIPTIVE_LABELS: frozenset[str] = frozenset(
    {"项目背景", "技术栈", "项目描述", "系统架构", "架构说明"}
)


# ---------------------------------------------------------------------------
# Description-block partition — Python mirror of buildDescriptionBlocks() in
# components/resume/list-format.ts. Keep the two behaviour-identical.
# ---------------------------------------------------------------------------

# Block shapes:
#   ("label", desc, descriptive)
#   ("list", indented, rows[(desc, numbered, bold, level)])  # level 1: "1.", 2: "1.1"
#   ("body", rows[desc], inline)  # inline=True merges a tech stack into one line
DescriptionBlock = tuple[str, Any, Any]


def _looks_like_sub_label(point: str) -> bool:
    """Whether a legacy ``plain`` row is really a bold sub-module heading."""
    text = str(strip_source_point_marker(point)).strip()
    if not text:
        return False
    ends_with_colon = bool(re.search(r"[：:]\s*$", text))
    core = re.sub(r"[：:]\s*$", "", text).strip()
    if core in _SUB_LABEL_CANDIDATES:
        return True
    if not ends_with_colon:
        return False
    if _SENTENCE_PUNCTUATION_RE.search(core):
        return False
    return bool(_STANDALONE_LABEL_RE.match(text))


def _canonicalize_project_sub_label(desc: str) -> str:
    """Mirror canonicalizeProjectSubLabel(): alias core -> canonical name."""
    text = str(strip_source_point_marker(desc)).strip()
    match = re.match(r"^(.*?)([：:])?\s*$", text)
    core = match.group(1).strip() if match else text
    suffix = match.group(2) if match and match.group(2) else ""
    canonical = PROJECT_SUB_LABEL_CANONICAL.get(core)
    return desc if canonical is None else canonical + suffix


def _is_project_descriptive_label(label_desc: str) -> bool:
    """Mirror isProjectDescriptiveLabel(): bold head with unnumbered body."""
    core = re.sub(
        r"[：:]\s*$",
        "",
        str(strip_source_point_marker(label_desc)).strip(),
    ).strip()
    return core in _PROJECT_DESCRIPTIVE_LABELS


def _is_project_tech_stack_label(label_desc: str) -> bool:
    """Mirror isProjectTechStackLabel(): body rows merge into one inline line."""
    core = re.sub(
        r"[：:]\s*$",
        "",
        str(strip_source_point_marker(label_desc)).strip(),
    ).strip()
    return core == "技术栈"


def _is_known_sub_label(point: str) -> bool:
    """Mirror isKnownSubLabel(): heading is a recognized sub-module name."""
    core = re.sub(
        r"[：:]\s*$",
        "",
        str(strip_source_point_marker(point)).strip(),
    ).strip()
    return core in _SUB_LABEL_CANDIDATES


def _join_inline_body_rows(rows: list[str]) -> str:
    """Mirror joinInlineBodyRows(): 、 for CJK content, ", " for ASCII stacks."""
    separator = "、" if any(re.search(r"[一-鿿]", row) for row in rows) else ", "
    return separator.join(rows)


# Structured tech-stack category row ("后端：Java 8、Spring Boot",
# "数据库：MySQL、Redis"): short category prefix, colon, non-empty content.
# Mirrors TECH_STACK_CATEGORY_RE in components/resume/list-format.ts — keep in
# sync. A region with such rows renders as an ordered list (one number per
# category row); pure-name stacks stay one inline paragraph.
_TECH_STACK_CATEGORY_RE = re.compile(
    r"^[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,10}[：:]\s*\S"
)
# Sentence punctuation distinguishes a category row from a glued achievement
# or background sentence ("项目亮点：时延降到 600ms。").
_CATEGORY_SENTENCE_RE = re.compile(r"[。；！？!?;]")


def _is_tech_stack_category_row(row: str) -> bool:
    """Mirror isTechStackCategoryRow(): category enumeration, not prose."""
    if not _TECH_STACK_CATEGORY_RE.search(row) or _CATEGORY_SENTENCE_RE.search(row):
        return False
    # A glued known sub-module ("技术难点及亮点：实时时延<50ms", no period)
    # stays prose even though it has the category row's short-colon shape.
    core = re.sub(r"[：:].*$", "", row).strip()
    return not _is_known_sub_label(f"{core}：")


def _split_project_plain_prefix(point: str) -> tuple[str, str] | None:
    """Mirror splitProjectPlainPrefix(): split a glued descriptive row.

    Returns ``(label_with_colon, content)`` for rows like "项目简介：面向…",
    None otherwise (heading-only rows, non-descriptive labels, ordinary
    bullets).
    """
    text = str(strip_source_point_marker(point)).strip()
    labels = sorted(_PROJECT_INLINE_PLAIN_LABELS, key=len, reverse=True)
    match = re.match(
        r"(" + "|".join(labels) + r")(\s*[：:])\s*(\S.*)$",
        text,
    )
    if not match:
        return None
    alias, colon_raw, content = match.group(1), match.group(2), match.group(3)
    canonical = PROJECT_SUB_LABEL_CANONICAL.get(alias, alias)
    colon = colon_raw if colon_raw in ("：", ":") else "："
    return f"{canonical}{colon}", content.strip()


def _canonicalize_project_sub_label_prefix(desc: str) -> str:
    """Mirror canonicalizeProjectSubLabelPrefix(): rename a glued prefix."""
    text = str(strip_source_point_marker(desc))
    aliases = sorted(PROJECT_SUB_LABEL_CANONICAL, key=len, reverse=True)
    match = re.match(
        r"^(" + "|".join(re.escape(a) for a in aliases) + r")(\s*[：:])",
        text,
    )
    if not match:
        return text
    alias, colon = match.group(1), match.group(2)
    return text[: match.start(1)] + PROJECT_SUB_LABEL_CANONICAL[alias] + colon + text[
        match.end(2) :
    ]


# Mirror parser.py nested-group-head planning / the frontend
# planNestedGroupHeads(): a bare bold sub-heading grouping the points below
# it ("架构演进与技术债务治理" followed by duty bullets). Keep the three
# implementations in sync.
_NESTED_GROUP_HEAD_MAX_LEN = 16
_NESTED_GROUP_HEAD_PUNCT_RE = re.compile(r"[，。；！？、,.!?;：:]")
# A real grouping structure holds at least this many head groups per module;
# an isolated short row amid normal points is a peer point, never a head.
_NESTED_GROUP_MIN_HEADS = 2


def _is_nested_head_shaped(desc: Any, style: str) -> bool:
    """Shape-only test for a bare bold group heading (no successor check).

    Mirrors parser.py::_is_nested_head_shaped: short, unnumbered, colon-less
    rows without sentence/enumeration punctuation qualify whether the weak
    model stored them as plain, label or bullet.
    """
    if style not in ("plain", "label", "bullet"):
        return False
    if not isinstance(desc, str):
        return False
    text = desc.strip()
    if not text or text.endswith(("：", ":")):
        return False
    # A source-numbered enumeration ("2）机审") is a detail row, not a head.
    if strip_source_point_marker(text) != text:
        return False
    if len(text) > _NESTED_GROUP_HEAD_MAX_LEN:
        return False
    return not _NESTED_GROUP_HEAD_PUNCT_RE.search(text)


def _plan_nested_group_heads(
    items: list[Any],
    styles: list[str],
    canonicalize_labels: bool,
) -> set[int]:
    """Plan nested group-head indices for one project entry's description.

    Render-site mirror of parser.py::_plan_nested_group_heads. Label rows
    delimit module spans: duty/highlight labels open a list span, descriptive
    labels （项目背景/技术栈） open a body span. Inside a list span a
    head-shaped row qualifies only with a detail-shaped successor, a
    non-head-shaped predecessor, and at least ``_NESTED_GROUP_MIN_HEADS``
    qualified heads in the same span.
    """
    if not canonicalize_labels:
        return set()

    def style_at(index: int) -> str:
        return styles[index] if index < len(styles) else "bullet"

    span_heads: list[set[int]] = []
    current: set[int] = set()
    in_list_span = False

    def close_span() -> None:
        nonlocal current
        if current:
            span_heads.append(current)
            current = set()

    for index, desc in enumerate(items):
        style = style_at(index)
        is_label = style == "label" or (
            style == "plain" and _looks_like_sub_label(str(desc))
        )
        if is_label:
            close_span()
            label_desc = _canonicalize_project_sub_label(str(desc))
            in_list_span = not _is_project_descriptive_label(label_desc)
            continue
        if not in_list_span or not _is_nested_head_shaped(desc, style):
            continue
        next_index = index + 1
        if next_index >= len(items):
            continue
        next_style = style_at(next_index)
        if next_style == "label" or (
            next_style == "plain" and _looks_like_sub_label(str(items[next_index]))
        ):
            continue  # next row is a module label: no detail follows
        if _is_nested_head_shaped(items[next_index], next_style):
            continue  # adjacent head-shaped rows: peer points
        prev_index = index - 1
        if prev_index >= 0:
            prev_style = style_at(prev_index)
            prev_is_label = prev_style == "label" or (
                prev_style == "plain"
                and _looks_like_sub_label(str(items[prev_index]))
            )
            if not prev_is_label and _is_nested_head_shaped(
                items[prev_index], prev_style
            ):
                continue  # no head directly after another head
        current.add(index)
    close_span()

    qualified: set[int] = set()
    for heads in span_heads:
        if len(heads) >= _NESTED_GROUP_MIN_HEADS:
            qualified.update(heads)
    return qualified


def build_description_blocks(
    items: Iterable[str],
    styles: Iterable[str] | None,
    *,
    canonicalize_labels: bool = False,
) -> list[DescriptionBlock]:
    """Partition an entry's description rows into label/list/body blocks.

    Mirrors the frontend ``buildDescriptionBlocks``: a label row (or a legacy
    plain heading) starts a fresh block so following bullets restart at 1;
    project descriptive labels （项目背景/技术栈） own unnumbered body blocks;
    loose bullets form one continuous list.
    """
    items_list = list(items)
    styles_list = list(styles) if styles is not None else []
    # Structural head plan (project render sites only): head-shaped bullets
    # inside duty/highlight modules become bold level-1 numbered heads.
    nested_head_indices = _plan_nested_group_heads(
        items_list, styles_list, canonicalize_labels
    )
    blocks: list[DescriptionBlock] = []
    next_block_kind = "list"
    next_list_indented = False
    next_body_inline = False
    # Mirrors the frontend state: only after a recognized module label may an
    # unknown colon heading be treated as a nested numbered point head.
    module_seen = False
    # Detail rows after a nested bold head belong to it until the next head.
    nested_head_open = False

    def open_block() -> DescriptionBlock:
        nonlocal next_list_indented
        last = blocks[-1] if blocks else None
        if last is not None and last[0] in ("list", "body") and last[0] == next_block_kind:
            return last
        if next_block_kind == "body":
            block: DescriptionBlock = ("body", [], next_body_inline)
        else:
            block = ("list", next_list_indented, [])
        blocks.append(block)
        return block

    for index, desc in enumerate(items_list):
        style = styles_list[index] if index < len(styles_list) else "bullet"
        is_label = style == "label" or (style == "plain" and _looks_like_sub_label(desc))
        if is_label:
            label_desc = (
                _canonicalize_project_sub_label(desc) if canonicalize_labels else desc
            )
            descriptive = (
                canonicalize_labels and _is_project_descriptive_label(label_desc)
            )
            # Mirror the frontend: an UNKNOWN bold colon heading inside an
            # already-open duty/highlight module is a nested bold level-1 head
            # ("1. 重大生产环境问题解决：" under 项目亮点）, not a module
            # separator. Every detail row under it renders as a level-2
            # sub-point (1.1, 1.2), including rows stored "plain" — layered
            # content under a sub-module is always an ordered list.
            nested_numbered_head = (
                canonicalize_labels
                and module_seen
                and next_block_kind == "list"
                and not _is_known_sub_label(desc)
            )
            if nested_numbered_head:
                block = open_block()
                nested_head_open = True
                block[2].append((label_desc, True, True, 1))
                continue

            blocks.append(("label", label_desc, descriptive))
            module_seen = True
            nested_head_open = False
            next_block_kind = "body" if descriptive else "list"
            next_body_inline = descriptive and _is_project_tech_stack_label(label_desc)
            next_list_indented = True
            continue

        if canonicalize_labels:
            glued = _split_project_plain_prefix(desc)
            if glued is not None:
                blocks.append(("label", glued[0], True))
                module_seen = True
                nested_head_open = False
                next_block_kind = "body"
                next_body_inline = _is_project_tech_stack_label(glued[0])
                next_list_indented = True
                block = open_block()
                block[1].append(glued[1])
                continue

        # A bare bold sub-heading inside a duty/highlight module (no colon,
        # short unnumbered row followed by detail points — even when stored
        # as a bullet) is a nested level-1 numbered head; its following
        # points render as 1.1/1.2.
        if (
            canonicalize_labels
            and module_seen
            and next_block_kind == "list"
            and not _is_known_sub_label(desc)
            and index in nested_head_indices
        ):
            block = open_block()
            nested_head_open = True
            block[2].append((desc, True, True, 1))
            continue

        block = open_block()
        next_list_indented = False
        if block[0] == "body":
            block[1].append(
                _canonicalize_project_sub_label_prefix(desc)
                if canonicalize_labels
                else desc
            )
            continue
        row_desc = (
            _canonicalize_project_sub_label_prefix(desc)
            if canonicalize_labels
            else desc
        )
        # Every detail under a nested bold head is a numbered level-2
        # sub-point (1.1, 1.2, …), even when stored "plain". Outside nested
        # heads a row is a level-1 numbered-or-unnumbered point.
        if nested_head_open:
            numbered = True
            level = 2
        else:
            numbered = style != "plain"
            level = 1
        block[2].append((row_desc, numbered, False, level))

    # Mirror the frontend tech-stack post-processing:
    # - A structured region with category rows ("后端：…", "数据库：…") renders
    #   as an ordered list with one number per category row; bare-name rows in
    #   a mixed region are numbered too.
    # - Otherwise a region carrying a prose sentence or glued label prefix
    #   (legacy "技术难点及亮点：…" row) stays stacked instead of joining entries
    #   with a separator.
    inline_disqualify = re.compile(
        r"[。；！？!?;]|^[一-鿿A-Za-z][一-鿿A-Za-z0-9/]{0,9}[：:]"
    )
    for index, block in enumerate(blocks):
        if block[0] != "body" or not block[2] or not block[1]:
            continue
        if any(_is_tech_stack_category_row(str(row)) for row in block[1]):
            blocks[index] = (
                "list",
                True,
                [(str(row), True, False, 1) for row in block[1]],
            )
        elif any(inline_disqualify.search(str(row)) for row in block[1]):
            blocks[index] = ("body", block[1], False)

    return blocks


# ---------------------------------------------------------------------------
# Low-level Word helpers (same approach as services/diagnosis_docx.py)
# ---------------------------------------------------------------------------


def _set_east_asian_font(document: Document) -> None:
    """Make Chinese characters render in a CJK-aware font in Word."""
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    pf = style.paragraph_format
    pf.space_after = Pt(2)
    pf.line_spacing = 1.12


def _style_run(
    run: object, *, east_asian: str = "宋体", size: float | None = None
) -> None:
    """Assign an East Asian font to a run.

    python-docx only creates the rPr/rFonts node after ``font.name`` is set, so
    touching ``rFonts`` directly on a fresh run raises AttributeError.
    """
    run.font.name = "Calibri"  # type: ignore[attr-defined]
    run._element.rPr.rFonts.set(qn("w:eastAsia"), east_asian)
    if size is not None:
        run.font.size = Pt(size)  # type: ignore[attr-defined]


def _bottom_border(paragraph: Paragraph, *, size: str = "6") -> None:
    """Attach a single black bottom rule to a paragraph."""
    p_pr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), size)
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), "000000")
    pbdr.append(bottom)
    p_pr.append(pbdr)


def _remove_table_borders(table: Table) -> None:
    """Make a table render without any grid lines."""
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "nil")
        borders.append(element)
    tbl_pr.append(borders)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)


def _compact_cell(cell: object, *, size: float = 10.5) -> Paragraph:
    """Return the cell's single paragraph with tight spacing."""
    paragraph = cell.paragraphs[0]  # type: ignore[attr-defined]
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(1)
    pf.line_spacing = 1.1
    for run in paragraph.runs:
        _style_run(run, size=size)
    return paragraph


def _set_cell_text(
    cell: object,
    text: str,
    *,
    bold: bool = False,
    meta: bool = False,
    size: float = 10.5,
) -> None:
    """Replace a cell's text with one styled run (empty string -> empty cell)."""
    paragraph = _compact_cell(cell, size=size)
    if paragraph.runs:
        for run in paragraph.runs:
            run.text = ""
    if text:
        run = paragraph.add_run(text)
        run.bold = bold
        _style_run(run, size=size)
        if meta:
            run.font.color.rgb = _META_COLOR


def _grid_row(
    document: Document,
    cells: tuple[str, ...],
    *,
    bold: tuple[bool, ...],
    meta: tuple[bool, ...],
    widths_cm: tuple[float, ...],
) -> Table:
    """Add a borderless 1xN grid row (work/project/education headers)."""
    table = document.add_table(rows=1, cols=len(cells))
    table.autofit = False
    _remove_table_borders(table)
    row = table.rows[0]
    for index, (cell, text, is_bold, is_meta, width) in enumerate(
        zip(row.cells, cells, bold, meta, widths_cm, strict=True)
    ):
        cell.width = Cm(width)
        _set_cell_text(
            cell,
            text,
            bold=is_bold,
            meta=is_meta,
        )
    return table


def _four_column_row(
    document: Document,
    cells: tuple[str, str, str, str],
    *,
    bold: tuple[bool, bool, bool, bool] = (False, False, False, False),
    meta: tuple[bool, bool, bool, bool] = (False, False, False, False),
    # The date track (3.3cm) is deliberately wider than its glyphs so the
    # company column starts a little further right; the company track narrows
    # by the same 0.5cm (rows stay 17cm total).
    widths_cm: tuple[float, float, float, float] = (3.3, 4.5, 3.8, 5.4),
) -> Table:
    """Add a borderless 1x4 grid row (work/project/education headers)."""
    return _grid_row(
        document, cells, bold=bold, meta=meta, widths_cm=widths_cm
    )


def _three_column_row(
    document: Document,
    cells: tuple[str, str, str],
    *,
    bold: tuple[bool, bool, bool] = (False, False, False),
    meta: tuple[bool, bool, bool] = (False, False, False),
    # Company keeps the same track as the four-column row (so companies line
    # up across rows, 3.3/4.5cm); the role moves into the freed department band
    # and spans it plus the old role track (3.8 + 5.4 = 9.2cm), right-aligned
    # so the row stays 两端对齐 (date flush left, role flush right).
    widths_cm: tuple[float, float, float] = (3.3, 4.5, 9.2),
) -> Table:
    """Add a borderless 1x3 grid row (work header without a department)."""
    table = _grid_row(
        document, cells, bold=bold, meta=meta, widths_cm=widths_cm
    )
    for paragraph in table.rows[0].cells[2].paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    return table


def _section_heading(document: Document, text: str) -> None:
    """Bold 12pt 黑体 heading with a thin bottom rule (Swiss style)."""
    paragraph = document.add_paragraph()
    pf = paragraph.paragraph_format
    pf.space_before = Pt(8)
    pf.space_after = Pt(3)
    pf.keep_with_next = True
    run = paragraph.add_run(text)
    run.bold = True
    _style_run(run, east_asian="黑体", size=12)
    _bottom_border(paragraph)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _format_date_range(value: Any) -> str:
    """Display-side mirror of frontend formatDateRange() (lib/utils.ts).

    Canonical periods (``yyyy.MM~yyyy.MM`` / ``yyyy.MM~至今``) are produced by
    the heal chain; this re-applies the canonicalizer so even a value that
    slipped through (colloquial text stays byte-identical) never regains a
    hyphen connector or English month names.
    """
    if not isinstance(value, str):
        return ""
    return canonicalize_date_period(value.strip())


def _split_points(text: str) -> list[str]:
    """Mirror splitPoints(): trimmed non-empty source lines."""
    return [line.strip() for line in re.split(r"\r?\n", text) if line.strip()]


def _add_ordered_points(
    document: Document, points: list[str], *, base_size: float = 10.5
) -> None:
    """Hanging-indent ordered list; a single point renders as a paragraph."""
    if not points:
        return
    if len(points) == 1:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(str(strip_source_point_marker(points[0])))
        _style_run(run, size=base_size)
        return
    for index, point in enumerate(points, start=1):
        paragraph = document.add_paragraph()
        pf = paragraph.paragraph_format
        pf.left_indent = Cm(0.6)
        pf.first_line_indent = Cm(-0.6)
        pf.space_after = Pt(1)
        number_run = paragraph.add_run(f"{index}.")
        _style_run(number_run, size=base_size)
        text_run = paragraph.add_run(
            f" {strip_source_point_marker(point)}"
        )
        _style_run(text_run, size=base_size)


def _add_description_blocks(
    document: Document,
    items: list[str],
    styles: list[Any] | None,
    *,
    canonicalize_labels: bool = False,
) -> None:
    """Render work/project/custom-item descriptions (screen semantics)."""
    blocks = build_description_blocks(
        items,
        styles,
        canonicalize_labels=canonicalize_labels,
    )
    for block in blocks:
        kind = block[0]
        if kind == "label":
            paragraph = document.add_paragraph()
            pf = paragraph.paragraph_format
            pf.space_before = Pt(2)
            pf.space_after = Pt(1)
            pf.keep_with_next = True
            run = paragraph.add_run(str(strip_source_point_marker(block[1])))
            run.bold = True
            _style_run(run, size=10.5)
            continue

        if kind == "body":
            rows = [str(strip_source_point_marker(row)) for row in block[1]]
            if block[2]:
                # Tech-stack enumeration: all entries in one wrapping paragraph.
                paragraph = document.add_paragraph()
                pf = paragraph.paragraph_format
                pf.space_after = Pt(1)
                run = paragraph.add_run(_join_inline_body_rows(rows))
                _style_run(run, size=10.5)
            else:
                for row_text in rows:
                    paragraph = document.add_paragraph()
                    pf = paragraph.paragraph_format
                    pf.space_after = Pt(1)
                    run = paragraph.add_run(row_text)
                    _style_run(run, size=10.5)
            continue

        # list block — numbering is local to each block, so every sub-module
        # restarts at 1, plain rows outside nested heads skip the counter but
        # keep the indent. Nested bold heads are level 1 (1. 2.); every detail
        # below them is level 2 and renders indented with composite markers
        # (1.1, 1.2, …), restarting at every head.
        number_l1 = 0
        number_l2 = 0
        for desc, numbered, bold, level in block[2]:
            marker = ""
            paragraph = document.add_paragraph()
            pf = paragraph.paragraph_format
            pf.space_after = Pt(1)
            if level == 2:
                pf.left_indent = Cm(1.2)
                if numbered:
                    number_l2 += 1
                    pf.first_line_indent = Cm(-0.6)
                    marker = f"{number_l1}.{number_l2}"
            else:
                pf.left_indent = Cm(0.6)
                if bold:
                    number_l2 = 0
                if numbered:
                    number_l1 += 1
                    pf.first_line_indent = Cm(-0.6)
                    marker = f"{number_l1}."
            if marker:
                number_run = paragraph.add_run(marker)
                number_run.bold = bold and level == 1
                _style_run(number_run, size=10.5)
            text_run = paragraph.add_run(
                f" {strip_source_point_marker(desc)}" if marker
                else str(strip_source_point_marker(desc))
            )
            text_run.bold = bold
            _style_run(text_run, size=10.5)


def _add_text_block(document: Document, text: str) -> None:
    """Render summary / custom text: per-line numbered list, prose stays prose."""
    points = _split_points(text)
    _add_ordered_points(document, points)


def _add_string_list(document: Document, strings: list[str]) -> None:
    """Render a custom stringList (OrderedStringList semantics)."""
    points = [item.strip() for item in strings if isinstance(item, str) and item.strip()]
    _add_ordered_points(document, points)


def _render_header(document: Document, data: dict[str, Any], chrome: dict[str, str]) -> None:
    info = data.get("personalInfo")
    info = info if isinstance(info, dict) else {}
    additional = data.get("additional")
    additional = additional if isinstance(additional, dict) else {}
    education = data.get("education")
    education = education if isinstance(education, list) else []

    name = _clean(info.get("name"))
    if name:
        paragraph = document.add_paragraph()
        pf = paragraph.paragraph_format
        pf.space_after = Pt(2)
        run = paragraph.add_run(name)
        run.bold = True
        _style_run(run, east_asian="黑体", size=20)

    # Labeled facts in the on-screen order:
    # 性别 / 年龄 / 学历 / 工作年限 / 求职意向 / 意向城市 / 电话 / 邮箱 / 外语水平.
    languages = [
        item.strip()
        for item in additional.get("languages", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(additional.get("languages"), list) else []
    degree_fallback = next(
        (
            edu.get("degree", "").strip()
            for edu in education
            if isinstance(edu, dict)
            and isinstance(edu.get("degree"), str)
            and edu.get("degree", "").strip()
        ),
        "",
    )
    education_level = _clean(info.get("educationLevel")) or degree_fallback

    facts: list[tuple[str, str]] = []

    def push(label_key: str, value: Any) -> None:
        text = value.strip() if isinstance(value, str) else ""
        if text:
            facts.append((chrome[label_key], text))

    push("gender", info.get("gender"))
    push("age", info.get("age"))
    push("education", education_level)
    push("workYears", info.get("workYears"))
    push("jobIntention", info.get("title"))
    push("desiredCity", info.get("location"))
    push("phone", info.get("phone"))
    push("email", info.get("email"))
    if languages:
        facts.append((chrome["foreignLanguage"], "、".join(languages)))

    if facts:
        separator = "：" if chrome is _CHROME["zh"] else ": "
        fact_separator = "　　" if chrome is _CHROME["zh"] else "    "
        paragraph = document.add_paragraph()
        pf = paragraph.paragraph_format
        pf.space_after = Pt(2)
        for index, (label, value) in enumerate(facts):
            if index:
                gap_run = paragraph.add_run(fact_separator)
                _style_run(gap_run, size=10.5)
            label_run = paragraph.add_run(f"{label}{separator}")
            _style_run(label_run, size=10.5)
            value_run = paragraph.add_run(value)
            _style_run(value_run, size=10.5)

    # Website / social links stay on their own row, display text only
    # (strip protocol / www / trailing slash, mirroring the on-screen pills).
    link_texts = [
        _display_link(info.get("website")),
        _display_link(info.get("linkedin")),
        _display_link(info.get("github")),
    ]
    link_texts = [text for text in link_texts if text]
    if link_texts:
        paragraph = document.add_paragraph()
        pf = paragraph.paragraph_format
        pf.space_after = Pt(2)
        for index, text in enumerate(link_texts):
            if index:
                gap_run = paragraph.add_run("    ")
                _style_run(gap_run, size=9.5)
            run = paragraph.add_run(text)
            _style_run(run, size=9.5)
            run.font.color.rgb = _META_COLOR


def _display_link(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    return re.sub(r"/$", "", text)


def _render_work(document: Document, data: dict[str, Any]) -> None:
    works = data.get("workExperience")
    if not isinstance(works, list) or not works:
        return
    for work in works:
        if not isinstance(work, dict):
            continue
        date = _format_date_range(work.get("years"))
        company = _clean(work.get("company"))
        department = _clean(work.get("department"))
        location = _clean(work.get("location"))
        role = _clean(work.get("title"))
        if any((date, company, department, location, role)):
            company_text = company
            location_text = f" · {location}" if location else ""
            if department:
                table = _four_column_row(
                    document,
                    (date, company_text, department, role),
                    # Role is deliberately regular weight; so is the company.
                    bold=(False, False, False, False),
                    meta=(True, False, False, False),
                )
            else:
                # No department: the three fields that exist (time, company,
                # role) fill the row as three columns instead of leaving an
                # empty department track.
                table = _three_column_row(
                    document,
                    (date, company_text, role),
                    bold=(False, False, False),
                    meta=(True, False, False),
                )
            if location_text:
                company_cell = table.rows[0].cells[1]
                location_run = company_cell.paragraphs[0].add_run(location_text)
                _style_run(location_run, size=9)
                location_run.font.color.rgb = _META_COLOR
        description = work.get("description")
        if isinstance(description, list) and description:
            _add_description_blocks(
                document,
                [row for row in description if isinstance(row, str)],
                work.get("descriptionStyles")
                if isinstance(work.get("descriptionStyles"), list)
                else None,
            )


def _render_projects(document: Document, data: dict[str, Any]) -> None:
    projects = data.get("personalProjects")
    if not isinstance(projects, list) or not projects:
        return
    for project in projects:
        if not isinstance(project, dict):
            continue
        name = _clean(project.get("name"))
        date = _format_date_range(project.get("years"))
        scale = _clean(project.get("scale"))
        role = _clean(project.get("role"))
        github = _display_link(project.get("github"))
        website = _display_link(project.get("website"))
        if any((name, date, scale, role, github, website)):
            name_parts = name
            if not any((date, scale, role)):
                # No metadata: name gets a full-width row instead of 4 tracks.
                paragraph = document.add_paragraph()
                pf = paragraph.paragraph_format
                pf.space_after = Pt(1)
                if name_parts:
                    name_run = paragraph.add_run(name_parts)
                    name_run.bold = True
                    _style_run(name_run, size=10.5)
                for link_text in (github, website):
                    if link_text:
                        link_run = paragraph.add_run(f"  {link_text}")
                        _style_run(link_run, size=9)
                        link_run.font.color.rgb = _META_COLOR
            else:
                table = _four_column_row(
                    document,
                    (name_parts, date, scale, role),
                    bold=(True, False, False, True),
                    meta=(False, True, True, False),
                    widths_cm=(5.6, 2.8, 3.2, 5.4),
                )
                name_cell = table.rows[0].cells[0]
                for link_text in (github, website):
                    if link_text:
                        link_run = name_cell.paragraphs[0].add_run(
                            f"  {link_text}"
                        )
                        _style_run(link_run, size=9)
                        link_run.font.color.rgb = _META_COLOR
        description = project.get("description")
        if isinstance(description, list) and description:
            _add_description_blocks(
                document,
                [row for row in description if isinstance(row, str)],
                project.get("descriptionStyles")
                if isinstance(project.get("descriptionStyles"), list)
                else None,
                canonicalize_labels=True,
            )


def _render_education(document: Document, data: dict[str, Any]) -> None:
    education = data.get("education")
    if not isinstance(education, list) or not education:
        return
    for edu in education:
        if not isinstance(edu, dict):
            continue
        date = _format_date_range(edu.get("years"))
        institution = _clean(edu.get("institution"))
        major = _clean(edu.get("description"))
        degree = _clean(edu.get("degree"))
        if not any((date, institution, major, degree)):
            continue
        _four_column_row(
            document,
            (date, institution, major, degree),
            # Institution bold, major/degree regular.
            bold=(False, True, False, False),
            meta=(True, False, False, False),
            widths_cm=(3.3, 4.5, 4.0, 5.2),
        )


def _additional_entries(
    additional: Any, field: str
) -> list[str]:
    """Non-empty string entries of one ``additional`` sub-list."""
    if not isinstance(additional, dict):
        return []
    raw = additional.get(field)
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _render_additional_skills(
    document: Document, data: dict[str, Any], chrome: dict[str, str]
) -> None:
    """Early ``additional`` slot: technical skills only.

    Certifications/awards are projected to the back of the resume by
    :func:`_render_late_modules`; languages only appear in the header fact
    grid (外语水平 / Foreign Languages).
    """
    skills = _additional_entries(data.get("additional"), "technicalSkills")
    if not skills:
        return
    _section_heading(document, chrome["additional"])
    _add_ordered_points(
        document,
        [str(strip_source_point_marker(skill)) for skill in skills],
    )


def _render_late_modules(
    document: Document, data: dict[str, Any], chrome: dict[str, str]
) -> None:
    """Render 培训与证书 / 荣誉奖项 as independent sections at the back.

    Mirrors the frontend ``getRenderSections`` projection: the two modules
    stay independent but are emitted after the custom-section cluster.
    Single entries stay unnumbered (``_add_ordered_points`` behaviour).
    """
    additional = data.get("additional")
    for heading_key, field in (
        ("certifications", "certificationsTraining"),
        ("awards", "awards"),
    ):
        entries = _additional_entries(additional, field)
        if entries:
            _section_heading(document, chrome[heading_key])
            _add_ordered_points(document, entries)


def _late_modules_anchor(
    rows: list[dict[str, Any]], degree_class: str
) -> int:
    """Row index before which the cert/award modules are emitted.

    Anchor resolution, first match wins — the DOCX mirror of the TS
    ``getRenderSections`` anchor search:

    1. on the ``other`` degree branch, the late education row (it sits
       structurally after the custom cluster in that branch);
    2. the self-evaluation row (``__selfeval__``);
    3. end of document.
    """
    if degree_class == "other":
        for index, row in enumerate(rows):
            if row.get("key") == "education":
                return index
    for index, row in enumerate(rows):
        if section_symbol(row) == SELFEVAL_SYMBOL:
            return index
    return len(rows)


def _custom_title(
    display_name: str, chrome: dict[str, str]
) -> str:
    """Localize the self-introduction alias block; other titles are verbatim."""
    folded = re.sub(r"\s+", " ", display_name.strip()).lower()
    if any(
        folded == re.sub(r"\s+", " ", alias).lower()
        for alias in SELF_INTRODUCTION_TITLE_ALIASES
    ):
        return chrome["selfIntroduction"]
    return display_name


def _render_custom(
    document: Document, row: dict[str, Any], data: dict[str, Any], chrome: dict[str, str]
) -> None:
    key = row.get("key")
    custom_sections = data.get("customSections")
    if not isinstance(key, str) or not isinstance(custom_sections, dict):
        return
    section = custom_sections.get(key)
    if not isinstance(section, dict):
        return
    section_type = section.get("sectionType") or row.get("sectionType")
    display_name = row.get("displayName")
    title = _custom_title(display_name, chrome) if isinstance(display_name, str) else key

    if section_type == "text":
        text = section.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        _section_heading(document, title)
        _add_text_block(document, text)
        return

    if section_type == "stringList":
        strings = section.get("strings")
        if not isinstance(strings, list) or not any(
            isinstance(item, str) and item.strip() for item in strings
        ):
            return
        _section_heading(document, title)
        _add_string_list(document, [s for s in strings if isinstance(s, str)])
        return

    if section_type == "itemList":
        items = section.get("items")
        if not isinstance(items, list) or not items:
            return
        _section_heading(document, title)
        for item in items:
            if not isinstance(item, dict):
                continue
            item_title = _clean(item.get("title"))
            years = _format_date_range(item.get("years"))
            if item_title or years:
                paragraph = document.add_paragraph()
                pf = paragraph.paragraph_format
                pf.space_before = Pt(3)
                pf.space_after = Pt(1)
                pf.keep_with_next = True
                pf.tab_stops.add_tab_stop(
                    Cm(_CONTENT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT
                )
                if item_title:
                    title_run = paragraph.add_run(item_title)
                    title_run.bold = True
                    _style_run(title_run, size=10.5)
                if years:
                    years_run = paragraph.add_run(f"\t{years}")
                    _style_run(years_run, size=9.5)
                    years_run.font.color.rgb = _META_COLOR
            subtitle = _clean(item.get("subtitle"))
            location = _clean(item.get("location"))
            if subtitle or location:
                paragraph = document.add_paragraph()
                pf = paragraph.paragraph_format
                pf.space_after = Pt(1)
                pf.tab_stops.add_tab_stop(
                    Cm(_CONTENT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT
                )
                if subtitle:
                    subtitle_run = paragraph.add_run(subtitle)
                    subtitle_run.bold = True
                    _style_run(subtitle_run, size=10.5)
                if location:
                    location_run = paragraph.add_run(f"\t{location}")
                    _style_run(location_run, size=9.5)
                    location_run.font.color.rgb = _META_COLOR
            description = item.get("description")
            if isinstance(description, list) and description:
                _add_description_blocks(
                    document,
                    [row_text for row_text in description if isinstance(row_text, str)],
                    item.get("descriptionStyles")
                    if isinstance(item.get("descriptionStyles"), list)
                    else None,
                )


_HAN_CHAR_RE = re.compile(r"[一-鿿]")
_DETECTION_CHAR_BUDGET = 4000


def _detect_content_language(value: Any, *, budget: int = _DETECTION_CHAR_BUDGET) -> str:
    """Return ``"zh"`` when the resume content contains Han characters.

    Static chrome follows the CONTENT language (not the UI language): the
    first Han character found while scanning string leaves wins, so a mostly
    English resume with a Chinese name still gets Chinese chrome. The scan is
    char-bounded to stay cheap on huge payloads.
    """
    seen = 0

    def visit(node: Any) -> bool:
        nonlocal seen
        if isinstance(node, str):
            if _HAN_CHAR_RE.search(node):
                return True
            seen += len(node)
            return seen > budget
        if isinstance(node, dict):
            for item in node.values():
                if visit(item):
                    return True
        elif isinstance(node, list):
            for item in node:
                if visit(item):
                    return True
        return False

    return "zh" if visit(value) else "en"


def build_resume_docx(
    data: dict[str, Any], *, language: str | None = None
) -> bytes:
    """Build the canonical Word resume from structured ResumeData.

    ``language`` selects static chrome when given (``zh`` prefix -> Chinese,
    otherwise English); with ``None`` the chrome follows the resume CONTENT
    language (Han characters -> Chinese). The input dict is never mutated.
    """
    if not isinstance(data, dict):
        raise ValueError("Resume data must be a dict")

    if language:
        chrome_key = "zh" if str(language).lower().startswith("zh") else "en"
    else:
        chrome_key = _detect_content_language(data)
    chrome = _CHROME[chrome_key]

    # Canonicalize on a private copy: strip Markdown modifiers, section
    # order, title governance and omitted-section healing for free, plus the
    # legacy department repair. Marker removal can collapse duplicated list
    # rows ("英语四级" / "英语四级**"); drop the duplicates. Input dict is
    # never mutated.
    payload = normalize_cjk_compat_deep(copy.deepcopy(data))
    payload = normalize_date_periods(payload)
    payload = repair_project_label_regions(payload)
    payload = extract_education_credentials(payload)
    payload = extract_misfiled_credentials(payload)
    # Same container-shape reconciliation as the read-path heal chain so a
    # stringList section whose entries were stored as items renders its
    # content instead of a title-only block.
    payload = reconcile_custom_section_shapes(payload)
    payload = canonicalize_tech_terms(payload)
    payload = normalize_text_hygiene(payload)
    payload = dedupe_resume_lists(strip_markdown_emphasis_deep(payload))
    promote_work_departments(payload)
    rows = [
        row
        for row in canonicalize_section_meta(payload)
        if isinstance(row, dict) and row.get("isVisible", True)
    ]

    document = Document()
    _set_east_asian_font(document)
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    _render_header(document, payload, chrome)

    # Certifications/awards are render-only late modules (never meta rows):
    # they appear only while the additional section is visible — the same
    # gate the frontend getRenderSections projection uses — and anchor after
    # the custom-section cluster.
    additional_payload = payload.get("additional")
    has_late_modules = any(
        _additional_entries(additional_payload, field)
        for field in ("certificationsTraining", "awards")
    )
    additional_visible = any(row.get("key") == "additional" for row in rows)
    render_late_modules = has_late_modules and additional_visible
    degree_class = classify_highest_degree(payload.get("education"))
    late_anchor = (
        _late_modules_anchor(rows, degree_class) if render_late_modules else -1
    )

    for index, row in enumerate(rows):
        if index == late_anchor:
            _render_late_modules(document, payload, chrome)
        key = row.get("key")
        if key == "personalInfo":
            continue
        if key == "summary":
            summary = payload.get("summary")
            if isinstance(summary, str) and summary.strip():
                _section_heading(document, chrome["summary"])
                _add_text_block(document, summary)
            continue
        if key == "workExperience":
            works = payload.get("workExperience")
            if isinstance(works, list) and any(isinstance(w, dict) for w in works):
                _section_heading(document, chrome["workExperience"])
                _render_work(document, payload)
            continue
        if key == "education":
            education = payload.get("education")
            if isinstance(education, list) and any(isinstance(e, dict) for e in education):
                _section_heading(document, chrome["education_section"])
                _render_education(document, payload)
            continue
        if key == "personalProjects":
            projects = payload.get("personalProjects")
            if isinstance(projects, list) and any(isinstance(p, dict) for p in projects):
                _section_heading(document, chrome["personalProjects"])
                _render_projects(document, payload)
            continue
        if key == "additional":
            _render_additional_skills(document, payload, chrome)
            continue
        if key in DEFAULT_SECTION_KEYS:
            continue
        _render_custom(document, row, payload, chrome)

    if late_anchor == len(rows):
        _render_late_modules(document, payload, chrome)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def resume_docx_headers(resume_id: str, filename_stem: str) -> dict[str, str]:
    """Content-Disposition with RFC 5987 UTF-8 filename plus ASCII fallback."""
    ascii_fallback = f"resume-{resume_id[:8]}.docx"
    quoted = quote(f"{filename_stem}.docx")
    return {
        "Content-Disposition": (
            f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quoted}"
        )
    }
