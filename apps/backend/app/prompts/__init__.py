"""LLM prompt templates."""

from app.prompts.templates import (
    CRITICAL_TRUTHFULNESS_RULES,
    DEFAULT_IMPROVE_PROMPT_ID,
    DIFF_IMPROVE_PROMPT,
    DIFF_STRATEGY_INSTRUCTIONS,
    EXTRACT_KEYWORDS_PROMPT,
    GENERATE_TITLE_PROMPT,
    IMPROVE_PROMPT_OPTIONS,
    IMPROVE_RESUME_PROMPT,
    IMPROVE_RESUME_PROMPTS,
    INTERVIEW_PREP_NO_JD_PROMPT,
    INTERVIEW_PREP_PROMPT,
    OUTREACH_NO_JD_PROMPT,
    PARSE_RESUME_PROMPT,
    SKILL_TARGET_PLAN_PROMPT,
    get_language_name,
)

# Placeholders every user-supplied cover-letter / outreach prompt must contain.
# These correspond to the ``.format()`` keys used by the services in
# ``app/services/cover_letter.py``. Validated at save time so a 422 surfaces
# immediately instead of a ``KeyError`` during generation.
REQUIRED_FEATURE_PROMPT_PLACEHOLDERS: tuple[str, ...] = (
    "{job_description}",
    "{resume_data}",
    "{output_language}",
)

# Placeholders every user-supplied resume-parse prompt must contain. They match
# the ``.format()`` keys in parser.parse_resume_to_json; deliberately a
# separate tuple — the parse prompt has no JD/output-language slots.
PARSE_REQUIRED_PLACEHOLDERS: tuple[str, ...] = ("{schema}", "{resume_text}")


def validate_prompt_placeholders(
    prompt: str,
    required: tuple[str, ...] = REQUIRED_FEATURE_PROMPT_PLACEHOLDERS,
) -> list[str]:
    """Return required placeholders missing from ``prompt``.

    Empty or whitespace-only prompts are treated as "use default" and return
    an empty list (valid — the router treats them as clearing the override).
    Non-empty prompts must include every entry from ``required`` (the
    cover-letter/outreach set by default; pass ``PARSE_REQUIRED_PLACEHOLDERS``
    for the resume-parse prompt).
    """
    if not prompt or not prompt.strip():
        return []
    return [p for p in required if p not in prompt]


__all__ = [
    "PARSE_RESUME_PROMPT",
    "EXTRACT_KEYWORDS_PROMPT",
    "IMPROVE_RESUME_PROMPT",
    "IMPROVE_RESUME_PROMPTS",
    "IMPROVE_PROMPT_OPTIONS",
    "DEFAULT_IMPROVE_PROMPT_ID",
    "CRITICAL_TRUTHFULNESS_RULES",
    "DIFF_IMPROVE_PROMPT",
    "DIFF_STRATEGY_INSTRUCTIONS",
    "SKILL_TARGET_PLAN_PROMPT",
    "GENERATE_TITLE_PROMPT",
    "INTERVIEW_PREP_PROMPT",
    "INTERVIEW_PREP_NO_JD_PROMPT",
    "OUTREACH_NO_JD_PROMPT",
    "REQUIRED_FEATURE_PROMPT_PLACEHOLDERS",
    "PARSE_REQUIRED_PLACEHOLDERS",
    "validate_prompt_placeholders",
    "get_language_name",
]
