"""Resume diagnosis orchestration (rubric V4-optimized, checklist edition).

Hybrid judging pipeline:

1. ``diagnosis_checks`` deterministically answers every checklist item the
   structured ResumeData can settle — including date-arithmetic checks and
   stability risk markers. No LLM, no drift.
2. The remaining semantic items go to one structured JSON LLM call, together
   with a precomputed facts packet (timeline, gaps, tenure, point counts) so
   the model never has to do date math itself. That same call optionally runs
   the item-7 auxiliary review: regex-missed stack groups are rescued only
   when the model quotes a verbatim skill-entry synonym (never downgraded).
3. Verdicts merge into ``diagnosis_summary`` for checklist counts and the
   hard-veto red-line verdict (no points/band).

The diagnosis anchors on a job title (求职意向): the request may name one
explicitly (multi-intention resumes let the user pick), otherwise the resume's
``personalInfo.title`` is used. A matching per-role competency model
(``diagnosis_competency``) fills the 专业能力 items (18–22) with the level's
behavioral standards.

Prerequisites (from the rules artifact) gate items the context cannot support,
and the two gates are independent in the V4-optimized rubric:

* item 17 (目标岗位匹配度) requires a target JD and is ``na`` without one;
* items 18–22 (专业能力) require a clear target intention that resolves to a
  level model and are ``na`` without one — a JD is NOT required, so a no-JD
  diagnosis still judges 18–22 whenever the intention resolves.

Item 15 (growth) is objectively ``na`` below 5 effective dev years.

The rubric standards never leave the server: the LLM prompt carries the
criteria and the QC-level guidance, but the API/Word payloads expose only each
item's short ``topic`` label plus the resume-grounded evidence and suggestion.

Items the model omits after its retry budget default to "partial" with a
visible warning — never silently disappear from the checklist.
"""

import json
import logging
import re
from typing import Any

from app.config_cache import get_content_language
from app.llm import complete_json, get_llm_config, get_model_name, get_safe_max_tokens
from app.prompts import get_language_name
from app.prompts.diagnosis import (
    DIAGNOSIS_COMPETENCY_BLOCK,
    DIAGNOSIS_JOB_BLOCK,
    DIAGNOSIS_ORIGINAL_BLOCK,
    DIAGNOSIS_PROMPT,
    DIAGNOSIS_RENDERED_BLOCK,
    DIAGNOSIS_SKILL_REVIEW_BLOCK,
    DIAGNOSIS_SYSTEM_PROMPT,
    DIAGNOSIS_TARGET_BLOCK,
)
from app.schemas.diagnosis import (
    CompetencyModelInfo,
    DiagnosisItemResult,
    DiagnosisReport,
    DimensionResult,
    RatingCounts,
    RedLineStatus,
    RenderedLayoutIn,
    TemplateSettingsIn,
)
from app.services.diagnosis_checks import (
    _MAINSTREAM_GROUPS,
    _STACK_CONFORM_RATIO,
    _check_skill_count,
    _join_findings,
    _layout_facts,
    _usable_layout,
    build_mainstream_stack_finding,
    mainstream_stack_coverage,
    run_objective_checks,
    technical_skill_entries,
)
from app.services.diagnosis_competency import (
    expand_rules,
    parse_competency_models,
    resolve_competency_model,
)
from app.services.diagnosis_rules import (
    COMPETENCE_DIMENSION_KEY,
    RATINGS,
    RATING_CONFORM,
    RATING_NA,
    RATING_PARTIAL,
    get_rules,
)
from app.services.diagnosis_summary import summarize_verdicts
from app.services.interview_prep import (
    _serialize_resume_data_for_prompt,
    _truncate_text_for_prompt,
)

logger = logging.getLogger(__name__)

_JOB_DESCRIPTION_CHAR_LIMIT = 12_000
# Original-resume grounding text bound for the judge prompt (omissions are made
# explicit by _truncate_text_for_prompt's notice instead of silently cut).
_ORIGINAL_RESUME_CHAR_LIMIT = 20_000
# Whole rendered-layout block bound (facts JSON + per-page text mirror). The
# mirror is the bulk, so under overflow it is what gets truncated.
_RENDERED_BLOCK_CHAR_LIMIT = 12_000


