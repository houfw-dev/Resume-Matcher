"""Content locks for the resume-parse prompt and its JSON schema example.

The upload parser maps free-form Chinese headings (个人优势 / 自我评价 / 专业技能 /
荣誉证书) onto fixed data slots. The mapping lives in the prompt text itself, so
these substring/structure tests fail if a prompt edit silently re-merges
sections, drops the required sectionMeta, collapses source lines, or weakens the
project-field rules that diagnosis item 9 relies on.
"""

import json
import re

from app.prompts.templates import PARSE_RESUME_PROMPT, RESUME_SCHEMA_EXAMPLE


def _formatted_prompt() -> str:
    return PARSE_RESUME_PROMPT.format(
        schema=RESUME_SCHEMA_EXAMPLE, resume_text="个人优势\n沟通能力强"
    )


def test_prompt_formats_with_schema_and_resume() -> None:
    rendered = _formatted_prompt()
    assert "sectionMeta" in rendered
    assert rendered.rstrip().endswith("个人优势\n沟通能力强")


class TestSchemaExample:
    def test_example_is_valid_json(self) -> None:
        data = json.loads(RESUME_SCHEMA_EXAMPLE)
        assert isinstance(data, dict)

    def test_personal_info_has_header_demographic_fields(self) -> None:
        data = json.loads(RESUME_SCHEMA_EXAMPLE)
        info = data["personalInfo"]
        for field in ("gender", "age", "workYears", "educationLevel"):
            assert field in info
        # the example leaves them blank: they are optional, never invented
        assert info["gender"] == ""
        assert info["age"] == ""
        assert info["workYears"] == ""
        assert info["educationLevel"] == ""

    def test_honors_go_to_additional_and_selfeval_is_custom(self) -> None:
        data = json.loads(RESUME_SCHEMA_EXAMPLE)
        custom = data["customSections"]
        # self evaluation stays a dedicated custom text block; honors no longer
        # get a custom section — they populate the two additional arrays
        assert "self_evaluation" in custom
        assert "honors_awards" not in custom
        assert data["additional"]["certificationsTraining"] == [
            "AWS Solutions Architect Associate (2023)"
        ]
        assert data["additional"]["awards"] == ["Employee of the Year 2022"]

    def test_section_meta_covers_every_section_with_verbatim_keys(self) -> None:
        data = json.loads(RESUME_SCHEMA_EXAMPLE)
        rows = data["sectionMeta"]
        keys = [row["key"] for row in rows]
        assert keys[:6] == [
            "personalInfo",
            "education",
            "summary",
            "additional",
            "workExperience",
            "personalProjects",
        ]
        assert "self_evaluation" in keys
        assert "honors_awards" not in keys
        # every custom meta key must resolve to a customSections object
        for row in rows:
            if not row["isDefault"]:
                assert row["id"] == row["key"]
                assert row["key"] in data["customSections"]
        assert [row["order"] for row in rows] == list(range(len(rows)))


