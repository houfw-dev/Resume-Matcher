"""Tests for the deterministic (LLM-free) diagnosis checks (rubric V4).

Every test pins a concrete signal -> rating mapping, so a checker that stops
detecting its target fails here instead of silently inflating the checklist.
"""

import pytest

from app.services.diagnosis_checks import (
    Interval,
    _check_basic_info,
    _check_date_format,
    _check_date_validity,
    _check_education_elements,
    _check_gaps,
    _check_job_hops,
    _check_mainstream_stack,
    _check_modules,
    _check_order,
    _check_page_length,
    _check_section_governance,
    _check_paragraph_length,
    _check_privacy,
    _check_projects,
    _check_education_overlap,
    _check_project_timeline,
    _check_selfeval_points,
    _check_short_stints,
    _check_skill_count,
    _check_stated_years,
    _check_summary_points,
    _check_work_education_order,
    _check_work_elements,
    _check_work_overlap,
    _join_findings,
    _timeline_facts,
    _union_tenure_months,
    build_mainstream_stack_finding,
    count_points,
    mainstream_stack_coverage,
    parse_date_range,
    run_objective_checks,
    technical_skill_entries,
)
from app.services.diagnosis_rules import (
    RATING_CONFORM,
    RATING_NA,
    RATING_NONCONFORM,
    RATING_PARTIAL,
)


def _resume(**overrides: object) -> dict:
    base: dict = {
        "personalInfo": {"name": "王浩"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    base.update(overrides)
    return base


# --- date parsing ----------------------------------------------------------


def test_parse_date_range_inclusive_months() -> None:
    iv = parse_date_range("2019.09 - 2021.06")
    assert iv is not None
    assert iv.start == (2019, 9)
    assert iv.end == (2021, 6)
    assert iv.length_months == 22  # 21 month-span + inclusive month


def test_parse_open_ended_and_variants() -> None:
    iv = parse_date_range("2024.03 至今")
    assert iv is not None and iv.end is None
    iv2 = parse_date_range("2020/1-2021/12")
    assert iv2 is not None and iv2.end == (2021, 12)
    assert parse_date_range("") is None


def test_union_tenure_counts_overlap_once() -> None:
    months = _union_tenure_months(
        [
            Interval((2020, 1), (2020, 12), "", ""),
            Interval((2020, 7), (2021, 6), "", ""),  # overlaps 6 months
        ]
    )
    assert months == 18


# --- item 1: block order + paragraph length --------------------------------


def test_order_inversion_detected() -> None:
    # Formal degree (统招本科) puts education second; work before education is
    # out of order in that branch.
    meta = [
        {"key": "personalInfo", "displayName": "基本信息", "isVisible": True, "order": 0},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 1},
        {"key": "education", "displayName": "教育经历", "isVisible": True, "order": 2},
    ]
    resume = _resume(
        sectionMeta=meta,
        education=[{"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016 - 2020"}],
    )
    rating, evidence, _suggestion = _check_order(resume)
    assert rating == RATING_NONCONFORM
    assert "不一致" in evidence


def test_order_conforms_in_formal_sequence() -> None:
    meta = [
        {"key": "personalInfo", "displayName": "基本信息", "isVisible": True, "order": 0},
        {"key": "education", "displayName": "教育经历", "isVisible": True, "order": 1},
        {"key": "summary", "displayName": "个人优势", "isVisible": True, "order": 2},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 3},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 4},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 5},
    ]
    resume = _resume(
        sectionMeta=meta,
        education=[{"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016 - 2020"}],
    )
    assert _check_order(resume)[0] == RATING_CONFORM


def test_order_conforms_in_other_branch_with_education_near_end() -> None:
    # Non-formal degree: education sits between the custom cluster (here a
    # legacy 荣誉证书 block) and 自我评价.
    meta = [
        {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
        {"key": "summary", "displayName": "个人优势", "isVisible": True, "order": 1},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 2},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 3},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 4},
        {"key": "custom_honors", "displayName": "荣誉证书", "isVisible": True, "order": 5},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 6},
        {"key": "custom_eval", "displayName": "自我评价", "isVisible": True, "order": 7},
    ]
    resume = _resume(
        sectionMeta=meta,
        education=[{"id": 1, "institution": "甲大学", "degree": "大专", "years": "2013 - 2016"}],
    )
    rating, _evidence, _suggestion = _check_order(resume)
    assert rating == RATING_CONFORM


def test_order_other_branch_education_directly_before_selfeval_without_extra_customs() -> None:
    meta = [
        {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
        {"key": "summary", "displayName": "个人优势", "isVisible": True, "order": 1},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 2},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 3},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 4},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 5},
        {"key": "custom_eval", "displayName": "自我评价", "isVisible": True, "order": 6},
    ]
    resume = _resume(
        sectionMeta=meta,
        education=[{"id": 1, "degree": "自考本科"}],
    )
    assert _check_order(resume)[0] == RATING_CONFORM


def test_order_unknown_custom_blocks_form_one_cluster_after_projects() -> None:
    meta = [
        {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 1},
        {"key": "summary", "displayName": "个人优势", "isVisible": True, "order": 2},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 3},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 4},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 5},
        {"key": "custom_a", "displayName": "志愿者", "isVisible": True, "order": 6},
        {"key": "custom_b", "displayName": "出版物", "isVisible": True, "order": 7},
        {"key": "custom_honors", "displayName": "荣誉证书", "isVisible": True, "order": 8},
        {"key": "custom_eval", "displayName": "自我评价", "isVisible": True, "order": 9},
    ]
    resume = _resume(
        sectionMeta=meta,
        education=[{"id": 1, "degree": "全日制本科"}],
    )
    assert _check_order(resume)[0] == RATING_CONFORM

    # ...but stranding the self-evaluation row among the custom blocks breaks
    # the sequence (自我评价 must own the terminal fixed slot).
    meta[6]["order"], meta[9]["order"] = meta[9]["order"], meta[6]["order"]
    scrambled = _resume(
        sectionMeta=[dict(m) for m in meta],
        education=[{"id": 1, "degree": "全日制本科"}],
    )
    assert _check_order(scrambled)[0] == RATING_NONCONFORM


def test_order_missing_meta_uses_degree_branch_synthetic_view() -> None:
    # Parsed resumes store no sectionMeta: the synthetic default view must
    # match the degree branch instead of flagging every parsed resume.
    formal = _resume(education=[{"id": 1, "degree": "博士"}])
    other = _resume(education=[{"id": 1, "degree": "大专"}])
    assert _check_order(formal)[0] == RATING_CONFORM
    assert _check_order(other)[0] == RATING_CONFORM


def test_oversized_paragraph_fails() -> None:
    resume = _resume(summary="技" * 300)
    rating, _, _suggestion = _check_paragraph_length(resume)
    assert rating == RATING_NONCONFORM


def test_split_points_measured_per_point_not_over_joined_block() -> None:
    # Real stored resume: five newline-split points, 364 chars total (~8
    # rendered lines if joined) but each point only ~2 lines. The renderer
    # shows five numbered points, so the checker must conform.
    points = [
        "10年以上Java开发经验，其中3年的电商，5年的大型医院项目开发经验；",
        "拥有5年以上微服务项目开发经验，实践经验扎实；",
        "系统学习了并发编程、SpringBoot、Redis等技术；",
        "5年项目管理经验，取得信息系统项目管理师证书；",
        "2年全栈开发经验，熟悉Vue2/3、React等框架。",
    ]
    resume = _resume(summary="\n".join(points))
    rating, evidence, _suggestion = _check_paragraph_length(resume)
    assert rating == RATING_CONFORM
    assert evidence == ""


def test_one_dense_point_among_split_points_fails_with_that_point() -> None:
    dense = "密" * 300
    resume = _resume(summary="短要点一\n" + dense + "\n短要点二")
    rating, evidence, suggestion = _check_paragraph_length(resume)
    assert rating == RATING_NONCONFORM
    assert evidence.startswith(f"「{dense[:40]}")
    assert "拆分" in suggestion


# --- item 1: section title governance ---------------------------------------