def _build_rendered_block(
    layout: RenderedLayoutIn, settings: TemplateSettingsIn
) -> str:
    """Render the measured-template context block for the LLM judge.

    The whole block (including the per-page mirror) is capped at
    ``_RENDERED_BLOCK_CHAR_LIMIT``; the mirror text takes the cut with the
    standard explicit-omission notice.
    """
    facts = _layout_facts(layout)
    facts["margins_mm"] = {
        "top": settings.margins.top,
        "bottom": settings.margins.bottom,
        "left": settings.margins.left,
        "right": settings.margins.right,
    }
    facts["compact_mode"] = settings.compactMode
    facts["warnings"] = list(layout.warnings)
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2)

    mirror = "\n\n".join(page.text for page in layout.page_mirror if page.text.strip())
    if not mirror:
        mirror = "（本次测量未生成逐页文本镜像）"

    # Probe the fixed overhead once with an empty mirror, then give the mirror
    # the remaining budget so the block never exceeds its cap.
    overhead = len(
        DIAGNOSIS_RENDERED_BLOCK.format(
            template=layout.template,
            page_size=layout.page_size,
            margins="0mm",
            layout_facts=facts_json,
            page_mirror="",
        )
    )
    mirror_budget = max(500, _RENDERED_BLOCK_CHAR_LIMIT - overhead)
    mirror = _truncate_text_for_prompt(mirror, mirror_budget)

    return DIAGNOSIS_RENDERED_BLOCK.format(
        template=layout.template,
        page_size=layout.page_size,
        margins=(
            f"上/下 {settings.margins.top}/{settings.margins.bottom}mm，"
            f"左/右 {settings.margins.left}/{settings.margins.right}mm"
        ),
        layout_facts=facts_json,
        page_mirror=mirror,
    )

# Public (standard-free) evidence shown when a prerequisite is missing.
_NA_WITHOUT_JD = "未提供目标岗位 JD，岗位匹配度检查项不适用。"
_NA_WITHOUT_MODEL = "未明确求职意向，或未匹配/选择对应职级的能力模型，专业能力项不适用。"


def _silence_conform_text(
    rating: str, evidence: str, suggestion: str
) -> tuple[str, str, str]:
    """Enforce "no problem, no description, no advice" on conforming items.

    Both the prompt and the deterministic checkers may still emit positive
    sentences (e.g. "实际顺序：…", 🟢/💡 tips); the report contract is that
    conforming rows carry neither a problem description nor a suggestion.
    """
    if rating == RATING_CONFORM:
        return rating, "", ""
    return rating, evidence, suggestion


# Source-carried point marker at the start of a line ("1. ", "1、", "1)",
# "(1)", circled digits, bullet glyphs, dashes). Mirrors the frontend
# stripPointMarker so the API never returns pre-numbered points.
_LEADING_POINT_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,2}\s*[.、)）．:：]"
    r"|[（(]\d{1,2}[)）]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"
    r"|[•·・●▪▸▹◆■\-—–]\s*"
    r")\s*"
)

# Another point glued into one line: a circled glyph anywhere, or an arabic
# marker right after sentence punctuation. The trailing char class excludes
# digits/punctuation so versions and decimals ("JDK 1.8", "2.0 平台",
# "提升到 2.5 倍") never split.
_GLUED_POINT_SPLIT_RE = re.compile(
    r"(?=[②③④⑤⑥⑦⑧⑨⑩])"
    r"|(?<=[；;。！？!?])\s*(?=\d{1,2}\s*[.、)．]\s*[^。．.、)）\s\d])"
)
# Inside a line the model clearly intended as a list (it started with one),
# whitespace before the next arabic marker also separates points.
_GLUED_POINT_SPLIT_LISTLINE_RE = re.compile(
    r"\s+(?=\d{1,2}\s*[.、)．]\s*[^。．.、)）\s\d])"
)


