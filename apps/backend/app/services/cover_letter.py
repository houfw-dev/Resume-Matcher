"""Cover letter, outreach message, and resume title generation service."""

import json
import logging
import re
from typing import Any, Mapping

from app.ai_limits import MAX_JOB_CHARACTERS, validate_source_size
from app.config import load_config_file
from app.llm import complete
from app.prompts.templates import (
    COVER_LETTER_NO_JD_PROMPT,
    COVER_LETTER_PROMPT,
    GENERATE_TITLE_PROMPT,
    GENERATE_TITLE_STRICT_REMINDER,
    OUTREACH_MESSAGE_PROMPT,
    OUTREACH_NO_JD_PROMPT,
)
from app.prompts import get_language_name


def _resolve_feature_prompt(
    custom_key: str,
    default_template: str,
) -> tuple[str, bool]:
    """Resolve a feature-prompt template at runtime.

    Returns ``(template, is_custom)``. If the stored custom prompt is
    empty or absent, returns the default template. The ``is_custom`` flag
    lets callers decide whether to fall back to the default on a format
    failure (defensive — save-time validation should have caught a
    malformed custom prompt).
    """
    stored = load_config_file()
    custom = (stored.get(custom_key) or "").strip()
    if not custom:
        return default_template, False
    return custom, True


async def _generate_cover_letter_without_jd(
    resume_data: dict[str, Any],
    output_language: str,
) -> str:
    """Generate a resume-only cover letter when no job description is given.

    Custom feature prompts always require a ``{job_description}`` placeholder,
    so this path uses the built-in no-JD template exclusively.
    """
    prompt = COVER_LETTER_NO_JD_PROMPT.format(
        resume_data=json.dumps(resume_data),
        output_language=output_language,
    )
    result = await complete(
        prompt=prompt,
        system_prompt="You are a professional career coach and resume writer. Write compelling, personalized cover letters.",
        max_tokens=2048,
    )
    return result.strip()


async def generate_cover_letter(
    resume_data: dict[str, Any],
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a cover letter based on resume and optional job description.

    Args:
        resume_data: Structured resume data (ResumeData format)
        job_description: Target job description text; an empty/whitespace
            string produces a resume-only cover letter
        language: Output language code (en, es, zh, ja)

    Returns:
        Generated cover letter as plain text
    """
    output_language = get_language_name(language)

    if not job_description or not job_description.strip():
        return await _generate_cover_letter_without_jd(
            resume_data, output_language
        )

    validate_source_size(job_description, MAX_JOB_CHARACTERS)

    template, is_custom = _resolve_feature_prompt(
        "cover_letter_prompt", COVER_LETTER_PROMPT
    )
    try:
        prompt = template.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )
    except (KeyError, IndexError, ValueError) as e:
        # str.format() raises KeyError for unknown placeholders, IndexError for
        # positional out-of-range, and ValueError for unmatched/invalid braces
        # (e.g., ``{foo``). If the failing template is the built-in default,
        # something is broken upstream and the caller should see it — re-raise.
        # If it's a user-supplied custom prompt, fall back to the default with a
        # warning so generation doesn't crash on out-of-band disk edits.
        if not is_custom:
            raise
        logging.warning(
            "Custom cover letter prompt failed to format (%s); falling back to default",
            e,
        )
        prompt = COVER_LETTER_PROMPT.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )

    result = await complete(
        prompt=prompt,
        system_prompt="You are a professional career coach and resume writer. Write compelling, personalized cover letters.",
        max_tokens=2048,
    )

    return result.strip()


async def _generate_outreach_without_jd(
    resume_data: dict[str, Any],
    output_language: str,
) -> str:
    """Generate a resume-only outreach message when no job description is given.

    Custom feature prompts always require a ``{job_description}`` placeholder,
    so this path uses the built-in no-JD template exclusively.
    """
    prompt = OUTREACH_NO_JD_PROMPT.format(
        resume_data=json.dumps(resume_data),
        output_language=output_language,
    )
    result = await complete(
        prompt=prompt,
        system_prompt="You are a professional networking coach. Write genuine, engaging cold outreach messages.",
        max_tokens=1024,
    )
    return result.strip()


async def generate_outreach_message(
    resume_data: dict[str, Any],
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a cold outreach message for networking.

    Args:
        resume_data: Structured resume data (ResumeData format)
        job_description: Target job description text; an empty/whitespace
            string produces a resume-only general-purpose message
        language: Output language code (en, es, zh, ja)

    Returns:
        Generated outreach message as plain text
    """
    output_language = get_language_name(language)

    if not job_description or not job_description.strip():
        return await _generate_outreach_without_jd(resume_data, output_language)

    validate_source_size(job_description, MAX_JOB_CHARACTERS)

    template, is_custom = _resolve_feature_prompt(
        "outreach_message_prompt", OUTREACH_MESSAGE_PROMPT
    )
    try:
        prompt = template.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )
    except (KeyError, IndexError, ValueError) as e:
        # See generate_cover_letter for rationale on the exception set.
        if not is_custom:
            raise
        logging.warning(
            "Custom outreach message prompt failed to format (%s); falling back to default",
            e,
        )
        prompt = OUTREACH_MESSAGE_PROMPT.format(
            job_description=job_description,
            resume_data=json.dumps(resume_data),
            output_language=output_language,
        )

    result = await complete(
        prompt=prompt,
        system_prompt="You are a professional networking coach. Write genuine, engaging cold outreach messages.",
        max_tokens=1024,
    )

    return result.strip()


