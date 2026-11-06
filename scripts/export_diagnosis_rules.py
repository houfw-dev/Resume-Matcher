#!/usr/bin/env python3
"""Export the diagnosis rubric from the source xlsx into the shipped JSON.

The xlsx (rules/简历诊断规范_V4_优化版.xlsx) is the human-maintained source of
truth; the JSON it produces (apps/backend/app/services/diagnosis_rules.json) is
the only artifact the backend reads at runtime — openpyxl is deliberately NOT a
runtime dependency.

The workbook carries two sheets:

1. ``诊断规范V4`` (the sheet tab keeps its historical name) — the checklist,
   6 columns: 序号 / 一级维度 / 二级维度 / 诊断前置条件 / 检查项·判定标准 /
   质检违规等级建议. The V4-optimized revision numbers 22 items contiguously
   1–22 across 7 dimensions (简历外观 / 撰写规范 / 工作稳定性 / 职业成长性 /
   风险与合规 / 目标岗位匹配度 / 专业能力). Each item carries:
     * a short public ``topic`` — here the 二级维度 label: the only rubric
       wording clients ever see (it names WHERE the check looks, never the
       judged standard);
     * an optional ``prerequisite`` (``""`` / ``"jd"`` / ``"intention"``):
       item 17 requires the target JD, items 18–22 require a clear target
       intention (求职意向) that resolves to a level model;
     * the full ``criterion`` text and the ``qc`` 质检违规等级建议 text — both
       server-side only, sent to the LLM judge but never returned to clients.
       The five 专业能力 pointer rows intentionally carry no QC cell.
   Severity is recovered from the QC column: only an explicit 一票否决 marker
   makes an item a ``redline`` (item 16 only). 🔴 严重违规 on other items
   (e.g. the stability risk markers on item 14) is NOT a veto.
2. ``职级体系与能力模型对照表`` — a Java engineering leveling matrix (P3–P8
   columns × five capability elements, each cell listing the level's
   behavioral standards). Each level is exported as one competency model; its
   five elements fill the base rubric's 专业能力 items (ids 18–22) in place
   when a target intention resolves to a level (see
   ``app/services/diagnosis_competency.py``).

Earlier workbook revisions also carried a ``全局通用规则`` sheet (G1–G11
cross-item rules). The V4-optimized workbook folds that guidance into the
criterion cells, so the exported ``global_rules`` list is empty; the loader
keeps the field for forward compatibility.

Run from the repo root with ephemeral openpyxl (the xlsx is untrusted data):

    uv run --with openpyxl python -I scripts/export_diagnosis_rules.py

Verify the output after regenerating:

    git diff --stat apps/backend/app/services/diagnosis_rules.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
XLSX_PATH = REPO_ROOT / "rules" / "简历诊断规范_V4_优化版.xlsx"
OUT_PATH = REPO_ROOT / "apps" / "backend" / "app" / "services" / "diagnosis_rules.json"

SPEC_VERSION = "V4"
TITLE = "简历诊断规范"
RUBRIC_SHEET = "诊断规范V4"
GLOBAL_SHEET = "全局通用规则"
LEVEL_SHEET = "职级体系与能力模型对照表"

EXPECTED_ITEM_COUNT = 22

DIMENSION_KEYS: dict[str, str] = {
    "简历外观": "appearance",
    "撰写规范": "content",
    "工作稳定性": "stability",
    "职业成长性": "growth",
    "风险与合规": "compliance",
    "目标岗位匹配度": "fit",
    "专业能力": "competence",
}

# Column-D precondition text → artifact value.
PREREQUISITE_MAP: dict[str, str] = {
    "": "",
    "需要提供岗位JD": "jd",
    "需要明确求职意向": "intention",
}

# The V4-optimized workbook mislabels row 9's 二级维度 as 工作经历 even though
# its criterion is 【项目经验】 and its Sheet2 mapping is project based. Export
# the coherent label rather than the typo so two items never share a location.
SUBDIMENSION_FIXES: dict[int, str] = {
    9: "项目经验",
}

# A hard veto exists ONLY where the QC column's own 🔴 heading says 一票否决
# (item 16). Plain 🔴 严重 markers (e.g. the stability risk item) are severe
# findings but not vetoes — hence the marker must sit on the 🔴 heading line.
_REDLINE_RE = re.compile(r"🔴[^\n]*一票否决")
_SERIAL_RE = re.compile(r"^\s*(\d+)\s*$")
_GLOBAL_CODE_RE = re.compile(r"^\s*G(\d+)\s*$")

# Level columns in the 职级体系与能力模型对照表 sheet → regexes matching the
# corresponding target titles. Matching uses re.search (first matching model
# wins); patterns are ordered P3→P8 so the specific seniority words take
# precedence, and the bare "Java 开发工程师" title defaults to P4 (中级).
_LEVEL_TITLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "P3": (
        r"(?i)(?:p3|初级|助理)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p3|初级|助理)",
    ),
    "P4": (
        r"(?i)(?:p4|中级)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p4|中级)",
        # Generic Java engineer, whole-title anchored ("Java 开发工程师" → P4;
        # "资深 Java 开发工程师" must not match here — the space before Java
        # would otherwise let a seniority prefix sneak through).
        r"(?i)^java\s*(?:开发)?工程师$",
    ),
    "P5": (
        r"(?i)(?:p5|高级)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p5|高级)",
    ),
    "P6": (
        r"(?i)(?:p6|资深)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p6|资深)",
    ),
    "P7": (
        r"(?i)(?:p7|架构师)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p7|架构)",
    ),
    "P8": (
        r"(?i)(?:p8|技术专家)[\s\-/]*java",
        r"(?i)java[\s\-/]*(?:p8|技术专家)",
    ),
}

_LEVEL_FAMILY = "Java"
_LEVEL_HEADER_RE = re.compile(r"^\s*(P\d)\s*[:：]?\s*(.+?)\s*$")


def _clean_cell(value: Any) -> str:
    """Normalize a behavioral-standards cell: trimmed non-empty lines."""
    if value is None:
        return ""
    lines = [line.strip() for line in str(value).splitlines()]
    return "\n".join(line for line in lines if line)


def export_rubric(ws: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sheet 1: base checklist. Returns (dimensions, items)."""
    rows = list(ws.iter_rows(values_only=True))
    # Row 1 = title banner, row 2 = header, row 3+ = items. Item serials are
    # stored as integers; anything that is not a pure integer serial
    # (banner/header/合计) is skipped.
    data_rows: list[tuple[Any, ...]] = []
    for row in rows[2:]:
        serial = _SERIAL_RE.match(str(row[0] or ""))
        if serial:
            data_rows.append(row)

    dimensions: list[dict[str, Any]] = []
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    expected_id = 0
    for row in data_rows:
        item_id = int(_SERIAL_RE.match(str(row[0] or "")).group(1))  # type: ignore[union-attr]
        expected_id += 1
        if item_id != expected_id:
            raise ValueError(
                f"Rubric serials must be contiguous: expected {expected_id}, got {item_id}"
            )

        dim_name = str(row[1] or "").strip()
        if dim_name not in DIMENSION_KEYS:
            raise ValueError(f"Item {item_id} has unknown dimension {dim_name!r}")
        dimension_key = DIMENSION_KEYS[dim_name]
        if dim_name not in seen:
            seen.add(dim_name)
            dimensions.append({"key": dimension_key, "name": dim_name})

        sub_dimension = SUBDIMENSION_FIXES.get(item_id) or str(row[2] or "").strip()
        if not sub_dimension:
            raise ValueError(f"Item {item_id} has no 二级维度 (public topic label)")

        prerequisite_text = str(row[3] or "").strip()
        if prerequisite_text not in PREREQUISITE_MAP:
            raise ValueError(
                f"Item {item_id} has unknown prerequisite {prerequisite_text!r}"
            )
        prerequisite = PREREQUISITE_MAP[prerequisite_text]

        criterion = str(row[4] or "").strip()
        if not criterion:
            raise ValueError(f"Item {item_id} has empty criterion text")
        qc = str(row[5] or "").strip()
        # The competence pointer rows (18–22) defer to the level matrix and
        # carry no QC cell; every other item must carry the three-tier QC text.
        if not qc and dimension_key != "competence":
            raise ValueError(f"Item {item_id} has empty QC-level guidance text")

        items.append(
            {
                "id": item_id,
                "dimension": dimension_key,
                "dimension_name": dim_name,
                "sub_dimension": sub_dimension,
                # The 二级维度 label is the public problem-location label.
                "topic": sub_dimension,
                "prerequisite": prerequisite,
                "criterion": criterion,
                "qc": qc,
                "severity": "redline" if _REDLINE_RE.search(qc) else "normal",
            }
        )

    if expected_id != EXPECTED_ITEM_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_ITEM_COUNT} rubric items, workbook has {expected_id}"
        )
    return dimensions, items