def normalize_finding_points(text: str) -> str:
    """Normalize an evidence/suggestion string into newline-separated points.

    The UI and the Word export render each finding as an ordered list, so the
    LLM is asked for one bare point per line; this deterministic pass also
    repairs legacy/weak-model formatting: source numbering and bullet glyphs
    are stripped per line, points glued onto one line ("a。2. b", "1. a 2. b",
    "①…②…") are split apart, and blank lines dropped. Plain prose and decimal
    numbers pass through untouched.
    """
    if not text or not text.strip():
        return ""
    points: list[str] = []
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if not line:
            continue
        list_line = bool(_LEADING_POINT_MARKER_RE.match(line))
        if list_line:
            line = _LEADING_POINT_MARKER_RE.sub("", line, count=1).strip()
        for piece in _GLUED_POINT_SPLIT_RE.split(line):
            piece = piece.strip()
            if list_line:
                # Further arabic markers separated only by whitespace.
                subpieces = _GLUED_POINT_SPLIT_LISTLINE_RE.split(piece)
            else:
                subpieces = [piece]
            for subpiece in subpieces:
                cleaned = _LEADING_POINT_MARKER_RE.sub("", subpiece.strip()).strip()
                # A point glued after a semicolon leaves that "；" dangling.
                cleaned = cleaned.rstrip("；; ").strip()
                if cleaned:
                    points.append(cleaned)
    return "\n".join(points)


def _resolve_target_title(resume_data: dict[str, Any], target_title: str | None) -> str | None:
    """Pick the diagnosis anchor title: explicit choice, else resume 求职意向."""
    if target_title and target_title.strip():
        return target_title.strip()
    info = resume_data.get("personalInfo")
    if isinstance(info, dict):
        title = info.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _prerequisite_ids(rules: Any, prerequisite: str) -> frozenset[int]:
    """Base item ids whose ``prerequisite`` metadata matches."""
    return frozenset(
        item_id
        for item_id, item in rules.items.items()
        if item.get("prerequisite") == prerequisite
    )


def _format_rubric_rows(item_ids: list[int], rules: Any) -> str:
    """Render assigned rubric items as the prompt's item table.

    The full criterion text and the QC 质检违规等级建议 guidance are rendered
    here (LLM-only); they never reach API clients or the Word export. The five
    专业能力 pointer rows carry no QC cell — their standards arrive through
    the matched competency model — so the QC line is omitted for them.
    """
    blocks: list[str] = []
    for item_id in item_ids:
        item = rules.item(item_id)
        location = item["dimension_name"]
        if item.get("sub_dimension"):
            location += f" / {item['sub_dimension']}"
        tag = " [红线·一票否决]" if item["severity"] == "redline" else ""
        block = (
            f"### {item_id}{tag}（{location}）\n"
            f"检查项：{item['criterion']}"
        )
        if item.get("qc"):
            block += f"\n质检违规等级建议：{item['qc']}"
        blocks.append(block)
    return "\n\n".join(blocks)


