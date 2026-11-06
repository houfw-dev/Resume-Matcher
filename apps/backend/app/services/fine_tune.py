"""Job-less resume fine-tuning: original-text-grounded reorganization.

Pipeline (see ``docs/agent/features/fine-tune.md``):

1. Build a prompt from BOTH the original upload markdown (truncated) and the
   structured ResumeData JSON, plus the editable scope and user instruction.
2. Ask the model for a complete ResumeData-shaped JSON object.
3. Run the standard preservation finalizer with ``extra_evidence`` set to the
   original markdown, so facts the parser dropped can be restored while
   invented metrics are still reverted.
4. Force-restrict the result to the requested scope (personalInfo/sectionMeta
   always frozen).
5. Attach grounding warnings and a field-level diff for the compare view.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config_cache import get_content_language
from app.llm import complete_json
from app.prompts.fine_tune import (
    FINE_TUNE_PROMPT,
    FINE_TUNE_RANK_RULE,
    FINE_TUNE_RELOCATION_RULE_ALL,
    FINE_TUNE_RELOCATION_RULE_SCOPED,
    FINE_TUNE_SYSTEM_PROMPT,
    FINE_TUNE_TRUTHFULNESS_RULES,
    SCOPE_FALLBACK_LABELS,
)
from app.prompts.templates import get_language_name
from app.schemas.models import ResumeData, normalize_resume_data
from app.services.improver import _sanitize_user_input, calculate_resume_diff
from app.services.parser import normalize_text_hygiene
from app.services.tech_terms import canonicalize_tech_terms
from app.services.interview_prep import (
    _serialize_resume_data_for_prompt,
    _truncate_text_for_prompt,
)
from app.services.description_regions import merged_entry_regions
from app.services.resume_preservation import (
    _identity,
    finalize_ai_resume,
    grounding_review_warnings,
    merge_row_provenance,
)

logger = logging.getLogger(__name__)

_ORIGINAL_TEXT_PROMPT_CHAR_LIMIT = 20_000
_NO_ORIGINAL_TEXT_NOTICE = "(No original upload text is available.)"

# Top-level sections the "all" scope may replace. personalInfo and sectionMeta
# are never here: the finalizer always restores them from the source.
_REPLACEABLE_SECTIONS: tuple[str, ...] = (
    "summary",
    "workExperience",
    "education",
    "personalProjects",
    "additional",
    "customSections",
)
_SECTION_TOKENS: frozenset[str] = frozenset(
    ("summary", "education", "additional", "customSections", "workExperience", "personalProjects")
)
_ITEM_TOKEN_RE = re.compile(r"^(work|project)_(\d+)$")
# Sub-module (label region) token: "work_0:achievements" /
# "project_2:highlights". Only rows owned by that label inside that one entry
# are editable; the label row itself and all other rows stay source-frozen.
_REGION_TOKEN_RE = re.compile(
    r"^(work|project)_(\d+):(techStack|background|duties|highlights"
    r"|achievements|role)$"
)
# Per-custom-section token: "custom_<customSections key>". Builder keys are
# themselves custom_N, hence the double-prefix token custom_custom_1.
_CUSTOM_TOKEN_RE = re.compile(r"^custom_([\w.-]+)$", re.UNICODE)

# English names used in the prompt scope block; the label text itself (e.g.
# 项目亮点：） is quoted so the model has an unambiguous row boundary.
_REGION_PROMPT_NAMES: dict[str, str] = {
    "techStack": "technology stack",
    "background": "project background",
    "duties": "responsibilities",
    "highlights": "project highlights",
    "achievements": "achievements",
    "role": "project role",
}

DIFF_UNAVAILABLE_WARNING = (
    "The change comparison is temporarily unavailable; review the rendered "
    "preview carefully before confirming."
)

# Emitted on module-scoped runs whose in-scope narrative text looks like it
# belongs in additional (awards/certifications). Relocation needs the target
# section to be in scope, so only an all-section fine-tune can move the items.
SCOPE_RELOCATION_HINT = "SCOPE_RELOCATION_HINT: {kinds}"

# Emitted on label-region fine-tunes when the model returned more rows than
# the region owns: region edits replace rows in place (fixed row count), so
# appended rows are not applied. The frontend localizes by this prefix.
REGION_APPEND_DROPPED_WARNING = (
    "REGION_APPEND_DROPPED: sub-module fine-tuning keeps the original row "
    "count; extra rewritten rows were not applied."
)

_MISPLACED_AWARD_RE = re.compile(
    r"奖项|荣誉|荣获|获奖|奖学金|优秀奖|[一二三四五六七八九十0-9]+\s*等奖|"
    r"冠军|亚军|季军|金奖|银奖|铜奖"
)
_MISPLACED_CERT_RE = re.compile(
    r"证书|认证|资格证|执业|执照|结课证明|结业证书|"
    r"PMP|CPA|CFA|CET[-\s]?[46]|雅思|托福|IELTS|TOEFL|AWS|Azure|Google Cloud"
)
_LIST_DESCRIPTION_SECTIONS: tuple[str, ...] = (
    "workExperience",
    "education",
    "personalProjects",
)


def _description_text(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    description = entry.get("description")
    if isinstance(description, list):
        return "\n".join(str(row) for row in description)
    if isinstance(description, str):
        return description
    return ""


def _structured_evidence_text(source: dict[str, Any]) -> str:
    """Narrative text already inside the structured resume.

    Including it as grounding evidence lets a fact move BETWEEN sections (e.g.
    an award trapped in an education description) even when no original upload
    markdown exists.
    """
    parts: list[str] = []
    summary = source.get("summary")
    if isinstance(summary, str):
        parts.append(summary)
    for section in _LIST_DESCRIPTION_SECTIONS:
        entries = source.get(section)
        if isinstance(entries, list):
            parts.extend(_description_text(entry) for entry in entries)
    return "\n".join(part for part in parts if part.strip())


def build_grounding_evidence(
    source: dict[str, Any], original_markdown: str
) -> str:
    """Combined evidence text: upload markdown plus structured narrative rows."""
    return "\n".join(
        part
        for part in (
            original_markdown.strip(),
            _structured_evidence_text(source),
        )
        if part
    )


def _in_scope_description_sections(kind: str, targets: list[str]) -> list[str]:
    if kind == "all":
        return list(_LIST_DESCRIPTION_SECTIONS)
    sections: list[str] = []
    if "education" in targets:
        sections.append("education")
    if "workExperience" in targets or any(
        token.startswith("work_") for token in targets
    ):
        sections.append("workExperience")
    if "personalProjects" in targets or any(
        token.startswith("project_") for token in targets
    ):
        sections.append("personalProjects")
    return sections


def _misplacement_hints(
    source: dict[str, Any], kind: str, targets: list[str]
) -> list[str]:
    """Detect awards/certificates trapped in in-scope narrative sections.

    Only emitted for module-scoped runs that do NOT include ``additional``:
    relocating items into a frozen target section is impossible, so the hint
    directs the user to an all-section fine-tune.
    """
    if kind != "modules" or "additional" in targets:
        return []
    scanned_sections = _in_scope_description_sections(kind, targets)
    item_targets = {
        token for token in targets if _ITEM_TOKEN_RE.match(token) is not None
    }
    whole_sections = set(targets) & set(_LIST_DESCRIPTION_SECTIONS)
    kinds: set[str] = set()
    for section in scanned_sections:
        entries = source.get(section)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            item_token = (
                f"work_{index}"
                if section == "workExperience"
                else f"project_{index}"
                if section == "personalProjects"
                else None
            )
            # Whole-section token in targets => every entry; otherwise only
            # explicitly checked item tokens (education has no item tokens).
            if item_token is not None and section not in whole_sections:
                if item_token not in item_targets:
                    continue
            text = _description_text(entry)
            if not text:
                continue
            if _MISPLACED_AWARD_RE.search(text):
                kinds.add("awards")
            if _MISPLACED_CERT_RE.search(text):
                kinds.add("certifications")
    if not kinds:
        return []
    return [SCOPE_RELOCATION_HINT.format(kinds=",".join(sorted(kinds)))]


@dataclass
class FineTuneResult:
    improved_data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    diff_summary: Any | None = None
    detailed_changes: list[Any] = field(default_factory=list)
    ignored_targets: list[str] = field(default_factory=list)


def _canonical_source(resume: dict[str, Any]) -> dict[str, Any]:
    processed = resume.get("processed_data")
    if not isinstance(processed, dict):
        raise ValueError("Resume has no structured data; parse it before fine-tuning")
    # Run the same read-time governance chain GET/PATCH use, so the model and
    # every preservation check see the healed shape the user sees (labeled
    # award/cert/language rows already relocated, section meta canonical).
    # normalize mutates in place, so deep-copy before normalizing.
    normalized = normalize_resume_data(copy.deepcopy(processed))
    return ResumeData.model_validate(normalized).model_dump()


def _entry_label(source: dict[str, Any], section: str, index: int) -> str:
    entries = source.get(section, [])
    if not isinstance(entries, list) or index >= len(entries):
        return ""
    entry = entries[index] if isinstance(entries[index], dict) else {}
    if section == "workExperience":
        title = str(entry.get("title") or "").strip()
        company = str(entry.get("company") or "").strip()
        return " — ".join(part for part in (title, company) if part)
    if section == "personalProjects":
        name = str(entry.get("name") or "").strip()
        role = str(entry.get("role") or "").strip()
        return " — ".join(part for part in (name, role) if part)
    return ""


def _custom_display_name(source: dict[str, Any], key: str) -> str:
    """Resolve a custom-section key to its user-facing name via sectionMeta."""
    meta_rows = source.get("sectionMeta")
    if not isinstance(meta_rows, list):
        return ""
    for row in meta_rows:
        if (
            isinstance(row, dict)
            and row.get("key") == key
            and row.get("isDefault") is False
        ):
            name = row.get("displayName")
            return str(name).strip() if isinstance(name, str) else ""
    return ""


def build_scope_description(
    source: dict[str, Any], kind: str, targets: list[str]
) -> str:
    """Human-readable editable-scope block for the prompt (English; UI localizes)."""
    if kind == "all":
        return (
            "ALL sections except personalInfo and sectionMeta. You may "
            "reorganize every entry's descriptions but must not add, remove or "
            "reorder the entries themselves."
        )
    lines: list[str] = []
    for token in targets:
        if token in SCOPE_FALLBACK_LABELS:
            lines.append(f"- {token}: {SCOPE_FALLBACK_LABELS[token]}")
            continue
        custom_match = _CUSTOM_TOKEN_RE.match(token)
        if custom_match:
            key = custom_match.group(1)
            display_name = _custom_display_name(source, key)
            suffix = f" ({display_name})" if display_name else ""
            lines.append(f"- customSections[{key}]{suffix}: only this custom section")
            continue
        item_match = _ITEM_TOKEN_RE.match(token)
        if item_match:
            index = int(item_match.group(2))
            section = (
                "workExperience" if item_match.group(1) == "work" else "personalProjects"
            )
            label = _entry_label(source, section, index)
            suffix = f" ({label})" if label else ""
            lines.append(f"- {section}[{index}]{suffix}: only this entry")
            continue
        region_match = _REGION_TOKEN_RE.match(token)
        if region_match:
            lines.append(_region_scope_line(source, region_match))
    return "\n".join(lines) if lines else "- (no specific target)"


def _region_scope_line(source: dict[str, Any], match: re.Match[str]) -> str:
    """One prompt scope line for a ``(work|project)_N:region`` token."""
    entry_kind = match.group(1)
    index = int(match.group(2))
    region_id = match.group(3)
    section = (
        "workExperience" if entry_kind == "work" else "personalProjects"
    )
    entries = source.get(section)
    token = match.group(0)
    if not isinstance(entries, list) or index >= len(entries):
        return f"- {token}: sub-module not present in this entry; copy it unchanged"
    entry = entries[index]
    if not isinstance(entry, dict):
        return f"- {token}: sub-module not present in this entry; copy it unchanged"
    regions = merged_entry_regions(
        entry.get("description"), entry.get("descriptionStyles"), kind=entry_kind
    )
    region = regions.get(region_id)
    entry_label = _entry_label(source, section, index)
    suffix = f" ({entry_label})" if entry_label else ""
    english_name = _REGION_PROMPT_NAMES.get(region_id, region_id)
    if region is None:
        return (
            f"- {section}[{index}]{suffix}: no \"{english_name}\" sub-module in "
            "this entry; copy it unchanged"
        )
    row_count = len(region.content_indices)
    return (
        f"- {section}[{index}]{suffix} > sub-module \"{region.label_text}\" "
        f"({english_name}): rewrite ONLY the {row_count} row(s) under this "
        f"label within this entry. Output exactly {row_count} replacement "
        "row(s); the label row itself, every other sub-module and every other "
        "entry must be copied through unchanged."
    )


def _validate_scoped_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate the overlaid result after presentation hygiene.

    These passes are style-preserving (term casing, trim, blank row/style
    lockstep drops, unified list-point endings), so rows the user just flipped
    into list points also lose their trailing periods. The full
    normalize_resume_data() chain must NOT run here: its label-region style
    repair would undo the explicit plain<->bullet flips the region overlay
    applied.
    """
    cleaned = canonicalize_tech_terms(result)
    return ResumeData.model_validate(normalize_text_hygiene(cleaned)).model_dump()


