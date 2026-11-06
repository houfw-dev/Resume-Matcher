"""Sub-module (label-region) spans inside work/project descriptions.

A fine-tune target can name one sub-module of one entry, e.g.
``project_2:highlights`` means only the rows owned by the ``项目亮点：`` label
inside project entry 2 may be rewritten. This module turns an entry's
``description`` / ``descriptionStyles`` arrays into label-region spans.

The boundary rules MIRROR the render-time partition in the frontend
(``apps/frontend/lib/utils/description-regions.ts`` and
``components/resume/list-format.ts``); the two sides share a parity test
fixture matrix. Keep them in sync.

Projects canonicalize label aliases (``项目成果`` → ``项目亮点`` etc.) via the
parser map; work labels are recognized but NEVER renamed — the parser leaves
work labels verbatim and tests lock that behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from app.services.parser import (
    PROJECT_SUB_LABEL_CANONICAL,
    _STANDALONE_SUB_LABEL_RE,
    _SUB_LABEL_CANDIDATES,
    strip_source_point_marker,
)

EntryKind = Literal["work", "project"]

# Region ids shared with the fine-tune token grammar and the frontend.
REGION_TECH_STACK = "techStack"
REGION_BACKGROUND = "background"
REGION_DUTIES = "duties"
REGION_HIGHLIGHTS = "highlights"
REGION_ACHIEVEMENTS = "achievements"
REGION_ROLE = "role"

REGION_IDS: tuple[str, ...] = (
    REGION_TECH_STACK,
    REGION_BACKGROUND,
    REGION_DUTIES,
    REGION_HIGHLIGHTS,
    REGION_ACHIEVEMENTS,
    REGION_ROLE,
)

# Project canonical label cores -> region ids. Aliases first pass through
# PROJECT_SUB_LABEL_CANONICAL, so only the four target names appear here.
_PROJECT_REGION_IDS: dict[str, str] = {
    "技术栈": REGION_TECH_STACK,
    "项目背景": REGION_BACKGROUND,
    "项目职责": REGION_DUTIES,
    "项目亮点": REGION_HIGHLIGHTS,
}

# Work labels are free-form and never renamed; curated cores map to a region
# id verbatim. Tech aliases mirror the project alias family.
_WORK_REGION_IDS: dict[str, str] = {
    "技术栈": REGION_TECH_STACK,
    "技术列表": REGION_TECH_STACK,
    "技术选型": REGION_TECH_STACK,
    "所用技术": REGION_TECH_STACK,
    "技术清单": REGION_TECH_STACK,
    "技术架构": REGION_TECH_STACK,
    "系统架构": REGION_TECH_STACK,
    "工作职责": REGION_DUTIES,
    "工作内容": REGION_DUTIES,
    "主要职责": REGION_DUTIES,
    "核心职责": REGION_DUTIES,
    "责任描述": REGION_DUTIES,
    "负责内容": REGION_DUTIES,
    "核心工作": REGION_DUTIES,
    # Combined duty + result headings ("项目职责与成果：") are duty regions;
    # project sites resolve them through PROJECT_SUB_LABEL_CANONICAL instead.
    "项目职责与成果": REGION_DUTIES,
    "项目职责和成果": REGION_DUTIES,
    "项目职责及成果": REGION_DUTIES,
    "工作职责与成果": REGION_DUTIES,
    "工作职责和成果": REGION_DUTIES,
    "工作职责及成果": REGION_DUTIES,
    "职责与成果": REGION_DUTIES,
    "职责和成果": REGION_DUTIES,
    "职责及成果": REGION_DUTIES,
    "工作业绩": REGION_ACHIEVEMENTS,
    "项目业绩": REGION_ACHIEVEMENTS,
    "主要成果": REGION_ACHIEVEMENTS,
    "核心成果": REGION_ACHIEVEMENTS,
    "工作成果": REGION_ACHIEVEMENTS,
    "项目角色": REGION_ROLE,
    "担任角色": REGION_ROLE,
}

_KNOWN_LABEL_CORES: frozenset[str] = frozenset(_SUB_LABEL_CANDIDATES)
_VALID_STYLES: frozenset[str] = frozenset({"bullet", "plain", "label"})
# Sentence punctuation proving a colon row is body text, not a heading.
# Mirrors SENTENCE_PUNCTUATION_RE in the frontend list-format.ts.
_SENTENCE_PUNCTUATION_RE = re.compile(r"[，。；！？、,.!?;：]")


@dataclass(frozen=True)
class LabelRegion:
    """One selectable sub-module within an entry."""

    region_id: str
    """Row index of the label heading itself (never overlaid by fine-tune)."""
    label_index: int
    """Content row indices owned by the label, until the next separator."""
    content_indices: tuple[int, ...]
    """Stored label text, e.g. ``项目亮点：``."""
    label_text: str


def _aligned_style(styles: object, index: int) -> str:
    if isinstance(styles, list) and index < len(styles):
        style = styles[index]
        if isinstance(style, str) and style in _VALID_STYLES:
            return style
    return "bullet"


def _heading_core(row: object, style: str) -> str | None:
    """Canonical-neutral heading test: return the row's label core or None.

    Mirrors ``looksLikeSubLabel`` in the frontend: a curated label name is a
    heading with or without its trailing colon; any other heading must be a
    short standalone colon-terminated title. Only ``label``/``plain`` rows can
    be headings — a bullet-styled label-shaped row renders as a numbered point.
    """
    if style not in ("label", "plain") or not isinstance(row, str):
        return None
    text = strip_source_point_marker(row).strip()
    if not text:
        return None
    ends_with_colon = text.endswith(("：", ":"))
    core = text[:-1].strip() if ends_with_colon else text
    if core in _KNOWN_LABEL_CORES:
        return core
    if not ends_with_colon:
        return None
    if _SENTENCE_PUNCTUATION_RE.search(core):
        return None
    if _STANDALONE_SUB_LABEL_RE.match(text) is None:
        return None
    return core


def entry_label_regions(
    description: object,
    description_styles: object,
    *,
    kind: EntryKind,
) -> list[LabelRegion]:
    """Partition an entry's rows into selectable label regions.

    Rules (mirror of ``buildDescriptionBlocks`` render semantics):

    - Rows before the first heading belong to no region.
    - A mapped heading opens a region; following content rows belong to it
      until the next module-separating heading. The label row itself is
      excluded (fine-tune never rewrites label rows).
    - Project sites: an unknown colon heading INSIDE an open bullet region
      (``重大问题解决：`` under 项目职责） is a nested numbered point head, not a
      separator — it and its detail rows stay in the open region. Unknown
      headings elsewhere (and every unknown heading in work entries, which
      have no nested-head rendering) close the current region.
    - The descriptive-only project names （项目描述/系统架构/架构说明） are
      headings but have no region id; they act as separators.
    """
    if not isinstance(description, list):
        return []

    regions: list[LabelRegion] = []
    open_region: LabelRegion | None = None
    # Project render state: nested numbered heads exist only inside a
    # bullet (duty/highlight) region. Descriptive regions own body blocks,
    # where every new heading separates.
    in_bullet_region = False

    def _region_id_for(core: str) -> str | None:
        if kind == "project":
            canonical = PROJECT_SUB_LABEL_CANONICAL.get(core, core)
            return _PROJECT_REGION_IDS.get(canonical)
        return _WORK_REGION_IDS.get(core)

    for index, row in enumerate(description):
        if not isinstance(row, str):
            # Schema guarantees strings; a malformed row is treated as
            # regionless content so it can never enter an overlay span.
            continue
        style = _aligned_style(description_styles, index)
        core = _heading_core(row, style)
        if core is not None:
            region_id = _region_id_for(core)
            if region_id is not None:
                open_region = LabelRegion(
                    region_id=region_id,
                    label_index=index,
                    content_indices=(),
                    label_text=row.strip(),
                )
                regions.append(open_region)
                in_bullet_region = kind == "project" and region_id in (
                    REGION_DUTIES,
                    REGION_HIGHLIGHTS,
                )
                continue
            known = core in _KNOWN_LABEL_CORES
            if kind == "project" and in_bullet_region and not known:
                # Nested numbered point head inside duties/highlights:
                # part of the open region, as are its detail rows.
                pass
            else:
                # Unmapped heading: close the region; its own rows are frozen.
                open_region = None
                in_bullet_region = False
                continue
        if open_region is not None:
            open_region = LabelRegion(
                region_id=open_region.region_id,
                label_index=open_region.label_index,
                content_indices=(*open_region.content_indices, index),
                label_text=open_region.label_text,
            )
            regions[-1] = open_region

    return regions


def merged_entry_regions(
    description: object,
    description_styles: object,
    *,
    kind: EntryKind,
) -> dict[str, LabelRegion]:
    """Merge same-id regions (two duty blocks) into one span union.

    First label occurrence provides ``label_index``/``label_text``.
    """
    merged: dict[str, LabelRegion] = {}
    for region in entry_label_regions(
        description, description_styles, kind=kind
    ):
        existing = merged.get(region.region_id)
        if existing is None:
            merged[region.region_id] = region
            continue
        indices = tuple(
            sorted(set(existing.content_indices) | set(region.content_indices))
        )
        merged[region.region_id] = LabelRegion(
            region_id=region.region_id,
            label_index=existing.label_index,
            content_indices=indices,
            label_text=existing.label_text,
        )
    return merged