def _coerce_item_id(value: Any) -> int | None:
    """Coerce a checklist id to int; tolerant of ``"22"`` from weak models."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        token = value.strip()
        if token.isdigit():
            return int(token)
    return None


def _build_validator(expected_ids: frozenset[int]):
    """complete_json validator: enforce structure, tolerate model sloppiness.

    The judge model is allowed to:
    * omit assigned items (they default to partial with a warning downstream);
    * emit ids as numeric strings ("22" → 22);
    * answer ids outside the assigned set (objective/gated items owned
      elsewhere — such entries are dropped, never allowed to fail the call).

    Only a response with zero usable entries is rejected (triggers a retry).
    """

    def validate(result: dict[str, Any]) -> dict[str, Any]:
        items = result.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("diagnosis response has no items list")
        accepted: list[dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item_id = _coerce_item_id(entry.get("id"))
            if item_id is None or item_id not in expected_ids:
                logger.warning(
                    "Diagnosis LLM returned out-of-scope/invalid item id %r; dropped",
                    entry.get("id"),
                )
                continue
            if entry.get("rating") not in RATINGS:
                logger.warning(
                    "Diagnosis item %s has invalid rating %r; dropped",
                    item_id,
                    entry.get("rating"),
                )
                continue
            evidence = entry.get("evidence", "")
            suggestion = entry.get("suggestion", "")
            if not isinstance(evidence, str) or not isinstance(suggestion, str):
                logger.warning("Diagnosis item %s text fields invalid; dropped", item_id)
                continue
            if any(item["id"] == item_id for item in accepted):
                continue
            accepted.append(
                {"id": item_id, "rating": entry["rating"], "evidence": evidence, "suggestion": suggestion}
            )
        if not accepted:
            raise ValueError("diagnosis response has no usable items")
        return {**result, "items": accepted}

    return validate


def salvage_diagnosis_response(content: str) -> dict[str, Any] | None:
    """Recover complete item objects from a truncated diagnosis JSON.

    Weak local models sometimes emit EOS mid-array, leaving unbalanced braces
    that fail JSON parsing on every retry. Every COMPLETE ``{...}`` object
    inside the ``"items"`` array is still individually parseable; recover those
    and let the normal merge path mark the missing ones partial with a visible
    warning. Returns ``None`` when the fragment holds no complete item.
    """
    marker = content.find('"items"')
    if marker < 0:
        return None
    array_start = content.find("[", marker)
    if array_start < 0:
        return None

    recovered: list[dict[str, Any]] = []
    depth = 0
    in_string = False
    escaped = False
    object_start = -1
    segment = content[array_start + 1 :]
    for offset, char in enumerate(segment):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                object_start = array_start + 1 + offset
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and object_start >= 0:
                chunk = content[object_start : array_start + 1 + offset + 1]
                try:
                    parsed = json.loads(chunk)
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict):
                    recovered.append(parsed)
                object_start = -1

    if not recovered:
        return None
    logger.warning(
        "Salvaged %d complete item object(s) from a truncated diagnosis response",
        len(recovered),
    )
    return {"items": recovered}


def _build_skill_review_block(miss_keys: tuple[str, ...], skills: list[str]) -> str:
    """Render the item-7 semantic-review auxiliary task (regex misses only)."""
    groups_by_key = {group.key: group for group in _MAINSTREAM_GROUPS}
    group_lines = "\n".join(f"- {key}：{groups_by_key[key].equiv}" for key in miss_keys)
    # User text is passed as a format *value*, so its braces are inserted
    # verbatim and cannot be read as placeholders.
    skill_lines = "\n".join(f"- {skill}" for skill in skills)
    return DIAGNOSIS_SKILL_REVIEW_BLOCK.format(
        group_count=len(miss_keys),
        groups=group_lines,
        skills=skill_lines,
    )


# Quote verification: interior whitespace differences (line wraps, full/half
# width spaces collapsed) and case differences are tolerated; every other
# character must match a verbatim substring of a skill entry.
_QUOTE_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_quote_text(text: str) -> str:
    return _QUOTE_WHITESPACE_RE.sub(" ", text).strip().casefold()


def _verify_skill_group_review(
    review: Any, miss_keys: tuple[str, ...], skills: list[str]
) -> frozenset[str]:
    """Accept LLM rescues whose quote is a verbatim skill-entry substring.

    Only regex-missed groups may be rescued (never downgrade), and a rescue
    without a quote literally present in the 专业技能 entries is rejected —
    hallucinated grounding cannot flip the deterministic verdict.
    """
    if not isinstance(review, list):
        return frozenset()
    miss = set(miss_keys)
    normalized_entries = [_normalize_quote_text(skill) for skill in skills]
    rescued: set[str] = set()
    for entry in review:
        if not isinstance(entry, dict):
            continue
        key = entry.get("group")
        if not isinstance(key, str) or key not in miss or key in rescued:
            continue
        if entry.get("covered") is not True:
            continue
        quote = entry.get("quote")
        if not isinstance(quote, str) or not quote.strip():
            continue
        normalized_quote = _normalize_quote_text(quote)
        if any(
            normalized_quote and normalized_quote in entry_text
            for entry_text in normalized_entries
        ):
            rescued.add(key)
        else:
            logger.warning(
                "Diagnosis skill review: quote for %s is not a verbatim skill "
                "entry; rescue rejected: %r",
                key,
                quote[:80],
            )
    return frozenset(rescued)


async def _judge_with_llm(
    resume_data: dict[str, Any],
    facts: dict[str, Any],
    rules: Any,
    subjective_ids: list[int],
    job_description: str | None,
    target_title: str | None,
    competency_block: str,
    language: str,
    original_markdown: str | None = None,
    rendered_block: str = "",
    skill_review_block: str = "",
) -> tuple[dict[int, tuple[str, str, str]], Any]:
    """Call the LLM for subjective items.

    Returns (id -> (rating, evidence, tip), raw skill_group_review list).
    """
    job_block = ""
    if job_description:
        job_block = DIAGNOSIS_JOB_BLOCK.format(
            job_description=_truncate_text_for_prompt(
                job_description, _JOB_DESCRIPTION_CHAR_LIMIT
            )
        )
    target_block = (
        DIAGNOSIS_TARGET_BLOCK.format(target_title=target_title) if target_title else ""
    )
    original_block = ""
    if original_markdown and original_markdown.strip():
        original_block = DIAGNOSIS_ORIGINAL_BLOCK.format(
            original_resume=_truncate_text_for_prompt(
                original_markdown.strip(), _ORIGINAL_RESUME_CHAR_LIMIT
            )
        )
    prompt = DIAGNOSIS_PROMPT.format(
        item_ids=", ".join(str(i) for i in subjective_ids),
        rubric=_format_rubric_rows(subjective_ids, rules),
        facts=json.dumps(facts, ensure_ascii=False, indent=2),
        resume_data=_serialize_resume_data_for_prompt(resume_data),
        job_block=job_block,
        target_block=target_block,
        competency_block=competency_block,
        original_block=original_block,
        rendered_block=rendered_block,
        skill_review_block=skill_review_block,
        output_language=get_language_name(language),
    )
    config = get_llm_config()
    # Structured multi-item judging must not spend the output budget on hidden
    # reasoning: providers such as DeepSeek (deepseek-chat + reasoning_effort)
    # burn the whole token allowance on chain-of-thought and return empty
    # content (finish_reason="length", zero visible tokens). The rubric is
    # explicit and needs no reasoning trace, so drop the globally configured
    # effort for this call only. ``getattr`` keeps duck-typed test doubles
    # working; the global LLMConfig is never mutated.
    if getattr(config, "reasoning_effort", None) is not None:
        config = config.model_copy(update={"reasoning_effort": None})
    max_tokens = get_safe_max_tokens(get_model_name(config), requested=12000, config=config)
    result = await complete_json(
        prompt=prompt,
        system_prompt=DIAGNOSIS_SYSTEM_PROMPT,
        config=config,
        max_tokens=max_tokens,
        schema_type="diagnosis",
        response_validator=_build_validator(frozenset(subjective_ids)),
        salvage_response=salvage_diagnosis_response,
    )
    verdicts: dict[int, tuple[str, str, str]] = {}
    for entry in result.get("items", []):
        item_id = int(entry["id"])
        if item_id in verdicts:
            continue
        rating, evidence, suggestion = _silence_conform_text(
            str(entry["rating"]),
            str(entry.get("evidence") or "").strip(),
            str(entry.get("suggestion") or "").strip(),
        )
        verdicts[item_id] = (rating, evidence, suggestion)
    return verdicts, result.get("skill_group_review")


async def diagnose_resume(
    resume_data: dict[str, Any],
    *,
    resume_id: str,
    job_description: str | None = None,
    target_title: str | None = None,
    competency_model_key: str | None = None,
    language: str | None = None,
    original_markdown: str | None = None,
    template_settings: TemplateSettingsIn | None = None,
    rendered_layout: RenderedLayoutIn | None = None,
) -> DiagnosisReport:
    """Run the full diagnosis pipeline and return the checklist report.

    ``original_markdown`` is the user's uploaded resume verbatim (parser
    input). It grounds content-level facts for the LLM judge; module
    organization (which module an entry belongs to, whether an optional
    module exists / is empty, duplication in the finished resume) is
    authoritative in ``resume_data`` plus the objective facts packet — the
    raw upload may group entries under catch-all headings such as 「其他」
    that parsing has since regrouped. Deterministic checks stay on the
    structured data, except the #16 privacy scan, which covers both.

    ``template_settings`` + ``rendered_layout`` are the builder's chosen
    template and a browser-measured render of the resume in that template.
    When the snapshot passes the usability gates, items 1/2 judge measured
    pagination and the LLM receives a per-page rendered-text block.
    """
    language = language or get_content_language()
    base_rules = get_rules()

    resolved_title = _resolve_target_title(resume_data, target_title)
    # Explicit user pick wins (req: confirm/choose when no intention or no
    # automatic title match); KeyError on an unknown key maps to HTTP 400.
    model = resolve_competency_model(
        parse_competency_models(base_rules.competency_models),
        resolved_title,
        competency_model_key,
    )
    rules = expand_rules(base_rules, model)

    # Prerequisite-gated item groups (single source: rules artifact metadata).
    jd_gated_ids = _prerequisite_ids(rules, "jd")
    competence_ids = frozenset(
        item_id
        for item_id, item in rules.items.items()
        if item["dimension"] == COMPETENCE_DIMENSION_KEY
    )

    objective_verdicts, facts = run_objective_checks(
        resume_data,
        supplementary_text=original_markdown,
        rendered_layout=rendered_layout,
        template_settings=template_settings,
    )
    facts["target_title"] = resolved_title
    objective_ids = set(objective_verdicts)

    def _supported(item_id: int) -> bool:
        # Item 17 requires a target JD. Items 18–22 independently require a
        # resolved level model (clear 求职意向); they no longer need a JD.
        if not job_description and item_id in jd_gated_ids:
            return False
        if model is None and item_id in competence_ids:
            return False
        return True

    # Subjective items = everything the deterministic layer did not answer and
    # the current context can actually support.
    subjective_ids = sorted(
        item_id
        for item_id in rules.items
        if item_id not in objective_ids and _supported(item_id)
    )

    competency_block = ""
    if model is not None:
        competency_block = DIAGNOSIS_COMPETENCY_BLOCK.format(model_name=model.name)

    # Re-derive usability with the same gates run_objective_checks applied:
    # an unusable snapshot must not reach the LLM prompt at all.
    usable_layout = _usable_layout(rendered_layout, template_settings)
    rendered_block = ""
    if usable_layout is not None and template_settings is not None:
        rendered_block = _build_rendered_block(usable_layout, template_settings)

    # Item 7 semantic review: the deterministic regex pass may miss synonym
    # coverage (MyBatis for RDBMS, Copilot for AI coding tools). Ride the
    # single judge call that is already happening — never make a separate LLM
    # call for it (no subjective items → the regex verdict stands unchanged).
    # A conforming stack needs no rescue.
    skill_entries = technical_skill_entries(resume_data)
    skill_hit_keys, skill_miss_keys = mainstream_stack_coverage(skill_entries)
    skill_review_block = ""
    skill_review_requested = bool(
        skill_entries
        and subjective_ids
        and len(skill_hit_keys) / len(_MAINSTREAM_GROUPS) < _STACK_CONFORM_RATIO
    )
    if skill_review_requested:
        skill_review_block = _build_skill_review_block(skill_miss_keys, skill_entries)

    llm_verdicts, raw_skill_review = await _judge_with_llm(
        resume_data,
        facts,
        rules,
        subjective_ids,
        job_description,
        resolved_title,
        competency_block,
        language,
        original_markdown,
        rendered_block,
        skill_review_block,
    )
    rescued_skill_groups: frozenset[str] = frozenset()
    if skill_review_requested:
        rescued_skill_groups = _verify_skill_group_review(
            raw_skill_review, skill_miss_keys, skill_entries
        )

    warnings: list[str] = []
    merged: dict[int, dict[str, str]] = {}
    # Objective items whose final verdict involved the LLM semantic review.
    semantic_method_ids: set[int] = set()

    for item_id, (rating, evidence, suggestion) in objective_verdicts.items():
        rating, evidence, suggestion = _silence_conform_text(
            rating, evidence, suggestion
        )
        merged[item_id] = {"rating": rating, "evidence": evidence, "suggestion": suggestion}

    if rescued_skill_groups:
        # Rebuild item 7 with the groups rescued by the verified LLM review;
        # skill-count findings and their text stay untouched.
        rescued_hit_keys = tuple(
            group.key
            for group in _MAINSTREAM_GROUPS
            if group.key in skill_hit_keys or group.key in rescued_skill_groups
        )
        rebuilt = _join_findings(
            [
                _check_skill_count(resume_data),
                build_mainstream_stack_finding(rescued_hit_keys),
            ]
        )
        rating, evidence, suggestion = _silence_conform_text(*rebuilt)
        merged[7] = {"rating": rating, "evidence": evidence, "suggestion": suggestion}
        semantic_method_ids.add(7)

    for item_id in subjective_ids:
        if item_id in llm_verdicts:
            rating, evidence, suggestion = llm_verdicts[item_id]
            merged[item_id] = {"rating": rating, "evidence": evidence, "suggestion": suggestion}
        else:
            logger.warning("Diagnosis item %s missing from LLM response; defaulting partial", item_id)
            warnings.append(f"检查项 {item_id} 未获得 AI 评级，默认部分符合，请人工复核")
            merged[item_id] = {
                "rating": RATING_PARTIAL,
                "evidence": "AI 未返回该项评级，默认部分符合，请人工复核",
                "suggestion": "",
            }

    # Prerequisite gaps: explicitly not applicable (never silent gaps). The
    # JD gate (item 17) and the intention/model gate (items 18–22) are
    # independent in the V4 rubric.
    if not job_description:
        for item_id in jd_gated_ids:
            merged.setdefault(
                item_id, {"rating": RATING_NA, "evidence": _NA_WITHOUT_JD, "suggestion": ""}
            )
    if model is None:
        for item_id in competence_ids:
            merged.setdefault(
                item_id, {"rating": RATING_NA, "evidence": _NA_WITHOUT_MODEL, "suggestion": ""}
            )

    missing = sorted(set(rules.items) - set(merged))
    if missing:
        # Defensive: every rubric item must always have a verdict.
        logger.error("Diagnosis produced no verdict for items %s", missing)
        for item_id in missing:
            merged[item_id] = {
                "rating": RATING_NA,
                "evidence": "该项本次未能评估，暂列不适用，请人工复核。",
                "suggestion": "",
            }

    simple_verdicts = {
        item_id: (entry["rating"], entry["evidence"]) for item_id, entry in merged.items()
    }
    summary = summarize_verdicts(simple_verdicts, rules=rules)

    items = [
        DiagnosisItemResult(
            id=item_id,
            dimension=item["dimension"],
            dimension_name=item["dimension_name"],
            sub_dimension=item["sub_dimension"],
            topic=item["topic"],
            severity=item["severity"],  # type: ignore[arg-type]
            judgment_method=(
                "subjective"
                if item_id in semantic_method_ids or item_id not in objective_ids
                else "objective"
            ),
            rating=merged[item_id]["rating"],  # type: ignore[arg-type]
            evidence=normalize_finding_points(merged[item_id]["evidence"]),
            suggestion=normalize_finding_points(merged[item_id]["suggestion"]),
        )
        for item_id, item in sorted(rules.items.items())
    ]

    redlines = [
        RedLineStatus(
            id=item_id,
            topic=rules.item(item_id)["topic"],
            passed=item_id not in summary["failed_redline_ids"],
            rating=merged[item_id]["rating"],  # type: ignore[arg-type]
            evidence=normalize_finding_points(merged[item_id]["evidence"]),
            suggestion=normalize_finding_points(merged[item_id]["suggestion"]),
        )
        for item_id in rules.redline_ids
    ]

    return DiagnosisReport(
        resume_id=resume_id,
        spec_version=rules.spec_version,
        language=language,
        target_title=resolved_title,
        competency_model=(
            CompetencyModelInfo(key=model.key, name=model.name) if model is not None else None
        ),
        counts=RatingCounts(**summary["counts"]),
        redline_passed=summary["redline_passed"],
        failed_redline_ids=summary["failed_redline_ids"],
        dimensions=[DimensionResult(**dim) for dim in summary["dimensions"]],
        redlines=redlines,
        items=items,
        warnings=warnings,
    )