def _governance_meta() -> list[dict]:
    return [
        {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 1},
        {"key": "summary", "displayName": "个人优势", "isVisible": True, "order": 2},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 3},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 4},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 5},
    ]


def test_governance_conforms_on_clean_meta() -> None:
    meta = _governance_meta()
    resume = _resume(
        sectionMeta=meta,
        summary="有内容的个人优势",
        education=[{"id": 1, "degree": "统招本科"}],
    )
    rating, _evidence, _suggestion = _check_section_governance(resume)
    assert rating == RATING_CONFORM


def test_governance_flags_duplicate_visible_titles() -> None:
    meta = _governance_meta()
    meta.append(
        {"key": "custom_a", "displayName": "荣誉证书", "isVisible": True, "order": 6}
    )
    meta.append(
        {"key": "custom_b", "displayName": " 荣誉证书 ", "isVisible": True, "order": 7}
    )
    rating, evidence, _suggestion = _check_section_governance(_resume(sectionMeta=meta))
    assert rating == RATING_NONCONFORM
    assert "「荣誉证书」区块标题重复出现" in evidence


def test_governance_flags_renamed_default_title() -> None:
    meta = _governance_meta()
    meta[2]["displayName"] = "我的故事"
    rating, evidence, _suggestion = _check_section_governance(
        _resume(sectionMeta=meta, summary="有内容")
    )
    assert rating == RATING_NONCONFORM
    assert "默认区块标题被改为「我的故事」" in evidence


def test_join_findings_strips_terminal_punctuation_before_semicolon_join() -> None:
    # Regression: "恢复被改区块的默认标题。" + "；将该长段拆分…" rendered as
    # "恢复被改区块的默认标题。；将该长段拆分…".
    joined = _join_findings(
        [
            (RATING_NONCONFORM, "问题一。", "恢复被改区块的默认标题。"),
            (RATING_NONCONFORM, "问题二！", "将该长段拆分为多条短句要点。"),
        ]
    )
    _rating, evidence, suggestion = joined
    # Seam punctuation is removed; the final part keeps its own period.
    assert evidence == "问题一；问题二！"
    assert suggestion == "恢复被改区块的默认标题；将该长段拆分为多条短句要点。"
    assert "。；" not in evidence + suggestion


def test_governance_ignores_personal_info_header_title() -> None:
    # The personal-info header renders the name and a fact grid; no template
    # ever displays its section title, so a stored rename (LLM extraction
    # produced "基本资料") must not be reported as a renamed default block.
    meta = _governance_meta()
    meta[0]["displayName"] = "基本资料"
    rating, evidence, _suggestion = _check_section_governance(
        _resume(sectionMeta=meta, summary="有内容")
    )
    assert rating == RATING_CONFORM
    assert "基本资料" not in evidence


def test_governance_accepts_shipped_zh_aliases() -> None:
    # Shipped zh defaults pre-canonicalization (个人信息/个人优势/技能与荣誉…)
    # and every alias heading from the mapping rules are accepted, not
    # reported as renames.
    meta = [
        {"key": "personalInfo", "displayName": "个人信息", "isVisible": True, "order": 0},
        {"key": "summary", "displayName": "核心优势", "isVisible": True, "order": 1},
        {"key": "workExperience", "displayName": "实习经历", "isVisible": True, "order": 2},
        {"key": "education", "displayName": "学历信息", "isVisible": True, "order": 3},
        {"key": "personalProjects", "displayName": "重点项目", "isVisible": True, "order": 4},
        {"key": "additional", "displayName": "核心技能", "isVisible": True, "order": 5},
    ]
    rating, _evidence, _suggestion = _check_section_governance(
        _resume(sectionMeta=meta, summary="有内容", education=[{"id": 1, "degree": "本科"}])
    )
    assert rating == RATING_CONFORM


def test_governance_flags_summary_named_like_self_introduction() -> None:
    # 个人简介 belongs to the 自我介绍 group; on the summary default block it
    # is now a rename, not an accepted alias.
    meta = [
        {"key": "personalInfo", "displayName": "个人信息", "isVisible": True, "order": 0},
        {"key": "summary", "displayName": "个人简介", "isVisible": True, "order": 1},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 2},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 3},
        {"key": "personalProjects", "displayName": "项目经历", "isVisible": True, "order": 4},
        {"key": "additional", "displayName": "技能与荣誉", "isVisible": True, "order": 5},
    ]
    rating, _evidence, _suggestion = _check_section_governance(
        _resume(sectionMeta=meta, summary="有内容", education=[{"id": 1, "degree": "本科"}])
    )
    assert rating == RATING_NONCONFORM


def test_governance_flags_empty_visible_optional_as_partial() -> None:
    meta = _governance_meta()
    meta.append(
        {"key": "custom_honors", "displayName": "荣誉证书", "isVisible": True, "order": 6}
    )
    resume = _resume(
        sectionMeta=meta,
        summary="",
        customSections={"custom_honors": {"sectionType": "text", "text": "   "}},
    )
    rating, evidence, _suggestion = _check_section_governance(resume)
    assert rating == RATING_PARTIAL
    assert "「荣誉证书」区块有标题无内容" in evidence
    assert "「个人优势」区块有标题无内容" in evidence


def test_governance_does_not_report_empty_required_blocks() -> None:
    # Empty required blocks are attributed to item 3, not item 1.
    meta = _governance_meta()
    meta = [m for m in meta if m["key"] != "summary"]
    rating, _evidence, _suggestion = _check_section_governance(_resume(sectionMeta=meta))
    assert rating == RATING_CONFORM


# --- item 2: page count ------------------------------------------------------


def test_page_length_conforms_for_short_resume() -> None:
    rating, _, _suggestion = _check_page_length(_resume(summary="简短简历内容"))
    assert rating == RATING_CONFORM


def test_page_length_fails_past_three_pages() -> None:
    rating, evidence, _suggestion = _check_page_length(_resume(summary="字" * 3200))
    assert rating == RATING_NONCONFORM
    assert "篇幅" in evidence


# --- item 3: required modules -----------------------------------------------


def test_modules_all_five_required_present_conforms() -> None:
    resume = _resume(
        education=[{"id": 1, "institution": "甲大学", "years": "2016 - 2020", "degree": "本科"}],
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2020 - 2024"}],
        personalProjects=[
            {"id": 1, "name": "项目", "role": "开发", "description": []}
        ],
        additional={"technicalSkills": ["Java"]},
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=3)
    assert rating == RATING_CONFORM
    assert "荣誉" not in evidence


def test_modules_work_required_even_for_fresh_graduate() -> None:
    # V4 deleted the fresh-graduate substitution: work experience is one of the
    # five unconditionally required modules, projects can no longer replace it.
    resume = _resume(
        education=[{"id": 1, "institution": "甲大学", "years": "2023 - 2027", "degree": "本科"}],
        personalProjects=[
            {"id": 1, "name": "项目", "role": "开发", "description": []}
        ],
        additional={"technicalSkills": ["Java"]},
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=0)
    assert rating == RATING_PARTIAL
    assert "工作经历" in evidence


def test_modules_missing_basic_info_is_one_missing_module() -> None:
    resume = _resume(
        personalInfo={},
        education=[{"id": 1, "institution": "甲大学", "years": "2016 - 2020", "degree": "本科"}],
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2020 - 2024"}],
        personalProjects=[
            {"id": 1, "name": "项目", "role": "开发", "description": []}
        ],
        additional={"technicalSkills": ["Java"]},
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=3)
    assert rating == RATING_PARTIAL
    assert "基础信息" in evidence


def test_modules_eight_years_requires_summary() -> None:
    resume = _resume(
        education=[{"id": 1, "institution": "甲大学", "years": "2010 - 2014", "degree": "本科"}],
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2014 - 2024"}],
        personalProjects=[{"id": 1, "name": "项目", "role": "开发", "description": []}],
        additional={"technicalSkills": ["Java"]},
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=9)
    assert rating in (RATING_PARTIAL, RATING_NONCONFORM)
    assert "个人优势" in evidence