def restrict_to_scope(
    source: dict[str, Any],
    candidate: dict[str, Any],
    kind: str,
    targets: list[str],
) -> tuple[dict[str, Any], list[str], bool]:
    """Force out-of-scope sections back to the source; never mutate inputs.

    Third return value flags label-region edits whose model-produced extra
    rows had to be dropped (region overlay keeps the source row count).
    """
    result = copy.deepcopy(source)
    ignored: list[str] = []
    region_appends_dropped = False
    if kind == "all":
        for section in _REPLACEABLE_SECTIONS:
            if section in candidate:
                result[section] = copy.deepcopy(candidate[section])
        return _validate_scoped_result(result), ignored, False

    whole_sections = {token for token in targets if token in _SECTION_TOKENS}
    for token in whole_sections:
        if token in candidate:
            result[token] = copy.deepcopy(candidate[token])

    for token in targets:
        item_match = _ITEM_TOKEN_RE.match(token)
        if item_match is None:
            continue
        index = int(item_match.group(2))
        section = (
            "workExperience" if item_match.group(1) == "work" else "personalProjects"
        )
        if section in whole_sections:
            continue
        source_entries = source.get(section)
        candidate_entries = candidate.get(section)
        if not isinstance(source_entries, list) or not isinstance(candidate_entries, list):
            ignored.append(token)
            continue
        if index >= len(source_entries):
            ignored.append(token)
            continue
        # The model may reorder entries; locate the finalized entry by identity
        # and place it back into its source slot.
        wanted_identity = _identity(source_entries[index], section)
        match_index = next(
            (
                candidate_index
                for candidate_index, entry in enumerate(candidate_entries)
                if isinstance(entry, dict)
                and _identity(entry, section) == wanted_identity
            ),
            None,
        )
        if match_index is None:
            ignored.append(token)
            continue
        result.setdefault(section, copy.deepcopy(source_entries))
        result[section][index] = copy.deepcopy(candidate_entries[match_index])

    custom_whole = "customSections" in whole_sections
    source_custom = source.get("customSections")
    candidate_custom = candidate.get("customSections")
    for token in targets:
        custom_match = _CUSTOM_TOKEN_RE.match(token)
        if custom_match is None:
            continue
        # The whole-section token supersedes per-block tokens, mirroring the
        # workExperience/work_N interaction above.
        if custom_whole:
            continue
        key = custom_match.group(1)
        if (
            not isinstance(source_custom, dict)
            or not isinstance(candidate_custom, dict)
            or key not in source_custom
            or key not in candidate_custom
        ):
            ignored.append(token)
            continue
        result["customSections"][key] = copy.deepcopy(candidate_custom[key])

    region_appends_dropped = _overlay_region_targets(
        source, candidate, result, whole_sections, targets, ignored
    )

    return (
        _validate_scoped_result(result),
        ignored,
        region_appends_dropped,
    )