# Reasoning-style models sometimes answer with a paraphrase of the request
# ("The user wants extraction of job title and company name…") instead of the
# title itself; under the small 60-token budget the preamble can consume the
# whole response. Detect those outputs so they never get stored as a title.
_TITLE_PREAMBLE_RE = re.compile(
    r"^(the user|i need|i will|i'll|let me|sure|okay|ok|certainly|"
    r"用户|我需要|我将|请提取|请根据|以下是|下面是|好的|标题[是为：:])",
    re.IGNORECASE,
)
_TITLE_PROMPT_ECHO_RE = re.compile(
    r"(job title and company name|extract(?:ion)? (?:of )?job title)",
    re.IGNORECASE,
)
_TITLE_HARD_LIMIT = 80
_TITLE_QUOTE_CHARS = "\"'“”‘’`"

# Last-resort titles when the model returns preamble twice; keyed by the same
# content-language codes used across every generative prompt.
_FALLBACK_TITLES: dict[str, str] = {
    "en": "Tailored Resume",
    "es": "Currículum personalizado",
    "zh": "定制简历",
    "ja": "カスタマイズ履歴書",
    "pt": "Currículo personalizado",
    "fr": "CV personnalisé",
    "ko": "맞춤 이력서",
}


def _clean_title_line(raw: str) -> str:
    """Normalize one model output line into a bare title string."""
    return raw.strip().strip(_TITLE_QUOTE_CHARS).strip()


def _is_valid_title(text: str) -> bool:
    """Return True only for a one-line title with no task-paraphrase preamble."""
    if not text or "\n" in text or len(text) > _TITLE_HARD_LIMIT:
        return False
    if _TITLE_PREAMBLE_RE.match(text) or _TITLE_PROMPT_ECHO_RE.search(text):
        return False
    return True


def _extract_title_candidate(raw: str) -> str:
    """Pull a title candidate out of a model response.

    A well-behaved model returns one line. If it wraps the title in
    commentary, salvage the first line that itself passes title validation;
    otherwise return the last non-empty line so the caller's retry logic
    decides what to do.
    """
    stripped = raw.strip()
    if "\n" not in stripped:
        return _clean_title_line(stripped)
    lines = [_clean_title_line(line) for line in stripped.splitlines()]
    lines = [line for line in lines if line]
    for line in lines:
        if _is_valid_title(line):
            return line
    return lines[-1] if lines else ""


_TITLE_WHITESPACE_RE = re.compile(r"\s+")
# 求职意向 sometimes enumerates several targets ("Java 开发/资深开发/技术经理").
_TITLE_TARGET_SPLIT_RE = re.compile(r"[/／]")