def test_modules_eight_years_accepts_named_custom_advantage() -> None:
    # 个人优势 living in a meta-less custom block still satisfies item 3 for
    # senior candidates; only an absent advantage module is flagged.
    resume = _resume(
        education=[{"id": 1, "institution": "甲大学", "years": "2010 - 2014", "degree": "本科"}],
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2014 - 2024"}],
        personalProjects=[{"id": 1, "name": "项目", "role": "开发", "description": []}],
        additional={"technicalSkills": ["Java"]},
        customSections={
            "personal_advantages": {
                "sectionType": "stringList",
                "strings": ["大厂背景", "架构能力", "技术深度"],
            }
        },
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=9)
    assert "个人优势" not in evidence
    assert rating == RATING_CONFORM


def test_modules_whitespace_only_entries_count_as_missing() -> None:
    # Regression: education=[{}] and all-empty work/project entries used to
    # look "present" because a non-empty list is truthy.
    resume = _resume(
        education=[{}],
        workExperience=[{"id": 1}],
        personalProjects=[{"id": 2}],
        additional={"technicalSkills": ["Java"]},
    )
    rating, evidence, _suggestion = _check_modules(resume, tenure_years=3)
    assert rating == RATING_NONCONFORM
    assert "教育经历" in evidence
    assert "工作经历" in evidence
    assert "项目经验" in evidence


# --- item 4: required basic info --------------------------------------------


def test_basic_info_missing_phone_fails() -> None:
    resume = _resume(
        personalInfo={
            "name": "王浩",
            "email": "a@b.com",
            "title": "Java 开发工程师",
            "location": "上海",
        }
    )
    rating, evidence, _suggestion = _check_basic_info(resume)
    assert rating == RATING_NONCONFORM
    assert "手机号" in evidence


def test_basic_info_all_required_fields_present_conforms() -> None:
    # V4 必填项：姓名、性别、手机号、邮箱、求职意向（期望城市为选填，见下例）。
    resume = _resume(
        personalInfo={
            "name": "王浩",
            "gender": "男",
            "phone": "138 1234 5678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "上海",
        }
    )
    assert _check_basic_info(resume)[0] == RATING_CONFORM


def test_basic_info_missing_expected_city_still_conforms() -> None:
    # 期望城市（location）是选填项：缺失/空白都不得判不符合，也不进整改建议。
    resume = _resume(
        personalInfo={
            "name": "王浩",
            "gender": "男",
            "phone": "138 1234 5678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "",
        }
    )
    rating, evidence, suggestion = _check_basic_info(resume)
    assert rating == RATING_CONFORM
    assert evidence == ""
    assert "期望城市" not in suggestion
    assert "意向城市" not in suggestion


def test_basic_info_missing_gender_fails() -> None:
    resume = _resume(
        personalInfo={
            "name": "王浩",
            "phone": "138 1234 5678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "上海",
        }
    )
    rating, evidence, suggestion = _check_basic_info(resume)
    assert rating == RATING_NONCONFORM
    assert "性别" in evidence
    assert "性别" in suggestion


def test_basic_info_recommended_fields_alone_do_not_fail() -> None:
    # 年龄/学历/工作年限是推荐项：缺失不扣分，性别等必填项齐全即符合。
    resume = _resume(
        personalInfo={
            "name": "王浩",
            "gender": "女",
            "phone": "138 1234 5678",
            "email": "wang@example.com",
            "title": "前端开发工程师",
            "location": "深圳",
        }
    )
    assert _check_basic_info(resume)[0] == RATING_CONFORM


# --- item 5: education four elements ----------------------------------------


def test_education_missing_major_and_annotation_partial() -> None:
    resume = _resume(
        education=[{"id": 1, "institution": "甲大学", "years": "2016.09 - 2020.06", "degree": "本科"}]
    )
    assert _check_education_elements(resume)[0] == RATING_PARTIAL


def test_education_full_conforms() -> None:
    resume = _resume(
        education=[
            {
                "id": 1,
                "institution": "甲大学",
                "years": "2016.09 - 2020.06",
                "degree": "本科（统招全日制）",
                "description": "计算机科学与技术",
            }
        ]
    )
    assert _check_education_elements(resume)[0] == RATING_CONFORM


def test_education_missing_module_is_na() -> None:
    assert _check_education_elements(_resume())[0] == RATING_NA


# --- item 6: summary content quality -----------------------------------------


def test_summary_empty_is_na_absence_owned_by_item3() -> None:
    assert _check_summary_points(_resume(), tenure_years=9)[0] == RATING_NA


def test_summary_two_to_five_points_conforms() -> None:
    resume = _resume(summary="1、大厂背景\n2、架构能力\n3、核心技术栈积累")
    assert _check_summary_points(resume, tenure_years=6)[0] == RATING_CONFORM


def test_summary_too_many_points_partial() -> None:
    resume = _resume(summary="\n".join(f"{i}、第{i}点" for i in range(1, 8)))
    assert _check_summary_points(resume, tenure_years=6)[0] == RATING_PARTIAL


def test_advantage_falls_back_to_meta_less_custom_itemlist() -> None:
    # Legacy parser output (e.g. real uploaded resume): no sectionMeta row,
    # 个人优势 misfiled under a snake_case custom key as itemList item titles.
    resume = _resume(
        customSections={
            "personal_advantages": {
                "sectionType": "itemList",
                "items": [
                    {"title": "大厂背景，熟悉高并发"},
                    {"title": "主导过支付链路重构"},
                    {"title": "Java/Go 双技术栈"},
                ],
            }
        }
    )
    assert _check_summary_points(resume, tenure_years=6)[0] == RATING_CONFORM


def test_advantage_falls_back_to_meta_less_custom_stringlist() -> None:
    resume = _resume(
        customSections={
            "core_strengths": {
                "sectionType": "stringList",
                "strings": ["架构设计能力", "跨团队协作", "线上稳定性治理"],
            }
        }
    )
    assert _check_summary_points(resume, tenure_years=6)[0] == RATING_CONFORM


def test_visible_summary_wins_over_named_custom_block() -> None:
    resume = _resume(
        summary="1、第一点\n2、第二点\n3、第三点",
        customSections={
            "personal_advantages": {
                "sectionType": "text",
                "text": "\n".join(str(i) for i in range(1, 9)),
            }
        },
    )
    # 8 custom points would be partial; the visible summary (3 points) is judged.
    assert _check_summary_points(resume, tenure_years=6)[0] == RATING_CONFORM


# --- item 7: skills count + mainstream coverage ------------------------------


def test_skill_count_under_eight_fails() -> None:
    resume = _resume(additional={"technicalSkills": ["Java", "MySQL", "Redis"]})
    rating, evidence, _suggestion = _check_skill_count(resume)
    assert rating == RATING_NONCONFORM
    assert "3" in evidence


def test_skill_count_over_fifteen_fails() -> None:
    skills = [f"技能{i}" for i in range(16)]
    assert _check_skill_count(_resume(additional={"technicalSkills": skills}))[0] == RATING_NONCONFORM


def test_skill_count_in_range_conforms() -> None:
    skills = [f"技能{i}" for i in range(10)]
    assert _check_skill_count(_resume(additional={"technicalSkills": skills}))[0] == RATING_CONFORM


def test_skill_empty_is_na() -> None:
    assert _check_skill_count(_resume())[0] == RATING_NA


def test_mainstream_stack_partial_coverage() -> None:
    # Five of the nine groups: Boot, MySQL, Redis, JVM, MQ(Kafka).
    resume = _resume(
        additional={"technicalSkills": ["Spring Boot", "MySQL", "Redis", "JVM 调优", "Kafka"]}
    )
    rating, evidence, suggestion = _check_mainstream_stack(resume)
    assert rating == RATING_PARTIAL
    # Evidence names what the resume actually has; the coverage ratio and the
    # canonical group count are server-side rubric material.
    assert "Spring Boot" in evidence and "JVM" in evidence
    assert "5/9" not in evidence and "个主流栈" not in evidence
    assert "覆盖不足" in evidence
    # The fix lists only missing directions, never categories already present.
    assert "微服务框架" in suggestion
    assert "并发与多线程编程" in suggestion
    assert "AI 应用开发" in suggestion
    assert "Redis" not in suggestion and "JVM" not in suggestion
    assert "MySQL" not in suggestion and "消息队列" not in suggestion