def export_global_rules(ws: Any) -> list[dict[str, Any]]:
    """Optional legacy sheet: G-coded cross-item definitions (verbatim).

    The V4-optimized workbook no longer ships this sheet (the guidance was
    folded into the criterion cells); keep parsing it so older workbooks still
    export. Codes must be contiguous; no fixed total is required.
    """
    rows = list(ws.iter_rows(values_only=True))
    rules: list[dict[str, Any]] = []
    expected_number = 0
    for row in rows[2:]:  # banner + header rows skipped
        code_text = str(row[0] or "").strip()
        match = _GLOBAL_CODE_RE.match(code_text)
        if not match:
            continue
        expected_number += 1
        number = int(match.group(1))
        if number != expected_number:
            raise ValueError(
                f"Global rule codes must be contiguous: expected G{expected_number}, got {code_text}"
            )
        name = str(row[1] or "").strip()
        definition = str(row[2] or "").strip()
        applies_to = str(row[3] or "").strip()
        if not name or not definition:
            raise ValueError(f"Global rule {code_text} is missing its name or definition")
        rules.append(
            {
                "code": f"G{number}",
                "name": name,
                "definition": definition,
                "applies_to": applies_to,
            }
        )
    return rules


def export_competency_models(
    ws: Any, competence_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Sheet 2: one competency model per P-level column.

    Each model element points at the base item it fills (ids 18–22 in the
    专业能力 dimension); the matched element's standards replace that base
    item's pointer criterion at diagnosis time.
    """
    element_to_item_id = {item["sub_dimension"]: item["id"] for item in competence_items}

    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    level_columns: dict[str, tuple[int, str]] = {}
    for index, cell in enumerate(header[1:], start=1):
        match = _LEVEL_HEADER_RE.match(str(cell or ""))
        if not match:
            continue
        level, title = match.group(1), match.group(2).strip()
        level_columns[level] = (index, title)

    # Data rows: first cell names the capability element (row 2 is the
    # "行为标准" banner with an empty first cell — skipped). The workbook
    # pads one element label ("项目管理 ") with a trailing space.
    element_rows = [row for row in rows[1:] if str(row[0] or "").strip()]

    models: list[dict[str, Any]] = []
    for level in sorted(level_columns):
        column, title = level_columns[level]
        items: list[dict[str, Any]] = []
        for row in element_rows:
            element = str(row[0]).strip()
            if element not in element_to_item_id:
                raise ValueError(
                    f"{LEVEL_SHEET}: element {element!r} has no matching rubric item"
                )
            standard = _clean_cell(row[column] if column < len(row) else None)
            if not standard:
                continue
            items.append(
                {
                    "item_id": element_to_item_id[element],
                    "sub_dimension": element,
                    "criterion": standard,
                }
            )
        if len(items) != len(element_to_item_id):
            raise ValueError(
                f"Model java-{level.lower()} covers {len(items)}/{len(element_to_item_id)} elements"
            )
        items.sort(key=lambda entry: entry["item_id"])
        models.append(
            {
                "key": f"java-{level.lower()}",
                "name": f"{level} {title}能力模型",
                "family": _LEVEL_FAMILY,
                "level": level,
                "title_patterns": list(_LEVEL_TITLE_PATTERNS[level]),
                "items": items,
            }
        )
    return models


def export() -> dict[str, Any]:
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True, read_only=True)
    dimensions, items = export_rubric(wb[RUBRIC_SHEET])
    global_rules = (
        export_global_rules(wb[GLOBAL_SHEET]) if GLOBAL_SHEET in wb.sheetnames else []
    )
    competence_items = [item for item in items if item["dimension"] == "competence"]
    competency_models = (
        export_competency_models(wb[LEVEL_SHEET], competence_items)
        if LEVEL_SHEET in wb.sheetnames
        else []
    )

    return {
        "spec_version": SPEC_VERSION,
        "title": TITLE,
        "dimensions": dimensions,
        "global_rules": global_rules,
        "competency_models": competency_models,
        "items": items,
    }


def main() -> None:
    payload = export()
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    redlines = [i["id"] for i in payload["items"] if i["severity"] == "redline"]
    model_sizes = [f"{m['key']}({len(m['items'])})" for m in payload["competency_models"]]
    print(
        f"wrote {OUT_PATH.relative_to(REPO_ROOT)}: {len(payload['items'])} items, "
        f"{len(payload['dimensions'])} dimensions, "
        f"{len(redlines)} redlines {redlines}, "
        f"{len(payload['global_rules'])} global rules, "
        f"{len(payload['competency_models'])} competency models: {', '.join(model_sizes)}"
    )


if __name__ == "__main__":
    main()