def _clean_title_fact(value: Any) -> str:
    """Normalize one title fact: collapse whitespace, drop blanks."""
    if not isinstance(value, str):
        return ""
    return _TITLE_WHITESPACE_RE.sub(" ", value).strip()


def build_resume_title(
    improved_data: Mapping[str, Any],
    job_keywords: Mapping[str, Any] | None,
    language: str = "en",
) -> str:
    """Build the deterministic tailored-resume title ``姓名-岗位名称``.

    The title is derived without an LLM call so model prompt-echo text (e.g.
    "Max 60 chars. Output one line.") can never be stored as a resume title.
    The position name prefers the role extracted from the target job
    description — each tailored resume targets one job — falling back to the
    resume's own ``personalInfo.title`` 求职意向, whose first slash-separated
    segment is the primary target. When neither fact exists, the localized
    generic title is returned.

    Args:
        improved_data: Tailored resume mapping with ``personalInfo.name`` and
            optional ``personalInfo.title``.
        job_keywords: Cached job-keyword extraction with an optional ``role``.
        language: Content-language code used for the last-resort fallback.

    Returns:
        A one-line title no longer than ``_TITLE_HARD_LIMIT`` characters.
    """
    personal: Mapping[str, Any] = {}
    if isinstance(improved_data, Mapping):
        candidate = improved_data.get("personalInfo")
        if isinstance(candidate, Mapping):
            personal = candidate

    name = _clean_title_fact(personal.get("name"))

    role = ""
    if isinstance(job_keywords, Mapping):
        role = _clean_title_fact(job_keywords.get("role"))
    if not role:
        own_target = _clean_title_fact(personal.get("title"))
        if own_target:
            role = _TITLE_TARGET_SPLIT_RE.split(own_target, 1)[0].strip()

    facts = [fact for fact in (name, role) if fact]
    if facts:
        title = "-".join(facts)
    else:
        title = _FALLBACK_TITLES.get(language, _FALLBACK_TITLES["en"])
    # Python slices by code point, so CJK titles truncate cleanly; trim any
    # dash or space left dangling by the cut.
    return title[:_TITLE_HARD_LIMIT].strip(" -")


async def generate_resume_title(
    job_description: str,
    language: str = "en",
) -> str:
    """Generate a short descriptive title from a job description.

    The output is validated: a request-paraphrase preamble (observed on
    reasoning-style OpenAI-compatible models) triggers one strict retry, and
    a second failure falls back to a localized generic title so callers never
    persist commentary text as the resume title.

    Args:
        job_description: Target job description text
        language: Output language code (en, es, zh, ja, pt, fr, ko)

    Returns:
        Generated title like "Senior Frontend Engineer @ Stripe"
    """
    validate_source_size(job_description, MAX_JOB_CHARACTERS)
    output_language = get_language_name(language)

    prompt = GENERATE_TITLE_PROMPT.format(
        job_description=job_description,
        output_language=output_language,
    )
    system_prompt = (
        "You extract job titles and company names from job descriptions."
    )

    result = await complete(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=60,
        temperature=0.3,
    )
    title = _extract_title_candidate(result)
    if _is_valid_title(title):
        return title[:_TITLE_HARD_LIMIT]

    logging.warning(
        "Title output failed validation (%r); retrying with strict reminder",
        result[:120],
    )
    retry_result = await complete(
        prompt=prompt
        + GENERATE_TITLE_STRICT_REMINDER.format(output_language=output_language),
        system_prompt=system_prompt,
        # A larger budget lets a model that emits a short preamble still reach
        # the actual title within a single response.
        max_tokens=120,
        temperature=0.0,
    )
    retry_title = _extract_title_candidate(retry_result)
    if _is_valid_title(retry_title):
        return retry_title[:_TITLE_HARD_LIMIT]

    logging.error(
        "Title retry still failed validation (%r); using localized fallback",
        retry_result[:120],
    )
    return _FALLBACK_TITLES.get(language, _FALLBACK_TITLES["en"])