def test_mainstream_stack_suggestion_never_names_present_categories() -> None:
    # Regression: a resume covering services, middleware and AI coding tools
    # was told to "add microservice frameworks, middleware, AI coding tools"
    # — directions it already had. Missing groups here: MySQL, JVM, AI 应用.
    resume = _resume(
        additional={
            "technicalSkills": [
                "Spring Boot",
                "Spring Cloud Alibaba",
                "Redis",
                "消息队列 MQ（RocketMQ）",
                "并发编程",
                "AI 编码工具 (Codex/Claude Code/Trae)",
            ]
        }
    )
    rating, evidence, suggestion = _check_mainstream_stack(resume)
    assert rating == RATING_PARTIAL
    assert "Spring Cloud Alibaba" in evidence and "Redis" in evidence
    assert "关系型数据库（MySQL）" in suggestion
    assert "JVM 原理与调优" in suggestion
    assert "AI 应用开发" in suggestion
    assert "微服务框架" not in suggestion
    assert "缓存中间件" not in suggestion
    assert "消息队列中间件" not in suggestion
    assert "AI 编码工具" not in suggestion


def test_ai_coding_tools_count_as_mainstream_group() -> None:
    skills = [
        "Spring Boot",
        "Spring Cloud Alibaba",
        "MySQL",
        "Redis",
        "RocketMQ",
        "JVM",
        "并发编程",
        "Spring AI / LangChain4j",
        "Claude Code / Codex / Trae",
    ]
    rating, evidence, suggestion = _check_mainstream_stack(
        _resume(additional={"technicalSkills": skills})
    )
    assert rating == RATING_CONFORM
    # Conform = silent: no coverage enumeration leaks into client text.
    assert evidence == "" and suggestion == ""


# --- item 7 semantic-review protocol helpers --------------------------------


def test_technical_skill_entries_strips_blanks_and_non_strings() -> None:
    resume = _resume(
        additional={"technicalSkills": [" Java ", "", "  ", 123, None, "Redis", ["nested"]]}
    )
    assert technical_skill_entries(resume) == ["Java", "Redis"]


def test_mainstream_coverage_splits_groups_by_regex() -> None:
    skills = ["Spring Boot", "Spring Cloud Alibaba", "Redis", "RocketMQ"]
    hit, miss = mainstream_stack_coverage(skills)
    assert hit == ("spring_boot", "spring_cloud", "redis", "mq")
    assert miss == ("rdbms", "jvm", "concurrency", "ai_app", "ai_coding")


def test_mainstream_coverage_all_hit() -> None:
    skills = [
        "Spring Boot",
        "Spring Cloud Alibaba",
        "MySQL",
        "Redis",
        "Kafka",
        "JVM 调优",
        "并发编程",
        "Spring AI",
        "Claude Code",
    ]
    hit, miss = mainstream_stack_coverage(skills)
    assert miss == ()
    assert len(hit) == 9


def test_build_finding_recomputes_rating_from_rescued_groups() -> None:
    # Six regex hits (partial); rdbms/jvm/ai_app rescued via synonyms → 9/9 silent.
    rescued = (
        "spring_boot",
        "spring_cloud",
        "rdbms",
        "redis",
        "mq",
        "jvm",
        "concurrency",
        "ai_app",
        "ai_coding",
    )
    rating, evidence, suggestion = build_mainstream_stack_finding(rescued)
    assert rating == RATING_CONFORM
    assert evidence == "" and suggestion == ""


def test_build_finding_partial_names_only_still_missing_directions() -> None:
    rating, evidence, suggestion = build_mainstream_stack_finding(
        ("spring_boot", "spring_cloud", "redis", "mq", "concurrency", "ai_coding")
    )
    assert rating == RATING_PARTIAL
    assert "覆盖不足" in evidence
    assert "关系型数据库（MySQL）" in suggestion
    assert "JVM 原理与调优" in suggestion
    assert "AI 应用开发" in suggestion
    # Three-example cap: the full checklist must not reach the client.
    assert "缓存中间件" not in suggestion
    assert "AI 编码工具" not in suggestion


# --- item 8: work three elements + internship rule ---------------------------


def test_work_elements_missing_title_fails() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "years": "2022.01 - 2023.06", "company": "甲公司", "title": ""}
        ]
    )
    rating, evidence, _suggestion = _check_work_elements(resume, tenure_years=3)
    assert rating in (RATING_PARTIAL, RATING_NONCONFORM)
    assert "岗位" in evidence


def test_work_three_elements_conform_without_department() -> None:
    resume = _resume(
        workExperience=[
            {
                "id": 1,
                "years": "2022.01 至今",
                "company": "甲公司",
                "title": "Java 开发工程师",
                "description": [],
            }
        ]
    )
    rating, evidence, suggestion = _check_work_elements(resume, tenure_years=3)
    assert rating == RATING_CONFORM
    # Conforming signals are silent by contract: no positive note, no advice.
    assert evidence == "" and suggestion == ""


def test_work_na_without_module() -> None:
    assert _check_work_elements(_resume(), tenure_years=3)[0] == RATING_NA


def test_internship_mixed_into_formal_work_after_one_year_fails() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "years": "2023.01 至今", "company": "甲公司", "title": "Java 工程师"},
            {"id": 2, "years": "2022.06 - 2022.12", "company": "乙公司", "title": "Java 实习"},
        ]
    )
    rating, evidence, _suggestion = _check_work_elements(resume, tenure_years=3)
    assert rating == RATING_NONCONFORM
    assert "实习" in evidence


def test_internship_allowed_for_fresh_graduate() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "years": "2026.03 至今", "company": "乙公司", "title": "Java 实习"}
        ]
    )
    assert _check_work_elements(resume, tenure_years=0)[0] == RATING_CONFORM


# --- item 9: project six fields + count 2–4 ----------------------------------


