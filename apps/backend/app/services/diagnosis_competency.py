"""Per-role competency models for the V4-optimized diagnosis rubric.

The base rubric's 专业能力 dimension (base items 18–22: 系统架构 / 业务架构 /
开发技能 / 应用技能 / 项目管理) is role-specific. Its workbook rows only point
at the level matrix ("从 Sheet2 获取对应行为标准……"): without a clear target
intention (求职意向) that resolves to a level model they cannot be judged and
are rated ``na``. A JD is NOT required. A competency model supplies the
behavioral standards for those five base items at one level (e.g. Java P5),
which then replace the pointer text in place and get judged by the LLM.

The shipped models are the **Java engineering level matrix** from the
workbook's ``职级体系与能力模型对照表`` sheet — six levels (P3–P8). Models live
inside ``diagnosis_rules.json`` under ``competency_models``::

    {
      "key": "java-p5",
      "name": "P5 高级Java开发工程师能力模型",
      "family": "Java",
      "level": "P5",
      "title_patterns": ["(?i)(?:p5|高级)[\\s\\-/]*java", ...],
      "items": [
        {"item_id": 18, "sub_dimension": "系统架构", "criterion": "行为标准……"},
        ...
      ]
    }

With no resolved target intention or no matched/selected model the base rules
are returned untouched (items 18–22 then carry their pointer criteria, are
never sent to the LLM and are reported ``na``). The standards only ever travel
server-side (rules JSON → LLM prompt); they are never returned to clients.

Mode exclusivity (enforced in ``diagnosis.diagnose_resume``): competency-model
diagnosis and JD diagnosis are mutually exclusive. When a job description is
present the effective model key is forced to ``none`` — title auto-matching is
suppressed even if the target title would match — and an explicit real model
key combined with a JD raises ``DiagnosisModeConflictError`` (HTTP 400).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from app.services.diagnosis_rules import DiagnosisRules

# Explicit "run the base rubric without a competency model" choice from the
# picker. Distinct from no key at all, which falls back to title matching —
# otherwise the user could never opt out when the title auto-matches.
NO_COMPETENCY_MODEL_KEY = "none"


@dataclass(frozen=True)
class CompetencyModel:
    """One role-specific checklist bundle (e.g. one Java P-level)."""

    key: str
    name: str
    title_patterns: tuple[re.Pattern[str], ...]
    items: tuple[dict[str, Any], ...]
    family: str = ""  # e.g. "Java"
    level: str = ""  # e.g. "P5"; empty for role models without a level axis

    def matches(self, title: str) -> bool:
        """Whether the target job title activates this model."""
        return any(pattern.search(title) for pattern in self.title_patterns)


def parse_competency_models(raw: list[dict[str, Any]]) -> list[CompetencyModel]:
    """Parse competency model entries from the rules JSON."""
    models: list[CompetencyModel] = []
    for entry in raw:
        key = str(entry.get("key") or "").strip()
        name = str(entry.get("name") or "").strip()
        items = entry.get("items") or []
        if not key or not name or not isinstance(items, list | tuple):
            continue
        patterns = tuple(
            re.compile(str(pattern))
            for pattern in (entry.get("title_patterns") or [])
            if str(pattern).strip()
        )
        models.append(
            CompetencyModel(
                key=key,
                name=name,
                title_patterns=patterns,
                items=tuple(item for item in items if isinstance(item, dict)),
                family=str(entry.get("family") or "").strip(),
                level=str(entry.get("level") or "").strip(),
            )
        )
    return models


def get_competency_model(
    models: list[CompetencyModel], key: str | None
) -> CompetencyModel | None:
    """Look a parsed model up by its stable key (None when unknown)."""
    if not key:
        return None
    normalized = key.strip()
    return next((model for model in models if model.key == normalized), None)


def resolve_competency_model(
    models: list[CompetencyModel],
    target_title: str | None,
    explicit_key: str | None = None,
) -> CompetencyModel | None:
    """Choose the model for a diagnosis run.

    An explicit user choice (the picker shown when there is no intention or no
    automatic match) always wins: a real model key selects it,
    ``NO_COMPETENCY_MODEL_KEY`` opts out of title matching entirely; otherwise
    the first title-regex match is used, or no model. Raises ``KeyError`` when
    the explicit key identifies neither a shipped model nor the opt-out.
    """
    if explicit_key and explicit_key.strip():
        normalized = explicit_key.strip()
        if normalized == NO_COMPETENCY_MODEL_KEY:
            return None
        model = get_competency_model(models, normalized)
        if model is None:
            raise KeyError(normalized)
        return model
    return select_competency_model(models, target_title)


def select_competency_model(
    models: list[CompetencyModel], target_title: str | None
) -> CompetencyModel | None:
    """Pick the first model whose pattern matches the target title."""
    if not target_title:
        return None
    title = target_title.strip()
    if not title:
        return None
    for model in models:
        if model.matches(title):
            return model
    return None


def expand_rules(base: Any, model: CompetencyModel | None) -> Any:
    """Fill the base rubric's 专业能力 items with the selected model's standards.

    Each model entry targets a base item id (18–22) via its ``item_id``; that
    item's pointer criterion is replaced with the level's behavioral standard.
    With ``model is None`` (no title match and no explicit user choice) the base
    rules are returned untouched. The cached base rules are never mutated.
    """
    if model is None or not model.items:
        return base

    items: dict[int, dict[str, Any]] = {
        item_id: copy.deepcopy(item) for item_id, item in base.items.items()
    }
    for entry in model.items:
        item_id = int(entry.get("item_id") or 0)
        target = items.get(item_id)
        if target is None:
            continue
        standard = str(entry.get("criterion") or "").strip()
        if standard:
            target["criterion"] = standard

    return DiagnosisRules(
        spec_version=base.spec_version,
        items=items,
        dimensions=copy.deepcopy(base.dimensions),
        dimension_order=tuple(base.dimension_order),
        global_rules=base.global_rules,
        competency_models=base.competency_models,
        parameters=base.parameters,
        vocabularies=base.vocabularies,
    )