def _resolve_entry(
    section: str, index: int, source_entries: Any, candidate_entries: Any
) -> tuple[dict[str, Any], dict[str, Any], int] | None:
    """Find source/finalized entries for one item index, honoring reorders."""
    if not isinstance(source_entries, list) or not isinstance(candidate_entries, list):
        return None
    if index >= len(source_entries) or not isinstance(source_entries[index], dict):
        return None
    wanted_identity = _identity(source_entries[index], section)
    match_index = next(
        (
            candidate_index
            for candidate_index, entry in enumerate(candidate_entries)
            if isinstance(entry, dict)
            and _identity(entry, section) == wanted_identity
        ),
        None,
    )
    if match_index is None:
        # Entries already validated as dicts above.
        return None
    return source_entries[index], candidate_entries[match_index], match_index


def _overlay_region_targets(
    source: dict[str, Any],
    candidate: dict[str, Any],
    result: dict[str, Any],
    whole_sections: set[str],
    targets: list[str],
    ignored: list[str],
) -> bool:
    """Replace in-place only rows owned by targeted label regions.

    The label row itself and every row outside the targeted regions stays
    byte-identical to the source. Replacement text keeps the SOURCE row style,
    except that an explicit plain<->bullet formatting request is honoured on
    aligned kept rows (label styles never move). Model rows with no source
    counterpart (appended rows) are never adopted here; their presence for a
    touched entry sets the dropped flag.
    """
    # Group region tokens per (entry kind, entry index) so several regions of
    # one entry overlay one merged entry dict.
    grouped: dict[tuple[str, int], list[str]] = {}
    for token in targets:
        match = _REGION_TOKEN_RE.match(token)
        if match is not None:
            grouped.setdefault(
                (match.group(1), int(match.group(2))), []
            ).append(match.group(3))

    appends_dropped = False
    item_tokens = {token for token in targets if _ITEM_TOKEN_RE.match(token)}

    for (entry_kind, index), region_ids in grouped.items():
        section = (
            "workExperience" if entry_kind == "work" else "personalProjects"
        )
        # Whole-section and whole-entry targets supersede region tokens.
        if section in whole_sections or f"{entry_kind}_{index}" in item_tokens:
            continue
        resolved = _resolve_entry(
            section,
            index,
            source.get(section),
            candidate.get(section),
        )
        if resolved is None:
            ignored.extend(
                f"{entry_kind}_{index}:{region_id}" for region_id in region_ids
            )
            continue
        source_entry, candidate_entry, _ = resolved
        regions = merged_entry_regions(
            source_entry.get("description"),
            source_entry.get("descriptionStyles"),
            kind=entry_kind,  # type: ignore[arg-type]
        )
        valid_ids: list[str] = []
        for region_id in region_ids:
            if region_id in regions:
                valid_ids.append(region_id)
            else:
                ignored.append(f"{entry_kind}_{index}:{region_id}")
        if not valid_ids:
            continue
        provenance, appended = merge_row_provenance(source_entry, candidate_entry)
        if appended:
            appends_dropped = True
        merged_entry = copy.deepcopy(source_entry)
        rows = merged_entry.get("description")
        editable_indices = sorted(
            {
                source_index
                for region_id in valid_ids
                for source_index in regions[region_id].content_indices
            }
        )
        candidate_rows = candidate_entry.get("description")
        candidate_styles = candidate_entry.get("descriptionStyles")
        merged_styles = merged_entry.get("descriptionStyles")
        styles_list = (
            merged_styles if isinstance(merged_styles, list) else []
        )
        for source_index in editable_indices:
            finalized_index = provenance.get(source_index)
            if finalized_index is None or not isinstance(candidate_rows, list):
                continue
            candidate_row = candidate_rows[finalized_index]
            if (
                isinstance(rows, list)
                and source_index < len(rows)
                and isinstance(candidate_row, str)
            ):
                rows[source_index] = candidate_row
            # An explicit formatting request ("render the rows under this
            # sub-head as an ordered list") may flip a kept row between plain
            # and bullet. The finalized candidate already passed the style-
            # edit policy, so only plain<->bullet on aligned indices is taken;
            # label rows and label-shaped spans never change.
            source_style = (
                styles_list[source_index] if source_index < len(styles_list) else None
            )
            candidate_style = (
                candidate_styles[finalized_index]
                if isinstance(candidate_styles, list)
                and finalized_index < len(candidate_styles)
                else None
            )
            if (
                source_style in ("plain", "bullet")
                and candidate_style in ("plain", "bullet")
                and candidate_style != source_style
            ):
                styles_list[source_index] = candidate_style
        if isinstance(merged_styles, list) and isinstance(
            merged_entry.get("description"), list
        ):
            merged_entry["descriptionStyles"] = styles_list
        result[section][index] = merged_entry

    return appends_dropped