def test_project_without_highlight_metric_fails() -> None:
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "交易中台",
                "role": "核心开发",
                "description": [
                    "项目背景：为解决多系统重复对接问题",
                    "技术栈采用 Spring Boot、Redis、Kafka",
                    "负责订单模块开发与联调",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "基于 Spring Boot、MySQL、RocketMQ 设计",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    rating, evidence, _suggestion = _check_projects(resume)
    assert rating in (RATING_PARTIAL, RATING_NONCONFORM)
    assert "亮点" in evidence


def test_project_time_is_optional_but_six_fields_required() -> None:
    # V4: 项目时间 conditionally optional; a project with no years but all six
    # content fields must conform.
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "交易中台",
                "role": "核心开发",
                "description": [
                    "项目背景：为解决多系统重复对接问题",
                    "技术栈：Spring Boot、MySQL、Redis、Kafka 负责整体设计",
                    "主导订单链路重构，承担核心模块开发",
                    "接口耗时降低 40%，峰值 QPS 提升至 8000",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "基于 Spring Boot、MySQL、RocketMQ 设计",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    assert _check_projects(resume)[0] == RATING_CONFORM


def test_single_project_fails_for_experienced_candidate() -> None:
    project = {
        "id": 1,
        "name": "交易中台",
        "role": "核心开发",
        "description": [
            "项目背景：多系统对接",
            "技术栈：Spring Boot、MySQL、Redis、Kafka",
            "主导重构与开发",
            "接口耗时降低 40%",
        ],
    }
    rating, evidence, _suggestion = _check_projects(_resume(personalProjects=[project]))
    assert rating == RATING_NONCONFORM
    assert "1 个" in evidence


def test_single_project_fails_even_for_fresh_graduate() -> None:
    # V4 applies the 2–4 project count unconditionally; the fresh-graduate
    # carve-out left with the old substitution clause.
    project = {
        "id": 1,
        "name": "交易中台",
        "role": "核心开发",
        "description": [
            "项目背景：多系统对接",
            "技术栈：Spring Boot、MySQL、Redis、Kafka",
            "主导重构与开发",
            "接口耗时降低 40%",
        ],
    }
    rating, _, _suggestion = _check_projects(_resume(personalProjects=[project]))
    assert rating == RATING_NONCONFORM


def test_projects_missing_module_is_na() -> None:
    assert _check_projects(_resume())[0] == RATING_NA


def test_split_label_tech_stack_with_big_data_terms_is_detected() -> None:
    # Regression: a split "技术栈：" label row whose terms (Hadoop/Hive/...)
    # were absent from the old vocabulary regex falsely reported a missing
    # tech stack (the RATAN EOD diagnosis false-negative).
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "RATAN EOD",
                "role": "开发",
                "description": [
                    "技术栈：",
                    "Hadoop、Hive、ControlM、Spring Boot、PostgreSQL",
                    "项目背景：金融衍生品交易数据分散，报表时效难保障。",
                    "承担数据平台日常运维与变更上线保障",
                    "作业失败率控制在 1% 以内，异常回滚可在 30 分钟内完成。",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "技术栈：Spring Boot、MySQL、Redis",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    rating, evidence, _suggestion = _check_projects(resume)
    assert rating == RATING_CONFORM, evidence
    assert "技术栈" not in evidence


def test_empty_tech_stack_label_followed_by_another_label_still_missing() -> None:
    # A label row with no content of its own, immediately followed by another
    # label, means the tech stack field is genuinely empty.
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "数据平台",
                "role": "开发",
                "description": [
                    "技术栈：",
                    "项目背景：多系统数据分散，报表产出困难。",
                    "承担数据平台日常运维",
                    "报表产出时效提升 40%",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "技术栈：Spring Boot、MySQL、Redis",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    _rating, evidence, suggestion = _check_projects(resume)
    assert "「技术栈」" in evidence
    assert "「技术栈」" in suggestion


def test_glued_tech_stack_alias_label_is_detected() -> None:
    # Older stored documents may keep an alias label (技术架构) glued to its
    # content row instead of the canonical split 技术栈 form.
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "实时数仓",
                "role": "核心开发",
                "description": [
                    "项目背景：离线链路时延高，无法支撑实时运营。",
                    "技术架构：Hadoop、Hive、HBase",
                    "主导数仓底座重构，承担核心模块开发",
                    "链路时延缩短 50%",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "技术栈：Spring Boot、MySQL、Redis",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    rating, evidence, _suggestion = _check_projects(resume)
    assert rating == RATING_CONFORM, evidence


def test_big_data_vocab_fallback_detects_unlabeled_stack() -> None:
    # Without any label, two distinct expanded-vocabulary mentions in prose
    # still count as a tech stack.
    resume = _resume(
        personalProjects=[
            {
                "id": 1,
                "name": "实时数仓",
                "role": "核心开发",
                "description": [
                    "项目背景：离线链路时延高，无法支撑实时运营。",
                    "基于 Hadoop 与 Hive 构建数仓底座，支撑每日 ETL 作业",
                    "承担数据链路开发与稳定性保障",
                    "链路时延缩短 50%",
                ],
            },
            {
                "id": 2,
                "name": "营销系统",
                "role": "开发",
                "description": [
                    "业务背景：营销活动配置困难",
                    "技术栈：Spring Boot、MySQL、Redis",
                    "承担活动引擎开发",
                    "活动配置耗时降低 60%",
                ],
            },
        ]
    )
    rating, evidence, _suggestion = _check_projects(resume)
    assert rating == RATING_CONFORM, evidence


# --- item 10: self evaluation ------------------------------------------------


def test_selfeval_missing_is_na() -> None:
    assert _check_selfeval_points(_resume())[0] == RATING_NA


def test_selfeval_three_to_five_points_conforms() -> None:
    resume = _resume(
        sectionMeta=[
            {"key": "custom_1", "displayName": "自我评价", "isVisible": True, "order": 0}
        ],
        customSections={
            "custom_1": {"sectionType": "text", "text": "1、学习能力强\n2、团队协作\n3、抗压能力好"}
        },
    )
    assert _check_selfeval_points(resume)[0] == RATING_CONFORM


def test_selfeval_accepts_personal_summary_heading() -> None:
    # A section titled 个人总结 now parses into key self_evaluation; item 10
    # must evaluate it even though its displayName is not 自我评价.
    resume = _resume(
        sectionMeta=[
            {"key": "self_evaluation", "displayName": "个人总结", "isVisible": True, "order": 0}
        ],
        customSections={
            "self_evaluation": {
                "sectionType": "text",
                "text": "1、学习能力强\n2、团队协作\n3、抗压能力好",
            }
        },
    )
    assert _check_selfeval_points(resume)[0] == RATING_CONFORM


def test_selfeval_falls_back_to_meta_less_custom_key() -> None:
    # Legacy parser emitted the snake_case key but no sectionMeta row.
    resume = _resume(
        customSections={
            "self_evaluation": {
                "sectionType": "itemList",
                "items": [
                    {"title": "学习能力强，乐于复盘"},
                    {"title": "沟通协作顺畅"},
                    {"title": "能承受高压节奏"},
                ],
            }
        }
    )
    assert _check_selfeval_points(resume)[0] == RATING_CONFORM


def test_selfeval_fallback_ignores_unrelated_custom_keys() -> None:
    resume = _resume(
        customSections={
            "hobbies": {"sectionType": "stringList", "strings": ["阅读", "跑步"]}
        }
    )
    assert _check_selfeval_points(resume)[0] == RATING_NA


# --- item 13: timeline self-consistency --------------------------------------


def test_mixed_date_formats_flagged() -> None:
    resume = _resume(
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2020.01 - 2021.06"}],
        education=[{"id": 1, "institution": "乙大学", "years": "2016 - 2020"}],
    )
    rating, evidence, _suggestion = _check_date_format(resume)
    assert rating in (RATING_PARTIAL, RATING_NONCONFORM)
    assert "精度" in evidence or "格式" in evidence


def test_reversed_date_range_fails() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲", "title": "工程师", "years": "2023.06 - 2022.01"}
        ]
    )
    rating, evidence, _suggestion = _check_date_validity(resume)
    assert rating == RATING_NONCONFORM
    assert "晚于结束" in evidence


def test_overlapping_work_intervals_fail() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.01 - 2020.12"},
            {"id": 2, "company": "乙公司", "title": "工程师", "years": "2020.07 - 2021.06"},
        ]
    )
    rating, evidence, _suggestion = _check_work_overlap(resume)
    assert rating == RATING_NONCONFORM
    assert "重叠" in evidence


def test_overlapping_work_intervals_exempt_with_part_time_note() -> None:
    resume = _resume(
        workExperience=[
            {
                "id": 1,
                "company": "甲公司",
                "title": "工程师",
                "years": "2020.01 - 2020.12",
                "description": ["全职"],
            },
            {
                "id": 2,
                "company": "乙公司",
                "title": "外包开发",
                "years": "2020.07 - 2021.06",
                "description": ["兼职/外包项目，与主业时间重叠"],
            },
        ]
    )
    rating, _, _suggestion = _check_work_overlap(resume)
    assert rating == RATING_CONFORM


def test_work_overlap_na_with_single_interval() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.01 - 2020.12"}
        ]
    )
    assert _check_work_overlap(resume)[0] == RATING_NA


def test_overlapping_education_intervals_fail() -> None:
    resume = _resume(
        education=[
            {"id": 1, "institution": "甲大学", "degree": "本科", "years": "2018.09 - 2022.06"},
            {"id": 2, "institution": "乙大学", "degree": "硕士", "years": "2021.09 - 2024.06"},
        ]
    )
    rating, evidence, _suggestion = _check_education_overlap(resume)
    assert rating == RATING_NONCONFORM
    assert "重叠" in evidence


def test_overlapping_education_exempt_with_double_degree_note() -> None:
    resume = _resume(
        education=[
            {"id": 1, "institution": "甲大学", "degree": "本科", "years": "2018.09 - 2022.06"},
            {
                "id": 2,
                "institution": "乙大学",
                "degree": "双学位",
                "description": "联合培养双学位项目",
                "years": "2021.09 - 2022.06",
            },
        ]
    )
    assert _check_education_overlap(resume)[0] == RATING_CONFORM


