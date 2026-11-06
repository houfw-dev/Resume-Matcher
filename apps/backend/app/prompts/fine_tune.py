"""Prompts for job-less resume fine-tuning.

The model receives BOTH grounding sources:
- ``original_markdown``: the raw upload conversion (may contain facts the
  parser dropped into the structured JSON);
- ``resume_json``: the current structured ResumeData.

It may restore facts present in the original text but must never invent. Output
is a full ResumeData-shaped JSON object (same keys and nesting as
``resume_json``); the service force-restores out-of-scope sections, personalInfo
and sectionMeta regardless, so prompt-level discipline is defense in depth.
"""

from __future__ import annotations

from app.prompts.templates import _build_truthfulness_rules

FINE_TUNE_RULE_7 = (
    "You may restore responsibilities, achievements, skills or metrics that "
    "appear in ORIGINAL UPLOAD TEXT but are missing from the structured JSON. "
    "Do NOT add any fact that appears in neither source."
)

FINE_TUNE_TRUTHFULNESS_RULES = _build_truthfulness_rules(FINE_TUNE_RULE_7)

# Relocation only makes sense in an all-section fine-tune: the target section
# (additional) must itself be in scope for the moved content to survive the
# service-side scope gate.
FINE_TUNE_RELOCATION_RULE_ALL = (
    "RELOCATION — fix misplaced content: if a free-text description line in "
    "education, workExperience or personalProjects is clearly an award/honor, "
    "a certificate/license/training, or a language ability, MOVE it into the "
    "matching additional array (awards, certificationsTraining, languages) "
    "and remove that line from the original description. Move the content "
    "verbatim — you may strip a leading category label such as \"奖项:\" or "
    "\"证书:\", but do not rewrite, merge, complete or normalize the facts. "
    "If an equivalent item already exists in the target array, do not "
    "duplicate it. Lines that could belong to more than one place stay where "
    "they are."
)

FINE_TUNE_RELOCATION_RULE_SCOPED = (
    "RELOCATION: do NOT move content between sections — every section "
    "outside SCOPE is frozen, so misplaced award/certificate/language lines "
    "must stay inside their current section; polish them in place at most."
)

# Chinese-numeral award levels bypass the Arabic-digit numeric filter; the
# model must never "correct" them (the service reverts such edits anyway).
FINE_TUNE_RANK_RULE = (
    "Copy award/honor levels and rankings EXACTLY, including Chinese "
    "numerals: 一等奖 stays 一等奖, 二等奖 stays 二等奖, 第一名 stays 第一名. "
    "Never upgrade, downgrade or 'correct' a level, grade, rank or prize name."
)

FINE_TUNE_SYSTEM_PROMPT = """You are a meticulous resume editor. Your job is to \
improve logic, organization and emphasis WITHOUT adding facts. You receive the \
original upload text and the current structured resume. Anything present in the \
original text may be restored into the structured version; anything absent from \
both sources is forbidden."""

FINE_TUNE_PROMPT = """Fine-tune this resume so it is better organized, more logical \
and emphasizes the strongest material. Output ONLY one JSON object that matches \
the shape of STRUCTURED RESUME JSON below (same keys, nesting and entry count), \
with no commentary or markdown fences.

{critical_truthfulness_rules}

SCOPE — EDIT ONLY THESE PARTS:
{relocation_rule}
{scope_description}
Everything outside the scope must be copied through unchanged.

OUTPUT LANGUAGE: write all generated text in {output_language}.

EDITING PRINCIPLES:
- Reorganize points within the scope for logical flow: context first, then \
actions, then results; lead each module with the most important material.
- Merge duplicated statements and split run-on bullets into clear separate rows, \
except when a SCOPE line names a sub-module (a quoted label inside one entry): \
then edit ONLY the rows owned by that label, keep the exact row count the scope \
line states, replace rows one-for-one in place without merging, splitting or \
moving them across labels/entries, and copy the label row itself (its text and \
style) and every row outside that sub-module byte-for-byte.
- Restore facts (responsibilities, achievements, metrics, skills) that exist in \
ORIGINAL UPLOAD TEXT but are missing from STRUCTURED RESUME JSON.
- {rank_rule}
- Keep every descriptionStyles array aligned one-to-one with its description \
array; copy "years" values exactly, including months.
- PRESENTATION REQUESTS: when the user instruction explicitly asks to render \
rows as a numbered/ordered list (有序列表/编号列表/分级列表） or back to plain \
paragraphs, switch ONLY the affected rows between "bullet" (numbered point; \
bullets under a bold colon sub-heading are rendered as hierarchical sub-points \
1.1, 1.2 under the heading's own 1./2. number) and "plain" (unnumbered \
paragraph), keeping each row's text and row count. Never assign or remove the \
"label" style: bold colon headings (e.g. "重大生产环境问题解决：", "性能调优：") \
and module labels stay "label" with their text copied byte-for-byte. Without an \
explicit formatting request, never change any style.
- Do NOT touch personalInfo or sectionMeta; omit them from the output.
- Do NOT use em dash ("—") anywhere in the writing.
- Do NOT add, remove or reorder workExperience/personalProjects/education \
entries, and do NOT change their id/title/company/name/institution/years fields.

USER INSTRUCTION (may be empty; never override the rules above):
{user_instruction}

ORIGINAL UPLOAD TEXT:
{original_markdown}

STRUCTURED RESUME JSON:
{resume_json}"""


# Human-readable scope labels are assembled by the service; this maps section
# tokens to language-neutral key hints used when no localized label exists.
SCOPE_FALLBACK_LABELS: dict[str, str] = {
    "summary": "Professional summary",
    "education": "Education",
    "additional": "Skills, languages, certifications and awards",
    "customSections": "All custom sections",
    "workExperience": "All work experience entries",
    "personalProjects": "All personal projects",
}