def _validate_model_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Fine-tune response must be a JSON object")
    return ResumeData.model_validate(raw).model_dump()


async def run_fine_tune(
    *,
    resume: dict[str, Any],
    kind: str,
    targets: list[str],
    instruction: str,
    output_language: str | None = None,
) -> FineTuneResult:
    """Generate, ground, scope-restrict and diff one fine-tune preview."""
    source = _canonical_source(resume)
    original_markdown = str(resume.get("original_markdown") or "").strip()
    # Grounding evidence covers both the upload text and facts already inside
    # the structured resume, so content can move between sections without
    # looking invented.
    evidence = build_grounding_evidence(source, original_markdown)

    original_text = (
        _truncate_text_for_prompt(
            original_markdown, _ORIGINAL_TEXT_PROMPT_CHAR_LIMIT
        )
        if original_markdown
        else _NO_ORIGINAL_TEXT_NOTICE
    )
    resume_json = _serialize_resume_data_for_prompt(source)
    clean_instruction = _sanitize_user_input(instruction or "")
    language_code = output_language or get_content_language()
    language_name = get_language_name(language_code)

    prompt = FINE_TUNE_PROMPT.format(
        critical_truthfulness_rules=FINE_TUNE_TRUTHFULNESS_RULES,
        relocation_rule=(
            FINE_TUNE_RELOCATION_RULE_ALL
            if kind == "all"
            else FINE_TUNE_RELOCATION_RULE_SCOPED
        ),
        rank_rule=FINE_TUNE_RANK_RULE,
        scope_description=build_scope_description(source, kind, targets),
        output_language=language_name,
        user_instruction=clean_instruction or "(none)",
        original_markdown=original_text,
        resume_json=resume_json,
    )

    candidate_raw = await complete_json(
        prompt=prompt,
        system_prompt=FINE_TUNE_SYSTEM_PROMPT,
        max_tokens=8192,
        schema_type="fine_tune",
        response_validator=_validate_model_payload,
    )
    candidate = ResumeData.model_validate(candidate_raw).model_dump()

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=True,
        allow_appended_rows=True,
        extra_evidence=evidence or None,
        allow_relocation=kind == "all",
        # Fine-tune instructions may explicitly reformat paragraphs as an
        # ordered list (or back); the finalizer may then flip plain<->bullet
        # on kept rows. Label rows stay frozen everywhere.
        allow_style_edits=True,
    )
    improved, ignored_targets, appends_dropped = restrict_to_scope(
        source, finalized, kind, targets
    )

    warnings = _misplacement_hints(source, kind, targets)
    if appends_dropped:
        warnings.append(REGION_APPEND_DROPPED_WARNING)
    warnings.extend(
        grounding_review_warnings(
            source, improved, extra_evidence=evidence or None
        )
    )
    diff_summary = None
    detailed_changes: list[Any] = []
    try:
        diff_summary, detailed_changes = calculate_resume_diff(source, improved)
    except Exception as e:  # diffs are advisory; never block the preview
        logger.warning("Fine-tune diff calculation failed: %s", e)
        warnings.append(DIFF_UNAVAILABLE_WARNING)

    return FineTuneResult(
        improved_data=improved,
        warnings=warnings,
        diff_summary=diff_summary,
        detailed_changes=detailed_changes,
        ignored_targets=ignored_targets,
    )