def test_project_outside_work_tenure_fails_without_amateur_note() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.07 - 至今"}
        ],
        personalProjects=[
            {"id": 1, "name": "在校项目", "role": "开发", "years": "2019.03 - 2019.09"}
        ],
    )
    rating, evidence, _suggestion = _check_project_timeline(resume)
    assert rating == RATING_NONCONFORM
    assert "个人业余项目" in evidence


def test_project_outside_work_tenure_allowed_with_amateur_note() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.07 - 至今"}
        ],
        personalProjects=[
            {
                "id": 1,
                "name": "开源工具",
                "role": "作者",
                "years": "2019.03 - 2019.09",
                "description": ["【个人业余项目】个人开源作品"],
            }
        ],
    )
    assert _check_project_timeline(resume)[0] == RATING_CONFORM


def test_project_inside_work_tenure_conforms() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.07 - 至今"}
        ],
        personalProjects=[
            {"id": 1, "name": "交易中台", "role": "开发", "years": "2021.03 - 2021.12"}
        ],
    )
    assert _check_project_timeline(resume)[0] == RATING_CONFORM


def test_project_timeline_na_without_dated_projects() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.07 - 至今"}
        ],
        personalProjects=[{"id": 1, "name": "项目", "role": "开发"}],
    )
    assert _check_project_timeline(resume)[0] == RATING_NA


def test_work_start_before_highest_degree_enrollment_is_partial() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2014.07 - 2018.06"},
            {"id": 2, "company": "乙公司", "title": "工程师", "years": "2018.07 - 至今"},
        ],
        education=[
            {"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016.09 - 2020.06"}
        ],
    )
    rating, evidence, _suggestion = _check_work_education_order(resume)
    assert rating == RATING_PARTIAL
    assert "入学时间" in evidence


def test_work_start_after_degree_enrollment_conforms() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2020.07 - 至今"}
        ],
        education=[
            {"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016.09 - 2020.06"}
        ],
    )
    assert _check_work_education_order(resume)[0] == RATING_CONFORM


def test_work_start_before_in_service_degree_is_exempt() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "工程师", "years": "2014.07 - 至今"}
        ],
        education=[
            {
                "id": 1,
                "institution": "甲大学",
                "degree": "硕士（非全日制/在职）",
                "years": "2018.09 - 2021.06",
            }
        ],
    )
    assert _check_work_education_order(resume)[0] == RATING_CONFORM


def test_internship_before_degree_enrollment_does_not_trigger_order_check() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "Java 实习", "years": "2019.03 - 2019.09"},
            {"id": 2, "company": "乙公司", "title": "工程师", "years": "2020.07 - 至今"},
        ],
        education=[
            {"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016.09 - 2020.06"}
        ],
    )
    assert _check_work_education_order(resume)[0] == RATING_CONFORM


def test_stated_years_overstated_by_more_than_half_year_fails() -> None:
    resume = _resume(
        customSections={"basic_info": {"sectionType": "text", "text": "工作年限：10 年"}}
    )
    # 24 months actually employed (~2.0 years) vs claimed 10.
    rating, evidence, _suggestion = _check_stated_years(resume, 24)
    assert rating == RATING_NONCONFORM
    assert "10" in evidence and "2" in evidence


def test_stated_years_within_half_year_conforms() -> None:
    resume = _resume(
        customSections={"basic_info": {"sectionType": "text", "text": "工作年限：5 年"}}
    )
    assert _check_stated_years(resume, 58)[0] == RATING_CONFORM  # ~4.8y vs 5y


def test_missing_stated_years_is_na() -> None:
    assert _check_stated_years(_resume(), 60)[0] == RATING_NA


# --- item 14: stability RISK markers (never a veto) --------------------------


def test_current_gap_over_six_months_fails() -> None:
    facts = {
        "current_gap_months": 8,
        "historical_gap_months": 0,
        "largest_gap_months": 8,
        "stints": [1],
        "short_stints": [],
        "companies_last_5_years": ["甲公司"],
    }
    assert _check_gaps(facts)[0] == RATING_NONCONFORM


def test_gap_between_three_and_six_is_partial() -> None:
    facts = {
        "current_gap_months": 4,
        "historical_gap_months": 0,
        "largest_gap_months": 4,
        "stints": [1],
        "short_stints": [],
        "companies_last_5_years": [],
    }
    assert _check_gaps(facts)[0] == RATING_PARTIAL


def test_exactly_six_month_gap_is_partial_threshold_is_strict() -> None:
    facts = {
        "current_gap_months": 6,
        "historical_gap_months": 0,
        "largest_gap_months": 6,
        "stints": [1],
        "short_stints": [],
        "companies_last_5_years": [],
    }
    assert _check_gaps(facts)[0] == RATING_PARTIAL


def test_exactly_three_month_gap_conforms_threshold_is_strict() -> None:
    # Rubric: only a single gap STRICTLY longer than 3 months is a warning;
    # 3 months and below must stay silent (regression for the off-by-one).
    facts = {
        "current_gap_months": 3,
        "historical_gap_months": 0,
        "largest_gap_months": 3,
        "stints": [1],
        "short_stints": [],
        "companies_last_5_years": [],
    }
    rating, evidence, suggestion = _check_gaps(facts)
    assert rating == RATING_CONFORM
    assert evidence == "" and suggestion == ""


def test_short_gaps_do_not_combine_into_a_finding() -> None:
    # Two separate 2-month gaps make the cumulative total 4 months, but each
    # single segment is within the 3-month tolerance, so no finding is raised.
    facts = {
        "current_gap_months": 0,
        "historical_gap_months": 4,
        "largest_gap_months": 2,
        "stints": [1, 2, 3],
        "short_stints": [],
        "companies_last_5_years": [],
    }
    rating, evidence, suggestion = _check_gaps(facts)
    assert rating == RATING_CONFORM
    assert evidence == "" and suggestion == ""


def test_single_historical_gap_over_three_months_is_partial() -> None:
    facts = {
        "current_gap_months": 0,
        "historical_gap_months": 4,
        "largest_gap_months": 4,
        "stints": [1, 2],
        "short_stints": [],
        "companies_last_5_years": [],
    }
    assert _check_gaps(facts)[0] == RATING_PARTIAL


def test_timeline_two_short_gaps_stay_conform() -> None:
    # End-to-end through _timeline_facts: two separate 2-month gaps make the
    # cumulative total 4 months, but no single segment exceeds 3, so item 14's
    # gap checker stays silent (the open-ended last job pins current_gap at 0).
    intervals = [
        ("甲公司", Interval((2018, 1), (2018, 12), "2018.01-2018.12", "")),
        ("乙公司", Interval((2019, 3), (2019, 12), "2019.03-2019.12", "")),
        ("丙公司", Interval((2020, 3), None, "2020.03 至今", "")),
    ]
    facts = _timeline_facts(intervals)
    assert facts["current_gap_months"] == 0
    assert facts["historical_gap_months"] == 4
    assert facts["largest_gap_months"] == 2
    rating, evidence, suggestion = _check_gaps(facts)
    assert rating == RATING_CONFORM
    assert evidence == "" and suggestion == ""


def test_timeline_exactly_three_month_gap_conforms() -> None:
    # A single segment of exactly 3 months must stay at conform (strict >3 rule).
    intervals = [
        ("甲公司", Interval((2018, 1), (2018, 12), "2018.01-2018.12", "")),
        ("乙公司", Interval((2019, 4), None, "2019.04 至今", "")),
    ]
    facts = _timeline_facts(intervals)
    assert facts["largest_gap_months"] == 3
    assert _check_gaps(facts)[0] == RATING_CONFORM


def test_timeline_four_month_segment_is_partial() -> None:
    intervals = [
        ("甲公司", Interval((2018, 1), (2018, 12), "2018.01-2018.12", "")),
        ("乙公司", Interval((2019, 5), (2020, 12), "2019.05-2020.12", "")),
        ("丙公司", Interval((2021, 1), None, "2021.01 至今", "")),
    ]
    facts = _timeline_facts(intervals)
    assert facts["historical_gap_months"] == 4
    assert facts["largest_gap_months"] == 4
    assert _check_gaps(facts)[0] == RATING_PARTIAL


