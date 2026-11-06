"""Content guards on the tailoring prompts.

Two invariants this locks:
1. JD-keyword incorporation is the DEFAULT across sections (the maintainer goal).
2. The anti-fabrication clauses stay present. Deterministic final-output
   preservation handles structural loss and unsupported metrics, while weakly
   grounded narrative is held for explicit review. These prompt clauses remain
   the model-facing first layer and should not regress.
"""

from app.prompts.templates import (
    COVER_LETTER_PROMPT,
    DIFF_IMPROVE_PROMPT,
    INTERVIEW_PREP_PROMPT,
    SKILL_TARGET_PLAN_PROMPT,
)
from app.prompts.refinement import KEYWORD_INJECTION_PROMPT


class TestSkillTargetPlannerPromptIsJsonFirst:
    """A verbose prose-brief planner prompt made DeepSeek emit chain-of-thought
    instead of JSON even in json_object mode; the router swallowed the parse
    failure, passed an empty allow-list, and the preview modal showed all-zero
    change counts. Lock the JSON-first imperative shape."""

    def test_planner_demands_raw_json_only(self):
        assert "Return ONLY a raw JSON object" in SKILL_TARGET_PLAN_PROMPT

    def test_planner_rules_are_terse_not_prose_paragraphs(self):
        # Each non-empty line before the JSON example stays short; a wall of
        # wrapped prose is what switched the model into reasoning-text mode.
        header = SKILL_TARGET_PLAN_PROMPT.split("Output this exact JSON format")[0]
        long_lines = [
            line
            for line in header.splitlines()
            if line.strip() and len(line) > 320
        ]
        assert long_lines == []

    def test_planner_keeps_any_form_dedup_instruction(self):
        assert "ANY form" in SKILL_TARGET_PLAN_PROMPT


class TestJdIncorporationIsDefault:
    def test_diff_prompt_reframes_by_default(self):
        assert "By DEFAULT" in DIFF_IMPROVE_PROMPT
        assert "reframe" in DIFF_IMPROVE_PROMPT.lower()

    def test_keyword_injection_targets_every_section_by_default(self):
        assert "EVERY section" in KEYWORD_INJECTION_PROMPT
        assert "DEFAULT" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_reframes_in_jd_terminology(self):
        assert "terminology" in COVER_LETTER_PROMPT.lower()


class TestAntiFabricationClausesPresent:
    def test_diff_prompt_keeps_no_invented_work_clauses(self):
        # rule 11's reframe permission must ship WITH its anti-fabrication clause
        assert "Do NOT add new work, metrics, or responsibilities" in DIFF_IMPROVE_PROMPT
        # rule 2 must remain
        assert "Do not invent metrics or achievements not supported by the original resume" in DIFF_IMPROVE_PROMPT

    def test_keyword_injection_keeps_no_invent_clauses(self):
        assert "do not invent new content, metrics, or work history" in KEYWORD_INJECTION_PROMPT
        assert "Do NOT add skills, technologies, or certifications not in the master resume" in KEYWORD_INJECTION_PROMPT

    def test_cover_letter_keeps_no_invent_clauses(self):
        assert "Do NOT invent information not in the resume" in COVER_LETTER_PROMPT
        assert "proven experience supports it" in COVER_LETTER_PROMPT

    def test_interview_prep_keeps_no_fabrication_guardrails(self):
        assert "Do NOT invent experience" in INTERVIEW_PREP_PROMPT
        assert "tools, employers, metrics, certifications, skills" in INTERVIEW_PREP_PROMPT
        assert "Skill gaps are preparation targets only" in INTERVIEW_PREP_PROMPT
        assert "Do NOT translate JSON property names" in INTERVIEW_PREP_PROMPT
        assert "role_fit_analysis" in INTERVIEW_PREP_PROMPT
        assert "talking_points" in INTERVIEW_PREP_PROMPT
