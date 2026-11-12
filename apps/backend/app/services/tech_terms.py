"""Deterministic canonical casing for technical English terms.

Implements the user's text-quality rule "技术英文名词全篇大小写保持统一": a
curated table of mainstream stack names is applied with one case-insensitive
regex pass over the *content* fields of a parsed resume. It fixes casing only
(``java`` → ``Java``, ``SPRING BOOT`` → ``Spring Boot``, ``mysql集群`` →
``MySQL集群``); it never adds, removes or translates anything, and OCR/typo
*spelling* correction stays the LLM's job (prompt rule), not this table's.

Boundary semantics
------------------

``(?<![A-Za-z0-9]) … (?![A-Za-z0-9])`` around every term means:

* adjacency to CJK, punctuation or whitespace is a match (``Redis集群``);
* adjacency to another ASCII letter/digit is not, so ``Java`` can never match
  inside ``JavaScript`` and ``Vue.js`` never inside ``Vue.jsx``;
* longer terms are listed first, so ``Spring Cloud Alibaba`` wins over
  ``Spring Cloud`` / ``Spring``.

Skip rules (do not canonicalize): ``years`` (dates), ``personalInfo`` (name,
phone, email, links), ``sectionMeta`` (display names), and URL fields.
"""

import copy
import re
from typing import Any

from app.services.parser_rules import get_parser_rules

#: Curated mainstream-stack table, canonical casing. Order is irrelevant —
#: the alternation is rebuilt longest-first. The words themselves are data and
#: ship in parser_rules.json (vocabulary ``canonical_tech_terms``, human source
#: rules/shared_terms.yaml); the frontend binds the same YAML through its
#: generated lib/generated/tech-terms.generated.ts module.
CANONICAL_TERMS: tuple[str, ...] = tuple(
    get_parser_rules().vocabulary_list("canonical_tech_terms")
)

# Build the alternation longest-first so compounds win over their prefixes;
# re.escape protects the ".", "+", "/" characters.
_SORTED_TERMS = sorted(set(CANONICAL_TERMS), key=len, reverse=True)
_TERM_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(re.escape(term) for term in _SORTED_TERMS)
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_CANONICAL_BY_LOWER: dict[str, str] = {term.lower(): term for term in _SORTED_TERMS}


def canonicalize_terms_in_text(value: Any) -> Any:
    """Replace every known term in one string with its canonical casing."""
    if not isinstance(value, str) or not value:
        return value
    return _TERM_RE.sub(lambda match: _CANONICAL_BY_LOWER[match.group(0).lower()], value)


def _canonicalize_rows(rows: Any) -> Any:
    if isinstance(rows, list):
        return [canonicalize_terms_in_text(row) for row in rows]
    return rows


def canonicalize_tech_terms(parsed_data: dict[str, Any]) -> dict[str, Any]:
    """Apply canonical term casing to a parsed resume's content fields.

    Pure: the input is deep-copied first. Non-string values pass through.
    """
    data = copy.deepcopy(parsed_data)

    if isinstance(data.get("summary"), str):
        data["summary"] = canonicalize_terms_in_text(data["summary"])

    work_entries = data.get("workExperience")
    if isinstance(work_entries, list):
        for entry in work_entries:
            if not isinstance(entry, dict):
                continue
            for field in ("title", "department"):
                if isinstance(entry.get(field), str):
                    entry[field] = canonicalize_terms_in_text(entry[field])
            entry["description"] = _canonicalize_rows(entry.get("description"))

    project_entries = data.get("personalProjects")
    if isinstance(project_entries, list):
        for entry in project_entries:
            if not isinstance(entry, dict):
                continue
            for field in ("name", "role"):
                if isinstance(entry.get(field), str):
                    entry[field] = canonicalize_terms_in_text(entry[field])
            entry["description"] = _canonicalize_rows(entry.get("description"))

    additional = data.get("additional")
    if isinstance(additional, dict):
        for field in ("technicalSkills", "languages", "certificationsTraining", "awards"):
            additional[field] = _canonicalize_rows(additional.get(field))

    custom_sections = data.get("customSections")
    if isinstance(custom_sections, dict):
        for section in custom_sections.values():
            if not isinstance(section, dict):
                continue
            section_type = section.get("sectionType")
            if section_type == "itemList":
                items = section.get("items")
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        for field in ("title", "subtitle"):
                            if isinstance(item.get(field), str):
                                item[field] = canonicalize_terms_in_text(item[field])
                        item["description"] = _canonicalize_rows(
                            item.get("description")
                        )
            elif section_type == "stringList":
                section["strings"] = _canonicalize_rows(section.get("strings"))
            elif section_type == "text" and isinstance(section.get("text"), str):
                section["text"] = canonicalize_terms_in_text(section["text"])

    return data