def test_four_job_hops_in_five_years_is_partial_risk_marker() -> None:
    # ≥4 hops is a 🟡 general risk, not a severe/redline finding.
    facts = {
        "stints": [1, 2, 3, 4],
        "companies_last_5_years": ["甲公司", "乙公司", "丙公司", "丁公司"],
        "short_stints": [],
    }
    rating, evidence, _suggestion = _check_job_hops(facts)
    assert rating == RATING_PARTIAL
    assert "4" in evidence and "变动较频繁" in evidence
    # The five-year observation window is an internal threshold.
    assert "5 年" not in evidence


def test_three_companies_in_five_years_still_conforms() -> None:
    facts = {
        "stints": [1, 2, 3],
        "companies_last_5_years": ["甲公司", "乙公司", "丙公司"],
        "short_stints": [],
    }
    rating, evidence, suggestion = _check_job_hops(facts)
    assert rating == RATING_CONFORM
    # Conforming signals stay silent even though the checker computes facts.
    assert evidence == "" and suggestion == ""


def test_job_hops_na_without_timeline() -> None:
    facts = {"stints": [], "companies_last_5_years": [], "short_stints": []}
    assert _check_job_hops(facts)[0] == RATING_NA


def test_short_stint_six_months_or_under_fails_as_risk() -> None:
    facts = {
        "stints": [1, 2],
        "short_stints": [
            {"company": "乙公司", "months": 3, "raw": "2023.01 - 2023.03"},
        ],
        "companies_last_5_years": ["甲公司", "乙公司"],
    }
    rating, evidence, _suggestion = _check_short_stints(facts)
    assert rating == RATING_NONCONFORM
    # Resume facts (company, actual length) yes; the internal band label no.
    assert "乙公司" in evidence and "3 个月" in evidence
    assert "半年以内" not in evidence


def test_short_stint_seven_to_twelve_months_is_partial() -> None:
    facts = {
        "stints": [1, 2],
        "short_stints": [
            {"company": "乙公司", "months": 9, "raw": "2023.01 - 2023.09"},
        ],
        "companies_last_5_years": ["甲公司", "乙公司"],
    }
    rating, evidence, _suggestion = _check_short_stints(facts)
    assert rating == RATING_PARTIAL
    assert "乙公司" in evidence and "9 个月" in evidence
    assert "7~12" not in evidence


def test_current_open_ended_job_excluded_from_short_stints() -> None:
    # The current job (open-ended) must never count as a short stint even when
    # it started recently — run_objective_checks builds short_stints accordingly;
    # here the checker simply sees none and conforms.
    facts = {
        "stints": [{"open_ended": True}],
        "short_stints": [],
        "companies_last_5_years": ["甲公司"],
    }
    assert _check_short_stints(facts)[0] == RATING_CONFORM


# --- item 16: privacy (the only red line) ------------------------------------


def test_id_card_number_detected() -> None:
    resume = _resume(
        personalInfo={"name": "王浩", "phone": "13800000000"},
        customSections={
            "basic_info": {"sectionType": "text", "text": "身份证号码：110101199003071234"}
        },
    )
    assert _check_privacy(resume)[0] == RATING_NONCONFORM


def test_privacy_scans_supplementary_original_resume_text() -> None:
    # Structured extraction dropped the ID number; the original-resume
    # transcription still carries it, and the red line must catch it.
    resume = _resume(personalInfo={"name": "王浩", "phone": "13800000000"})
    assert _check_privacy(resume)[0] == RATING_CONFORM
    rating, evidence, suggestion = _check_privacy(
        resume, supplementary_text="身份证号码：110101199003071234"
    )
    assert rating == RATING_NONCONFORM
    assert "身份证" in evidence and suggestion
    # Whitespace-only supplementary text changes nothing.
    assert _check_privacy(resume, supplementary_text="   ")[0] == RATING_CONFORM


def test_runner_privacy_dedupes_hits_across_json_and_original() -> None:
    sensitive = "家庭住址：上海市浦东新区世纪大道 100 号"
    resume = _resume(
        personalInfo={"name": "王浩", "phone": "13800000000"},
        customSections={"basic_info": {"sectionType": "text", "text": sensitive}},
    )
    # Same label token exists in structured data and in the original
    # transcription; it must be reported once, not twice.
    verdicts, _ = run_objective_checks(resume, supplementary_text="王浩 简历")
    verdicts_both, _ = run_objective_checks(
        resume, supplementary_text=f"王浩 简历\n{sensitive}"
    )
    assert verdicts_both[16][0] == RATING_NONCONFORM
    assert verdicts[16][1] == verdicts_both[16][1]
    assert verdicts_both[16][1].count("家庭住址") == 1


# --- point counter ----------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", 0),
        ("单一一句话优势", 1),
        ("1、第一点\n2、第二点\n3、第三点", 3),
        ("第一行\n第二行\n第三行\n第四行", 4),
    ],
)
def test_count_points(text: str, expected: int) -> None:
    assert count_points(text) == expected


# --- full runner -------------------------------------------------------------


def test_runner_covers_all_deterministic_items() -> None:
    # Without parseable tenure: 13 fixed objective items + optional modules
    # 11/12 objectively na (the bare fixture carries no certification/award
    # entries); item 15 (growth) is objectively na only below 5 effective dev
    # years and otherwise goes LLM.
    verdicts, facts = run_objective_checks(_resume())
    assert set(verdicts) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16}
    assert verdicts[11][0] == RATING_NA
    assert verdicts[12][0] == RATING_NA
    assert facts["certifications_training"] == []
    assert facts["awards"] == []
    assert isinstance(facts["tenure_years"], (float, type(None)))
    assert "target_title" not in facts  # only the service adds the target title


def test_optional_modules_go_to_llm_with_entries() -> None:
    # Non-empty certification / award lists are rendered modules: the
    # objective layer leaves 11/12 to the LLM and hands it the authoritative
    # entries (cleaned, stored order) via the facts packet.
    resume = _resume(
        additional={
            "technicalSkills": ["Java"],
            "certificationsTraining": [" OCP 认证 ", "", 123, None],
            "awards": ["公司技术之星"],
            "languages": ["英语四级"],
        }
    )
    verdicts, facts = run_objective_checks(resume)
    assert 11 not in verdicts
    assert 12 not in verdicts
    assert facts["certifications_training"] == ["OCP 认证"]
    assert facts["awards"] == ["公司技术之星"]
    assert facts["languages"] == ["英语四级"]


def test_optional_modules_na_when_additional_hidden() -> None:
    # The additional meta being visible gates all three render projections;
    # stored entries must not reach the LLM as module content when hidden.
    resume = _resume(
        additional={
            "certificationsTraining": ["OCP 认证"],
            "awards": ["公司技术之星"],
        },
        sectionMeta=[
            {"key": "personalInfo", "isVisible": True, "order": 0},
            {"key": "additional", "isVisible": False, "order": 3},
        ],
    )
    verdicts, facts = run_objective_checks(resume)
    assert verdicts[11][0] == RATING_NA
    assert verdicts[12][0] == RATING_NA
    assert facts["certifications_training"] == []
    assert facts["awards"] == []


def test_runner_marks_growth_na_below_five_years() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲", "title": "工程师", "years": "2022.01 至今"}
        ]
    )
    verdicts, _ = run_objective_checks(resume)
    assert verdicts[15][0] == RATING_NA
    # The five-year cutoff is an internal rule; evidence states the fact only.
    assert "有效开发年限" in verdicts[15][1] and "参考" in verdicts[15][1]
    assert "5 年" not in verdicts[15][1] and "按规则" not in verdicts[15][1]


def test_runner_leaves_growth_to_llm_at_five_plus_years() -> None:
    resume = _resume(
        workExperience=[
            {"id": 1, "company": "甲", "title": "工程师", "years": "2018.01 至今"}
        ]
    )
    verdicts, _ = run_objective_checks(resume)
    assert 15 not in verdicts