class TestSectionIdentityRules:
    def test_advantage_headings_go_to_summary_only(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in ("个人优势", "核心优势", "竞争优势", "综合优势", "个人亮点"):
            assert token in prompt
        assert 'top-level "summary"' in prompt
        assert "do not duplicate it" in prompt
        # 个人总结 moved out of the summary bucket into self_evaluation
        assert 'displayName "个人总结"' in prompt

    def test_selfeval_is_a_separate_custom_block(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in (
            "自我介绍",
            "个人介绍",
            "个人简介",
            "个人简述",
            "个人评价",
            "自我评价",
            "个人总结",
            "self_evaluation",
        ):
            assert token in prompt
        assert 'Never put these into "summary"' in " ".join(prompt.split())

    def test_timeline_section_heading_aliases_are_listed(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in ("实习经历", "从业经历", "职业履历", "任职经历", "工作履历", "职场经历"):
            assert token in prompt
        for token in ("项目履历", "重点项目"):
            assert token in prompt
        for token in ("学历信息", "求学履历"):
            assert token in prompt

    def test_skills_go_to_technical_skills(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in ("专业技能", "核心技能", "专业能力", "技术能力", "技能清单"):
            assert token in prompt
        assert "additional.technicalSkills" in prompt

    def test_honors_go_to_additional_fields_never_custom_section(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in (
            "荣誉证书",
            "荣誉/证书",
            "获奖情况",
            "资质荣誉",
            "资格证书",
            "资质认证",
        ):
            assert token in prompt
        # dedicated honors headings route into the two additional arrays…
        assert "additional.certificationsTraining" in prompt
        assert "additional.awards" in prompt
        # …and never create an honors_awards custom section
        assert "honors_awards" not in prompt
        assert "NEVER into customSections" in prompt

    def test_education_description_never_holds_inline_credentials(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        # award/cert lines inside the education block route to additional…
        assert "additional.awards / additional.certificationsTraining" in prompt
        # …and must never stay glued to the major in education.description
        assert "NEVER\ncopy such lines into education.description" in prompt
        # the major cell keeps the specialization without its label
        assert 'without the "专业："\nprefix' in prompt

    def test_languages_never_mix_into_technical_skills(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        for token in ("语言能力", "外语水平", "additional.languages"):
            assert token in prompt
        # even when the source nests them inside a combined skills block
        assert "NEVER appear in additional.technicalSkills" in prompt

    def test_header_demographics_go_to_personal_info_verbatim(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        # the four personalInfo fields are named with their zh tokens
        for token in ("gender", "age", "workYears", "educationLevel"):
            assert token in prompt
        for token in ("性别", "年龄", "工作年限", "最高学历"):
            assert token in prompt
        # copied verbatim from the header, never inferred, blank when unstated
        assert "copied VERBATIM" in prompt
        assert "never inferred" in prompt
        assert 'Use "" for any of the' in prompt
        # parenthetical school tags must survive in educationLevel
        for token in ("(211)", "(985)", "统招", "双一流"):
            assert token in prompt
        assert "统招本科(211)" in prompt


class TestFormatFidelity:
    def test_each_source_line_is_its_own_element(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        assert "its OWN array element" in prompt
        assert "never collapse content into" in prompt.lower()

    def test_text_blocks_keep_one_point_per_line(self) -> None:
        assert 'one point\n     per line joined by "\\n"' in PARSE_RESUME_PROMPT

    def test_custom_sections_must_reproduce_source_formatting(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        assert "customSections content must reproduce the source formatting" in prompt
        # Text blocks must be newline-joined strings, never arrays/space joins
        assert "never an array" in prompt
        assert "do not reflow, rewrap, renumber" in prompt

    def test_skill_group_labels_kept_per_line(self) -> None:
        assert "后端框架" in PARSE_RESUME_PROMPT

    def test_standalone_skill_group_headers_kept_as_own_entries(self) -> None:
        # Content lock for the grouped-skills shape (resume 4d85f471): a
        # standalone bold category header above detail bullets must survive
        # as its own short technicalSkills entry so the deterministic render
        # planner can rebuild the header/details hierarchy.
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "STANDALONE bold category/group header" in prompt
        assert "AI 大模型" in prompt
        assert "never invent group headers" in prompt
        assert "render planner rebuilds" in prompt


class TestProjectV4Alignment:
    def test_projects_capture_six_field_proxy(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        # name + role
        assert "项目名称" in prompt and "担任角色" in prompt
        # background/scenario
        assert "背景" in prompt and "场景" in prompt
        # technologies stay explicit, at least two when listed
        assert "at least two" in prompt
        # duty verbs + quantified results verbatim
        assert "action verbs" in prompt
        assert "VERBATIM" in prompt
        assert "NEVER invent" in prompt

    def test_project_period_uses_empty_string_when_absent(self) -> None:
        assert 'use "" when the' in PARSE_RESUME_PROMPT.replace("\n", " ")

    def test_source_list_numbering_must_not_be_copied(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        assert "NEVER copy the source's own numbering/bullet markers" in prompt
        assert "The renderer\n     numbers every list itself" in prompt

    def test_in_item_sub_labels_are_standalone_label_rows(self) -> None:
        prompt = PARSE_RESUME_PROMPT
        assert "IN-ITEM SUB-MODULES stay in place" in prompt
        assert "including unlisted" in prompt
        assert 'descriptionStyles "label"' in prompt
        for token in ("负责内容", "项目亮点", "难点与解决"):
            assert token in prompt
        flat = " ".join(prompt.split())
        assert "NEVER merge it with the following line" in flat

    def test_project_sub_labels_use_four_canonical_names(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "output as 项目职责" in prompt
        assert "output as 项目亮点" in prompt
        assert "output as 项目背景" in prompt
        assert "output as 技术栈" in prompt
        # The new alias families are all enumerated.
        for token in ("项目概述", "需求背景", "项目介绍", "所用技术", "技术清单"):
            assert token in prompt
        # Personal-phrasing and combined duty+result aliases (real uploads).
        for token in ("个人职责", "项目责任", "个人职责与成果", "核心职责与成果"):
            assert token in prompt
        assert "个人成果" in prompt
        # Renaming is project-scoped; work-entry labels stay verbatim.
        assert "personalProjects ONLY" in prompt
        assert "workExperience labels" in prompt and "stay verbatim" in prompt

    def test_each_sub_module_bullets_render_restart_at_one(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "each sub-label's bullets restart numbering at 1 at" in prompt

    def test_project_intro_and_tech_rows_are_plain(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "技术列表" in prompt and "项目简介" in prompt
        assert "are NOT duty points" in prompt
        assert 'ALL of its content row(s) are "plain" rows' in prompt
        assert "render below the bold label, aligned to the label text" in prompt
        assert "must never be numbered" in prompt

    def test_project_scale_and_role_have_header_fields(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "scale (项目规模" in prompt
        assert '"项目规模：…" / "团队规模：…" fills scale' in prompt
        assert '"项目角色：…" / "担任角色：…" fills role' in prompt
        # the schema example (injected via {schema}) carries the scale field
        example = json.loads(RESUME_SCHEMA_EXAMPLE)
        assert example["personalProjects"][0]["scale"] == ""
        assert '"scale": ""' in _formatted_prompt()

    def test_unplanned_sub_modules_become_plain_rows_without_reflow(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "unplanned structures that have no schema field" in prompt
        assert 'NEVER join cells or lines with " - " or punctuation' in prompt
        assert "never renumber, rewrite, or restructure" in prompt
        assert 'reproduced as "plain" rows' in prompt

    def test_bare_group_headings_are_standalone_labels_with_hierarchical_render(
        self,
    ) -> None:
        # Content lock for the 邹利平.pdf shape: bold colon-less sub-headings
        # inside 项目职责/项目亮点 must survive as their own label rows so the
        # renderer can number them 1./1.1/1.2.
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "NESTED GROUP HEADINGS" in prompt
        assert "carry no colon and no number" in prompt
        assert 'OWN short "label" row with no trailing colon' in prompt
        # The model must not flatten, skip or self-number the hierarchy.
        assert "never merge a sub-heading into its first bullet" in prompt
        assert "never skip a sub-heading" in prompt
        assert "the renderer numbers them hierarchically" in prompt
        # Concrete bare-head examples are enumerated verbatim.
        assert "架构演进与技术债务治理" in prompt
        assert "主导促销中心组件设计" in prompt


class TestDateCanonicalization:
    def test_prompt_mandates_numeric_tilde_periods(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        # The exact canonical shapes appear verbatim as examples.
        assert '"yyyy.MM"' in prompt
        assert '"2020.06~2023.09"' in prompt
        assert '"2024.03~至今"' in prompt
        # English month names and every open-ended marker are converted.
        assert '"Jan 2020 - Dec 2023"' in prompt
        assert '"2020.01~2023.12"' in prompt
        assert "Present/Current/Now/Ongoing" in prompt
        # Precision rule + colloquial prohibition.
        assert "never invent a month" in prompt
        assert "三年经验" in prompt

    def test_schema_example_uses_only_canonical_periods(self) -> None:
        data = json.loads(RESUME_SCHEMA_EXAMPLE)
        period_paths = []

        def collect(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "years" and isinstance(value, str) and value:
                        period_paths.append(value)
                    else:
                        collect(value)
            elif isinstance(node, list):
                for child in node:
                    collect(child)

        collect(data)
        assert period_paths  # the example genuinely carries dates
        canonical = re.compile(r"^\d{4}(\.\d{2})?(~\d{4}(\.\d{2})?|~至今)?$")
        for period in period_paths:
            assert canonical.fullmatch(period), period
            assert "Present" not in period and " - " not in period


class TestTechStackCategories:
    def test_prompt_keeps_source_category_lines_one_row_each(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "数据库：MySQL、Redis" in prompt
        assert "keep EACH category line verbatim as ONE" in prompt
        assert "never inventing categories" in prompt


class TestTechTermCasing:
    def test_prompt_mandates_canonical_term_casing(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "standard canonical casing" in prompt
        # A representative spread of the curated examples is named in the rule.
        for term in ("Java", "JavaScript", "Spring Boot", "MySQL", "Kubernetes"):
            assert term in prompt
        # The exact lowercase/all-caps failure modes are called out.
        assert '"java", "JAVA", "spring boot", "JAVASCRIPT"' in prompt

    def test_prompt_allows_only_conservative_extraction_repairs(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "obvious extraction/OCR damage" in prompt
        # The permission is bounded: no rewriting, facts, or number changes.
        assert "Do NOT rewrite wording" in prompt
        assert "alter numbers/metrics" in prompt
        assert 'when in doubt, copy the source' in prompt


class TestSkillsCategoryLines:
    def test_skills_section_keeps_category_prefixes_and_bare_names(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "category line as ONE entry with its category prefix" in prompt
        assert "never invent categories the source does not have" in prompt
        assert "bare (unprefixed) skill names as one entry per line" in prompt


class TestWorkDepartment:
    def test_schema_example_carries_department_field(self) -> None:
        example = json.loads(RESUME_SCHEMA_EXAMPLE)
        assert example["workExperience"][0]["department"] == "Platform Engineering"

    def test_standalone_org_unit_line_fills_department_never_description(self) -> None:
        prompt = " ".join(PARSE_RESUME_PROMPT.split())
        assert "department field holds the org unit" in prompt
        for token in ("全球资金部", "研发部", "云计算集成部"):
            assert token in prompt
        assert "NEVER leave it in description" in prompt
        assert 'use "" when the source gives no department' in prompt