def test_objective_evidence_never_quotes_the_rubric() -> None:
    """Client-facing evidence describes the resume, not the internal rules."""
    # Banned vocabulary: rule language and every internal threshold/band.
    banned = (
        "红线",
        "检查项",
        "规范",
        "一票否决",
        "质检违规",
        "全局通用规则",
        "按规则",
        "≥",
        "2~5",
        "3~5",
        "8~15",
        "2~4",
        "1~3",
        "半年以内",
        "7~12",
        "5/9",
        "9/9",
        "近 5 年",
        "个主流栈",
    )
    sparse = _resume(
        personalInfo={"name": "王浩", "title": "Java 开发工程师"},
        summary="技" * 300,
        workExperience=[
            {"id": 1, "company": "乙公司", "title": "开发", "years": "2025.06 - 2025.09"},
        ],
        customSections={
            "basic_info": {"sectionType": "text", "text": "工作年限：10 年"},
        },
    )
    messy = _resume(
        personalInfo={"name": "张三", "phone": "123", "email": "bad", "title": "", "location": ""},
        summary="一句话",
        workExperience=[
            {"id": 1, "company": "甲公司", "title": "Java", "years": "2024.01 - 2024.03"},
            {"id": 2, "company": "乙公司", "title": "Java", "years": "2023.01 - 2024.06"},
            {"id": 3, "company": "丙公司", "title": "工程师", "years": "2022.01 - 2023.01"},
            {"id": 4, "company": "丁公司", "title": "工程师", "years": "2021.01 - 2022.01"},
        ],
        education=[{"id": 1, "institution": "乙大学", "years": "2019 - 2023.06"}],
        personalProjects=[{"id": 1, "name": "", "role": "", "description": ["做了一些开发工作"]}],
        additional={"technicalSkills": ["Java"]},
        sectionMeta=[
            {"key": "custom_1", "displayName": "自我评价", "isVisible": True, "order": 0}
        ],
        customSections={"custom_1": {"sectionType": "text", "text": "一条"}},
    )
    # Dirty legacy meta: scrambled order + duplicate titles + renamed default
    # + titled-but-empty optional blocks, so the new item-1 evidence strings
    # go through the same banned-vocabulary scan.
    dirty_meta = _resume(
        personalInfo={"name": "李四", "title": "后端工程师"},
        summary="一句正常长度的个人优势",
        education=[{"id": 1, "institution": "丙大学", "degree": "统招本科"}],
        workExperience=[
            {"id": 1, "company": "戊公司", "title": "开发", "years": "2020 - 2024"}
        ],
        sectionMeta=[
            {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
            {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 1},
            {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 2},
            {"key": "summary", "displayName": "我的故事", "isVisible": True, "order": 3},
            {"key": "custom_a", "displayName": "荣誉证书", "isVisible": True, "order": 4},
            {"key": "custom_b", "displayName": "荣誉证书", "isVisible": True, "order": 5},
            {"key": "custom_empty", "displayName": "兴趣爱好", "isVisible": True, "order": 6},
        ],
        customSections={
            "custom_a": {"sectionType": "text", "text": "证书内容"},
            "custom_b": {"sectionType": "text", "text": "更多证书"},
            "custom_empty": {"sectionType": "text", "text": ""},
        },
    )
    for resume in (sparse, messy, dirty_meta):
        verdicts, _facts = run_objective_checks(resume)
        for rating, evidence, suggestion in verdicts.values():
            for word in banned:
                assert word not in evidence, f"{word!r} leaked: {evidence}"
                assert word not in suggestion, f"{word!r} leaked: {suggestion}"
            if rating == RATING_CONFORM:
                assert evidence == "" and suggestion == ""
            elif rating in (RATING_PARTIAL, RATING_NONCONFORM):
                # Every problem row carries a matching fix; the fix must not
                # quote rule language either.
                assert suggestion, f"problem row without suggestion: {evidence}"


def test_runner_item1_carries_only_failing_signals() -> None:
    # Order conforms and paragraphs are fine, but governance finds a renamed
    # default -> item 1 is nonconform and must carry ONLY that finding and its
    # single matching fix (no positive notes about the sub-checks that passed).
    meta = [
        {"key": "personalInfo", "displayName": "基础信息", "isVisible": True, "order": 0},
        {"key": "education", "displayName": "教育背景", "isVisible": True, "order": 1},
        {"key": "summary", "displayName": "我的亮点", "isVisible": True, "order": 2},
        {"key": "additional", "displayName": "专业技能", "isVisible": True, "order": 3},
        {"key": "workExperience", "displayName": "工作经历", "isVisible": True, "order": 4},
        {"key": "personalProjects", "displayName": "项目经验", "isVisible": True, "order": 5},
    ]
    resume = _resume(
        sectionMeta=meta,
        summary="简短的个人优势",
        education=[{"id": 1, "degree": "统招本科"}],
    )
    verdicts, _facts = run_objective_checks(resume)
    rating, evidence, suggestion = verdicts[1]
    assert rating == RATING_NONCONFORM
    assert "默认区块标题被改为「我的亮点」" in evidence
    assert "实际顺序" not in evidence
    assert "标题无重复" not in evidence
    assert suggestion == "恢复被改区块的默认标题。"


def test_runner_item1_paragraph_alone_does_not_drag_in_order_or_governance() -> None:
    # The screenshot regression: order + governance pass but one paragraph is
    # oversized; the merged row must mention only the paragraph.
    resume = _resume(
        personalInfo={"name": "王浩", "title": "Java 工程师", "phone": "13800000000",
                      "email": "w@example.com", "location": "上海"},
        summary="技" * 400,
        education=[{"id": 1, "degree": "统招本科", "institution": "甲大学",
                    "description": "计算机", "years": "2016.09-2020.06"}],
        workExperience=[{"id": 1, "company": "甲", "title": "工程师", "years": "2020.07 至今"}],
        personalProjects=[
            {"id": 1, "name": "P1", "role": "开发",
             "description": ["项目背景：x", "Spring Boot MySQL", "负责开发", "提升 30%"]},
            {"id": 2, "name": "P2", "role": "开发",
             "description": ["业务背景：y", "RocketMQ Redis", "承担开发", "降低 40%"]},
        ],
        additional={"technicalSkills": [f"技能{i}" for i in range(9)]},
    )
    verdicts, _facts = run_objective_checks(resume)
    rating, evidence, suggestion = verdicts[1]
    assert rating == RATING_NONCONFORM
    assert "单段" in evidence
    assert "顺序" not in evidence and "标题" not in evidence
    assert "拆分" in suggestion
    assert "排列" not in suggestion and "恢复默认" not in suggestion


def test_runner_conform_rows_are_silent_problem_rows_have_fixes() -> None:
    resume = _resume(
        personalInfo={"name": "王浩", "phone": "13800000000", "email": "w@example.com",
                      "title": "Java 工程师", "location": "上海"},
        summary="1、大厂背景\n2、架构能力\n3、核心技术栈",
        education=[{"id": 1, "institution": "甲大学", "years": "2016.09 - 2020.06",
                    "degree": "本科（统招全日制）", "description": "计算机"}],
        workExperience=[{"id": 1, "company": "甲公司", "title": "Java 工程师",
                         "years": "2020.07 至今", "description": ["负责开发"]}],
        personalProjects=[
            {"id": 1, "name": "交易中台", "role": "核心开发",
             "description": ["项目背景：多系统对接", "技术栈 Spring Boot MySQL Redis Kafka",
                             "主导重构与开发", "耗时降低 40%"]},
            {"id": 2, "name": "营销系统", "role": "开发",
             "description": ["业务背景：配置困难", "基于 Spring Boot RocketMQ 设计",
                             "承担开发", "效率提升 60%"]},
        ],
        additional={"technicalSkills": [f"技能{i}" for i in range(10)]},
    )
    verdicts, _facts = run_objective_checks(resume)
    for item_id, triple in verdicts.items():
        rating, evidence, suggestion = triple
        if rating == RATING_CONFORM:
            assert evidence == "", f"item {item_id} conform evidence not empty"
            assert suggestion == "", f"item {item_id} conform suggestion not empty"
