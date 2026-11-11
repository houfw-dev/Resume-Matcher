"""Unit tests for pure parsing helpers in app.services.parser.

The LLM frequently drops months when parsing resume dates ("Jun 2020 - Aug 2021"
→ "2020 - 2021"). restore_dates_from_markdown() patches that back from the raw
markdown. This is pure, deterministic logic — the parser module was at ~20%
coverage with none of it exercised.
"""

import copy

import pytest
from unittest.mock import AsyncMock, patch

from app.services.parser import (
    _MAX_RESUME_CONTENT_RECURSION,
    _MD_NUMERIC_DATE_RE,
    _canonical_numeric_date,
    _extract_markdown_dates,
    _is_tech_stack_category_row,
    _recover_glyph_loss,
    _shows_glyph_loss,
    backfill_personal_info_from_markdown,
    canonicalize_date_period,
    dedupe_resume_lists,
    normalize_date_periods,
    extract_education_credentials,
    extract_misfiled_credentials,
    has_meaningful_resume_content,
    normalize_cjk_compat,
    normalize_cjk_compat_deep,
    normalize_item_sub_labels,
    normalize_text_hygiene,
    normalize_header_link_value,
    sanitize_header_fact_value,
    parse_resume_to_json,
    reconcile_custom_section_shapes,
    repair_project_label_regions,
    repair_project_tech_stack_rows,
    restore_dates_from_markdown,
    sort_timeline_sections_newest_first,
    split_blob_text_sections,
    strip_source_point_marker,
    strip_source_point_numbering,
)


def _wrap(value: object, levels: int) -> object:
    """Nest ``value`` inside ``levels`` plain dicts.

    ``has_meaningful_resume_content`` starts the recursion at depth 0 on the
    section value, so ``levels`` wrappers put the string at depth ``levels``.
    """
    for _ in range(levels):
        value = {"value": value}
    return value


class TestExtractMarkdownDates:
    def test_finds_full_range(self):
        assert _extract_markdown_dates("Worked Jun 2020 - Aug 2021 there") == ["Jun 2020 - Aug 2021"]

    def test_finds_present_range(self):
        assert _extract_markdown_dates("May 2021 - Present") == ["May 2021 - Present"]

    def test_finds_single_date(self):
        assert _extract_markdown_dates("Graduated Jun 2023") == ["Jun 2023"]

    def test_ignores_year_only(self):
        # Year-only "2020 - 2021" has no month token → not captured.
        assert _extract_markdown_dates("2020 - 2021") == []


class TestRestoreDatesFromMarkdown:
    def test_restores_months_in_work_experience(self):
        parsed = {"workExperience": [{"title": "Dev", "years": "2020 - 2021"}]}
        markdown = "Senior Dev, Jun 2020 - Aug 2021, built things"
        result = restore_dates_from_markdown(parsed, markdown)
        assert result["workExperience"][0]["years"] == "Jun 2020 - Aug 2021"

    def test_restores_single_date(self):
        parsed = {"education": [{"degree": "BS", "years": "2023"}]}
        markdown = "B.S. Computer Science, Jun 2023"
        result = restore_dates_from_markdown(parsed, markdown)
        assert result["education"][0]["years"] == "Jun 2023"

    def test_leaves_entries_that_already_have_months(self):
        parsed = {"workExperience": [{"years": "Jan 2020 - Mar 2021"}]}
        markdown = "Jun 2020 - Aug 2021"  # same years, different months
        result = restore_dates_from_markdown(parsed, markdown)
        # Already month-precise → must NOT be overwritten.
        assert result["workExperience"][0]["years"] == "Jan 2020 - Mar 2021"

    def test_no_markdown_dates_is_noop(self):
        parsed = {"workExperience": [{"years": "2020 - 2021"}]}
        result = restore_dates_from_markdown(parsed, "no dates here at all")
        assert result["workExperience"][0]["years"] == "2020 - 2021"

    def test_no_matching_year_key_is_noop(self):
        parsed = {"workExperience": [{"years": "2019 - 2020"}]}
        markdown = "Jun 2021 - Aug 2022"  # different years → no match
        result = restore_dates_from_markdown(parsed, markdown)
        assert result["workExperience"][0]["years"] == "2019 - 2020"

    def test_restores_in_custom_item_list_sections(self):
        parsed = {
            "customSections": {
                "volunteering": {
                    "sectionType": "itemList",
                    "items": [{"name": "Mentor", "years": "2020 - 2021"}],
                }
            }
        }
        markdown = "Mentor, Jun 2020 - Aug 2021"
        result = restore_dates_from_markdown(parsed, markdown)
        assert result["customSections"]["volunteering"]["items"][0]["years"] == "Jun 2020 - Aug 2021"

    def test_tolerates_missing_sections(self):
        # Should not raise on a minimal/odd structure.
        parsed = {"personalInfo": {"name": "X"}}
        assert restore_dates_from_markdown(parsed, "Jun 2020 - Aug 2021") == parsed

    def test_skips_non_dict_entries(self):
        parsed = {"workExperience": ["not a dict", {"years": "2020 - 2021"}]}
        markdown = "Jun 2020 - Aug 2021"
        result = restore_dates_from_markdown(parsed, markdown)
        assert result["workExperience"][1]["years"] == "Jun 2020 - Aug 2021"


# Spaced CJK labels mirror real markitdown output ("姓    名：旷武").
_HEADER_MARKDOWN = """◆基本资料
姓    名：旷武             性    别：男\t     \t            年    龄：35
工作年限：8年              学    历：统招本科(211)           外语水平：英语六级
联系电话：15274975169       邮    箱：996927744@qq.com      求职意向：资深开发

◆教育背景
2010.09-2014.06  南京航空航天大学  电子信息科学与技术  统招本科
"""


class TestBackfillPersonalInfoFromMarkdown:
    def test_recovers_spaced_header_demographics(self):
        parsed: dict = {"personalInfo": {"name": "旷武"}}
        result = backfill_personal_info_from_markdown(parsed, _HEADER_MARKDOWN)
        info = result["personalInfo"]
        assert info["gender"] == "男"
        assert info["age"] == "35"
        assert info["workYears"] == "8年"
        assert info["educationLevel"] == "统招本科(211)"
        assert info["title"] == "资深开发"
        assert info["phone"] == "15274975169"
        assert info["email"] == "996927744@qq.com"
        assert result["additional"]["languages"] == ["英语六级"]

    def test_demographics_win_over_stripped_llm_value(self):
        # Source says "统招本科(211)"; the LLM must not be allowed to reduce
        # it to "本科". Contact fields keep LLM values when already present.
        parsed = {
            "personalInfo": {
                "gender": "男",
                "age": "35",
                "workYears": "8年",
                "educationLevel": "本科",
                "phone": "999",
                "email": "kept@example.com",
                "title": "LLM Title",
            }
        }
        result = backfill_personal_info_from_markdown(parsed, _HEADER_MARKDOWN)
        info = result["personalInfo"]
        assert info["educationLevel"] == "统招本科(211)"
        assert info["phone"] == "999"
        assert info["email"] == "kept@example.com"
        assert info["title"] == "LLM Title"

    def test_unions_languages_without_duplicates(self):
        parsed = {
            "personalInfo": {},
            "additional": {"languages": ["英语六级"], "technicalSkills": []},
        }
        markdown = "性别：男\n外语水平：英语六级，日语N2\n\n◆工作经历\n"
        result = backfill_personal_info_from_markdown(parsed, markdown)
        assert result["additional"]["languages"] == ["英语六级", "日语N2"]

    def test_header_scan_stops_at_first_section_heading(self):
        # A 学历 label inside the body must not override the header value.
        markdown = (
            "学    历：统招本科(211)\n\n"
            "◆工作经历\n2020 - 2021 某公司\n学历：硕士（岗位描述文字）\n"
        )
        parsed = {"personalInfo": {"educationLevel": "统招本科(211)"}}
        result = backfill_personal_info_from_markdown(parsed, markdown)
        assert result["personalInfo"]["educationLevel"] == "统招本科(211)"

    def test_label_words_inside_values_are_ignored(self):
        # "电话销售" embedded in the 求职意向 value is not a phone label.
        markdown = "求职意向：电话销售专员\n联系电话：13800000000\n\n◆工作经历\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        info = result["personalInfo"]
        assert info["title"] == "电话销售专员"
        assert info["phone"] == "13800000000"

    def test_table_cell_separators(self):
        markdown = "| 姓名 | 旷武 | 性别 | 男 | 年龄 | 35岁 |\n\n◆教育背景\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        info = result["personalInfo"]
        assert info["name"] == "旷武"
        assert info["gender"] == "男"
        assert info["age"] == "35岁"

    def test_no_header_is_noop(self):
        parsed: dict = {"personalInfo": {"gender": "", "educationLevel": ""}}
        result = backfill_personal_info_from_markdown(
            parsed, "◆工作经历\n2020 - 2021 某公司 开发工程师"
        )
        assert result["personalInfo"] == {"gender": "", "educationLevel": ""}
        assert "additional" not in result

    def test_blog_label_ends_work_years_span_and_backfills_website(self):
        # Real upload (resume de8ce72b): an unrecognized "博客地址：" cell used
        # to glue its Markdown link onto the verbatim workYears value.
        markdown = (
            "性 别：男 联系电话：15222165957 邮箱：3398905445@qq.com\n"
            "工作年限：13年 博客地址：[fengba.blog.csdn.net]"
            "(https://fengba.blog.csdn.net/)\n\n"
            "**教育背景**\n陕西科技大学\n"
        )
        parsed: dict = {"personalInfo": {}}
        result = backfill_personal_info_from_markdown(parsed, markdown)
        info = result["personalInfo"]
        assert info["workYears"] == "13年"
        assert info["website"] == "https://fengba.blog.csdn.net/"

    def test_existing_llm_website_is_not_overwritten(self):
        markdown = (
            "工作年限：13年 博客地址：[fengba.blog.csdn.net]"
            "(https://fengba.blog.csdn.net/)\n\n◆教育背景\n"
        )
        parsed = {"personalInfo": {"website": "https://llm-kept.example.com"}}
        result = backfill_personal_info_from_markdown(parsed, markdown)
        assert result["personalInfo"]["website"] == "https://llm-kept.example.com"
        assert result["personalInfo"]["workYears"] == "13年"

    def test_bare_url_glued_to_work_years_is_truncated(self):
        markdown = "工作年限：13年 https://fengba.blog.csdn.net/\n\n◆教育背景\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        assert result["personalInfo"]["workYears"] == "13年"

    def test_embedded_spaced_label_glued_to_education_level_is_truncated(self):
        # Real uploads (resume a3902761): next table cell "学 校：…" glued on.
        markdown = "学 历：本科 学 校： 西安电子科技大学\n\n◆教育背景\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        assert result["personalInfo"]["educationLevel"] == "本科"

    def test_linkedin_and_github_header_cells_are_backfilled(self):
        markdown = (
            "领英：[Wang Hao](https://www.linkedin.com/in/wanghao) "
            "GitHub：github.com/wanghao\n\n◆工作经历\n"
        )
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        info = result["personalInfo"]
        assert info["linkedin"] == "https://www.linkedin.com/in/wanghao"
        # Bare hosts pass through: the render layer promotes them to https://.
        assert info["github"] == "github.com/wanghao"

    def test_english_website_label_is_recognized(self):
        markdown = "Website: [blog](https://example.com/blog)\n\n◆工作经历\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        assert result["personalInfo"]["website"] == "https://example.com/blog"

    def test_fact_values_with_internal_punctuation_survive(self):
        # No colon/link inside a legitimate fact: comma-qualified values stay.
        markdown = "工作年限：5年大型医院项目，3年电商\n\n◆工作经历\n"
        result = backfill_personal_info_from_markdown({"personalInfo": {}}, markdown)
        assert result["personalInfo"]["workYears"] == "5年大型医院项目，3年电商"


class TestSanitizeHeaderFactValue:
    def test_truncates_markdown_link_glue(self):
        value = "13年 博客地址：[fengba.blog.csdn.net](https://fengba.blog.csdn.net/)"
        assert sanitize_header_fact_value(value) == "13年"

    def test_truncates_bare_url_glue(self):
        assert sanitize_header_fact_value("13年 https://fengba.blog.csdn.net/") == "13年"

    def test_truncates_embedded_spaced_label(self):
        assert sanitize_header_fact_value("本科 学 校： 西安电子科技大学") == "本科"

    def test_clean_values_are_unchanged(self):
        for value in ("男", "35岁", "8年", "统招本科(211)", "5年大型医院项目，3年电商"):
            assert sanitize_header_fact_value(value) == value


class TestNormalizeHeaderLinkValue:
    def test_markdown_link_collapses_to_url_target(self):
        assert (
            normalize_header_link_value(
                "[fengba.blog.csdn.net](https://fengba.blog.csdn.net/)"
            )
            == "https://fengba.blog.csdn.net/"
        )

    def test_bare_url_embedded_in_prose_is_extracted(self):
        assert (
            normalize_header_link_value("see https://example.com/x here")
            == "https://example.com/x"
        )

    def test_plain_host_passes_through(self):
        assert normalize_header_link_value("github.com/wanghao") == "github.com/wanghao"

    def test_empty_target_falls_back_to_bracket_text(self):
        assert normalize_header_link_value("[my-blog]()") == "my-blog"


class TestHeaderFactSelfHealOnHygiene:
    def test_hygiene_heals_glued_facts_and_links_from_stored_resumes(self):
        # Exact shapes found in stored uploads: no raw markdown is available at
        # read time, so hygiene must repair them without a re-parse.
        parsed = {
            "personalInfo": {
                "workYears": "13年 博客地址：[fengba.blog.csdn.net]"
                "(https://fengba.blog.csdn.net/)",
                "educationLevel": "本科 学 校： 西安电子科技大学",
                "website": "[fengba.blog.csdn.net](https://fengba.blog.csdn.net/)",
            }
        }
        result = normalize_text_hygiene(copy.deepcopy(parsed))
        info = result["personalInfo"]
        assert info["workYears"] == "13年"
        assert info["educationLevel"] == "本科"
        assert info["website"] == "https://fengba.blog.csdn.net/"

    def test_hygiene_heal_is_idempotent(self):
        parsed = {
            "personalInfo": {
                "workYears": "13年 博客地址：[fengba.blog.csdn.net]"
                "(https://fengba.blog.csdn.net/)"
            }
        }
        once = normalize_text_hygiene(copy.deepcopy(parsed))
        twice = normalize_text_hygiene(copy.deepcopy(once))
        assert once == twice
        assert once["personalInfo"]["workYears"] == "13年"


class TestSortTimelineSectionsNewestFirst:
    def test_orders_work_by_start_date_desc(self):
        parsed = {
            "workExperience": [
                {"company": "Old", "years": "2018.05 - 2020.11"},
                {"company": "New", "years": "2020.12 - 2026.04"},
            ]
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["company"] for e in result["workExperience"]] == ["New", "Old"]

    def test_orders_education_by_start_date_desc(self):
        parsed = {
            "education": [
                {"institution": "Bachelor", "years": "2010.09-2014.06"},
                {"institution": "Master", "years": "2014.09 - 2017.06"},
            ]
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["institution"] for e in result["education"]] == [
            "Master",
            "Bachelor",
        ]

    def test_understands_english_months_and_present(self):
        parsed = {
            "workExperience": [
                {"company": "Earlier", "years": "Jun 2020 - Aug 2021"},
                {"company": "Current", "years": "May 2021 - Present"},
            ]
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["company"] for e in result["workExperience"]] == [
            "Current",
            "Earlier",
        ]

    def test_undated_entries_sink_but_keep_relative_order(self):
        parsed = {
            "workExperience": [
                {"company": "A", "years": "2010 - 2012"},
                {"company": "Undated1", "years": ""},
                {"company": "B", "years": "2020 - 2022"},
                {"company": "Undated2"},
            ]
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["company"] for e in result["workExperience"]] == [
            "B",
            "A",
            "Undated1",
            "Undated2",
        ]

    def test_already_sorted_and_single_entry_stable(self):
        parsed = {
            "workExperience": [
                {"company": "A", "years": "2020.01 - 2021.01"},
                {"company": "B", "years": "2018.01 - 2019.01"},
            ],
            "education": [{"institution": "Only", "years": "2010 - 2014"}],
            "personalProjects": [
                {"name": "P1"},
                {"name": "P2"},
            ],
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["company"] for e in result["workExperience"]] == ["A", "B"]
        assert [e["institution"] for e in result["education"]] == ["Only"]
        # Projects are explicitly out of scope.
        assert [e["name"] for e in result["personalProjects"]] == ["P1", "P2"]

    def test_chinese_month_format(self):
        parsed = {
            "workExperience": [
                {"company": "Old", "years": "2018年5月 - 2020年11月"},
                {"company": "New", "years": "2020年12月 - 至今"},
            ]
        }
        result = sort_timeline_sections_newest_first(parsed)
        assert [e["company"] for e in result["workExperience"]] == ["New", "Old"]


class TestNormalizeItemSubLabels:
    def test_standalone_label_marked_label_even_when_model_numbers_it(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目治理：", "跟进风险与交付节奏。"],
                    "descriptionStyles": ["bullet", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["项目治理：", "跟进风险与交付节奏。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_merged_known_label_is_split_into_label_and_content(self):
        # 系统架构 is a split candidate that keeps its verbatim name (it is not
        # one of the 技术栈 aliases).
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["系统架构：Spring AI + Java 17；Redis Cluster。"],
                    "descriptionStyles": ["plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            "系统架构：",
            "Spring AI + Java 17；Redis Cluster。",
        ]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_split_content_row_keeps_bullet_style(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["责任描述：负责核心交易链路。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["责任描述：", "负责核心交易链路。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_mid_sentence_colon_in_duty_row_is_not_split(self):
        duty = "设计并落地多阶段对话编排管道：租户隔离识别 → 情绪分析。"
        parsed = {
            "personalProjects": [
                {"name": "P", "description": [duty], "descriptionStyles": ["bullet"]}
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["description"] == [duty]
        assert result["personalProjects"][0]["descriptionStyles"] == ["bullet"]

    def test_unknown_standalone_label_is_forced_label(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["特殊板块：", "保留原始排版的内容。"],
                    "descriptionStyles": ["bullet", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_spaced_latin_prefixed_standalone_label_is_forced_label(self):
        # The model rewrites "cpu飙升问题：" as "CPU 飙升问题：" (space after the
        # latin prefix); it must still be recognized as a nested head row.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["CPU 飙升问题：", "定位并优化慢查询。"],
                    "descriptionStyles": ["plain", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_source_numbering_prefix_on_label_row_is_dropped(self):
        parsed = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["1、工作职责：", "完成日常开发。"],
                    "descriptionStyles": ["bullet", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["workExperience"][0]
        assert item["description"] == ["工作职责：", "完成日常开发。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_custom_item_list_sections_are_normalized(self):
        parsed = {
            "customSections": {
                "volunteer": {
                    "sectionType": "itemList",
                    "items": [
                        {
                            "title": "V",
                            "description": ["项目职责：组织线下活动。"],
                            "descriptionStyles": ["bullet"],
                        }
                    ],
                }
            }
        }
        result = normalize_item_sub_labels(parsed)
        item = result["customSections"]["volunteer"]["items"][0]
        assert item["description"] == ["项目职责：", "组织线下活动。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_missing_styles_default_and_no_change_returns_same_rows(self):
        parsed = {
            "personalProjects": [
                {"name": "P", "description": ["完成需求评审。", "修复线上问题。"]}
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["完成需求评审。", "修复线上问题。"]
        assert "descriptionStyles" not in item

    def test_tolerates_malformed_sections(self):
        parsed = {
            "personalProjects": None,
            "workExperience": [None, "company"],
            "customSections": {"broken": "oops"},
        }
        assert normalize_item_sub_labels(parsed)["personalProjects"] is None


class TestCanonicalizeProjectSubLabels:
    def test_duty_aliases_rename_to_project_duty(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "工作职责：",
                        "负责核心交易链路。",
                        "负责内容：",
                        "保障线上稳定。",
                    ],
                    "descriptionStyles": ["label", "bullet", "label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            "项目职责：",
            "负责核心交易链路。",
            "项目职责：",
            "保障线上稳定。",
        ]
        assert item["descriptionStyles"] == ["label", "bullet", "label", "bullet"]

    @pytest.mark.parametrize(
        "alias",
        [
            "项目职责与成果",
            "项目职责和成果",
            "项目职责及成果",
            "工作职责与成果",
            "职责与成果",
            "核心职责与成果",
        ],
    )
    def test_combined_duty_result_aliases_rename_to_project_duty(self, alias: str):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{alias}：", "负责核心模块，QPS 提升 10 倍。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            "项目职责：",
            "负责核心模块，QPS 提升 10 倍。",
        ]
        assert item["descriptionStyles"] == ["label", "bullet"]

    @pytest.mark.parametrize(
        "alias",
        ["项目成果", "技术亮点", "技术难点", "难点与解决", "技术难点及亮点"],
    )
    def test_highlight_aliases_rename_to_project_highlight(self, alias: str):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{alias}：", "性能提升 30%。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["项目亮点：", "性能提升 30%。"]

    @pytest.mark.parametrize(
        "alias",
        ["项目概述", "业务背景", "项目简介", "需求背景", "项目概况", "项目介绍"],
    )
    def test_background_aliases_rename_to_project_background(self, alias: str):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{alias}：", "面向多子系统重复建设问题。"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["项目背景：", "面向多子系统重复建设问题。"]
        assert item["descriptionStyles"] == ["label", "plain"]

    @pytest.mark.parametrize(
        "alias",
        ["技术选型", "技术架构", "所用技术", "技术清单", "技术列表"],
    )
    def test_tech_aliases_rename_to_tech_stack(self, alias: str):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{alias}：", "Spring Boot + Redis + Kafka。"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["技术栈：", "Spring Boot + Redis + Kafka。"]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_project_description_label_is_not_renamed(self):
        # 项目描述 shares the descriptive layout but is NOT a user-facing
        # alias, so its name stays verbatim.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目描述：", "内部考勤与门禁平台。"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["description"] == [
            "项目描述：",
            "内部考勤与门禁平台。",
        ]

    def test_rename_applies_to_split_inline_label_including_core_work(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["核心工作：搭建对账平台。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["项目职责：", "搭建对账平台。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_colon_less_label_style_row_is_renamed_without_added_colon(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["负责内容", "推进需求落地。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["description"] == [
            "项目职责",
            "推进需求落地。",
        ]

    def test_ascii_colon_is_preserved(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目成果:", "QPS 翻倍。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["description"] == [
            "项目亮点:",
            "QPS 翻倍。",
        ]

    def test_work_experience_labels_are_not_renamed(self):
        parsed = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["工作职责：", "完成日常开发。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["workExperience"][0]
        assert item["description"] == ["工作职责：", "完成日常开发。"]

    def test_custom_item_list_labels_are_not_renamed(self):
        parsed = {
            "customSections": {
                "volunteer": {
                    "sectionType": "itemList",
                    "items": [
                        {
                            "title": "V",
                            "description": ["负责内容：", "组织线下活动。"],
                            "descriptionStyles": ["label", "bullet"],
                        }
                    ],
                }
            }
        }
        result = normalize_item_sub_labels(parsed)
        item = result["customSections"]["volunteer"]["items"][0]
        assert item["description"] == ["负责内容：", "组织线下活动。"]

    def test_non_alias_labels_keep_verbatim(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目治理：", "推进风险闭环。"],
                    "descriptionStyles": ["label", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["description"] == [
            "项目治理：",
            "推进风险闭环。",
        ]

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("个人职责", "项目职责"),
            ("项目责任", "项目职责"),
            ("个人职责与成果", "项目职责"),
            ("个人成果", "项目亮点"),
        ],
    )
    def test_personal_phrasing_aliases_rename_to_canonical(
        self, alias: str, canonical: str
    ):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{alias}：", "负责核心模块，QPS 提升 10 倍。"],
                    "descriptionStyles": ["plain", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            f"{canonical}：",
            "负责核心模块，QPS 提升 10 倍。",
        ]
        # A plain-styled alias heading is promoted to a bold label row.
        assert item["descriptionStyles"] == ["label", "plain"]

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("个人职责", "项目职责"),
            ("项目责任", "项目职责"),
            ("项目成果", "项目亮点"),
            ("负责内容", "项目职责"),
        ],
    )
    def test_bare_colon_less_alias_with_plain_style_is_renamed_and_promoted(
        self, alias: str, canonical: str
    ):
        # Real uploads contain bare ("个人职责") rows emitted with the plain
        # style: the module boundary must be restored without inventing a colon.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [alias, "推进需求落地与线上保障。"],
                    "descriptionStyles": ["plain", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [canonical, "推进需求落地与线上保障。"]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_numbered_bare_alias_row_is_unnumbered_renamed_and_promoted(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["1、项目责任", "牵头核心链路重构。"],
                    "descriptionStyles": ["bullet", "bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == ["项目职责", "牵头核心链路重构。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_glued_personal_duty_label_is_split_and_renamed(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["个人职责：负责核心调度模块的设计与落地。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            "项目职责：",
            "负责核心调度模块的设计与落地。",
        ]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_sentence_containing_alias_words_is_not_treated_as_heading(self):
        duty = "个人职责覆盖核心交易链路，同时牵头稳定性治理。"
        parsed = {
            "personalProjects": [
                {"name": "P", "description": [duty], "descriptionStyles": ["bullet"]}
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [duty]
        assert item["descriptionStyles"] == ["bullet"]


class TestProjectDescriptiveRowsArePlain:
    # (source label, canonical label after rename) — covers every name in
    # PROJECT_INLINE_PLAIN_LABELS, including the three that stay verbatim.
    @pytest.mark.parametrize(
        "label,canonical",
        [
            ("项目简介", "项目背景"),
            ("项目描述", "项目描述"),
            ("项目概况", "项目背景"),
            ("项目背景", "项目背景"),
            ("项目概述", "项目背景"),
            ("业务背景", "项目背景"),
            ("需求背景", "项目背景"),
            ("项目介绍", "项目背景"),
            ("技术架构", "技术栈"),
            ("系统架构", "系统架构"),
            ("架构说明", "架构说明"),
            ("技术栈", "技术栈"),
            ("技术列表", "技术栈"),
            ("技术选型", "技术栈"),
            ("所用技术", "技术栈"),
            ("技术清单", "技术栈"),
        ],
    )
    def test_glued_descriptive_content_is_forced_plain_in_projects(
        self, label: str, canonical: str
    ):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{label}：面向家庭宽带装维场景，SpringAI + RAG。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            f"{canonical}：",
            "面向家庭宽带装维场景，SpringAI + RAG。",
        ]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_plain_input_for_descriptive_content_stays_plain(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术架构：Spring AI、Redis Cluster。"],
                    "descriptionStyles": ["plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["descriptionStyles"] == ["label", "plain"]

    def test_descriptive_force_plain_is_project_scoped(self):
        # Work-experience entries keep the model's style on split content.
        parsed = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["技术架构：主导交易系统重构。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["workExperience"][0]
        assert item["description"] == ["技术架构：", "主导交易系统重构。"]
        assert item["descriptionStyles"] == ["label", "bullet"]

    def test_duty_label_split_content_keeps_bullet_style(self):
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目职责：负责核心调度模块。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        assert result["personalProjects"][0]["descriptionStyles"] == ["label", "bullet"]


class TestOutcomeSubLabelsStayPeerModules:
    """成效/效果 modules are peers of 项目亮点， never its nested sub-heads.

    The vocabulary lives in parser._SUB_LABEL_CANDIDATES (mirrored by
    resume_docx._SUB_LABEL_CANDIDATES and the frontend SUB_LABEL_CANDIDATES
    set). It must NOT be added to PROJECT_SUB_LABEL_CANONICAL: outcome labels
    keep their verbatim names instead of being renamed to 项目亮点.
    """

    @pytest.mark.parametrize(
        "label",
        [
            "项目成效",
            "工作成效",
            "实施成效",
            "建设成效",
            "应用成效",
            "业务成效",
            "落地成效",
            "实际成效",
            "量化成效",
            "运营成效",
            "项目效果",
            "实施效果",
            "应用效果",
            "落地效果",
            "运行效果",
            "实际效果",
        ],
    )
    def test_glued_outcome_label_is_split_but_kept_verbatim(self, label: str):
        # The inline-split regex is fed by _SUB_LABEL_CANDIDATES: without the
        # outcome vocabulary the glued row would survive as one content row.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [f"{label}：错报率下降约 70%，客服工作量明显下降。"],
                    "descriptionStyles": ["plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            f"{label}：",
            "错报率下降约 70%，客服工作量明显下降。",
        ]
        assert item["descriptionStyles"] == ["label", "plain"]

    def test_standalone_outcome_label_is_forced_label_style_without_rename(self):
        # Real upload (resume de8ce72b): 项目亮点 and 项目成效 are same-level
        # headings. A weak model may store the label row as a plain/bullet row;
        # the repair promotes it to "label" and never renames it.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目亮点：",
                        "用 Spark SQL 构建两层校验规则。",
                        "项目成效：",
                        "平台稳定支撑多家机构报送，错报率下降约 70%。",
                    ],
                    "descriptionStyles": ["label", "bullet", "plain", "plain"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["personalProjects"][0]
        assert item["description"] == [
            "项目亮点：",
            "用 Spark SQL 构建两层校验规则。",
            "项目成效：",
            "平台稳定支撑多家机构报送，错报率下降约 70%。",
        ]
        assert item["descriptionStyles"] == ["label", "bullet", "label", "plain"]

    def test_work_entry_outcome_label_glued_row_is_split_without_canonical_map(self):
        # Work entries get no canonical rename, but the inline split still
        # applies because the outcome names are curated sub-labels.
        parsed = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["工作成效：交付周期缩短 40%。"],
                    "descriptionStyles": ["bullet"],
                }
            ]
        }
        result = normalize_item_sub_labels(parsed)
        item = result["workExperience"][0]
        assert item["description"] == ["工作成效：", "交付周期缩短 40%。"]
        assert item["descriptionStyles"] == ["label", "bullet"]


class TestExtractProjectHeaderFields:
    def test_inline_scale_and_role_rows_move_to_header_fields(self):
        from app.services.parser import extract_project_header_fields

        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "role": "",
                    "scale": "",
                    "description": [
                        "项目规模：20人团队 / 千万级用户",
                        "项目角色：核心开发",
                        "负责核心交易链路。",
                    ],
                    "descriptionStyles": ["bullet", "bullet", "bullet"],
                }
            ]
        }
        result = extract_project_header_fields(parsed)
        item = result["personalProjects"][0]
        assert item["scale"] == "20人团队 / 千万级用户"
        assert item["role"] == "核心开发"
        assert item["description"] == ["负责核心交易链路。"]
        assert item["descriptionStyles"] == ["bullet"]

    def test_does_not_overwrite_existing_header_fields(self):
        from app.services.parser import extract_project_header_fields

        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "role": "技术负责人",
                    "description": ["项目角色：参与者", "负责核心交易链路。"],
                    "descriptionStyles": ["bullet", "bullet"],
                }
            ]
        }
        result = extract_project_header_fields(parsed)
        item = result["personalProjects"][0]
        assert item["role"] == "技术负责人"
        assert item["description"] == [
            "项目角色：参与者",
            "负责核心交易链路。",
        ]

    def test_missing_styles_are_tolerated(self):
        from app.services.parser import extract_project_header_fields

        parsed = {
            "personalProjects": [
                {"name": "P", "description": ["团队规模：10人", "完成需求评审。"]}
            ]
        }
        item = extract_project_header_fields(parsed)["personalProjects"][0]
        assert item["scale"] == "10人"
        assert item["description"] == ["完成需求评审。"]
        assert item["descriptionStyles"] == ["bullet"]


class TestRepairProjectTechStackRows:
    """Split per-token 技术栈 rows join back into one plain line and standalone
    URL rows lift into the project website/github header fields."""

    def test_split_flat_stack_joins_and_lifts_website_url(self) -> None:
        # The real Forest upload: one inline 技术栈 line plus a standalone URL
        # line, stored by the weak model as seven separate plain rows.
        parsed = {
            "personalProjects": [
                {
                    "name": "Forest",
                    "description": [
                        "技术栈：",
                        "Java",
                        "Kotlin",
                        "Spring Boot",
                        "Solon",
                        "OkHttp",
                        "HttpClient",
                        "https://forest.dtflyx.com",
                        "项目职责：",
                        "负责核心框架设计。",
                    ],
                    "descriptionStyles": [
                        "label",
                        "plain",
                        "plain",
                        "plain",
                        "plain",
                        "plain",
                        "plain",
                        "plain",
                        "label",
                        "bullet",
                    ],
                }
            ]
        }
        result = repair_project_tech_stack_rows(parsed)
        project = result["personalProjects"][0]
        assert project["website"] == "https://forest.dtflyx.com"
        assert project.get("github") is None
        assert project["description"] == [
            "技术栈：",
            "Java、Kotlin、Spring Boot、Solon、OkHttp、HttpClient",
            "项目职责：",
            "负责核心框架设计。",
        ]
        assert project["descriptionStyles"] == ["label", "plain", "label", "bullet"]

    def test_github_url_routes_to_github_field(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "ShakeInk",
                    "description": [
                        "技术栈：",
                        "Kotlin",
                        "Compose Desktop",
                        "https://github.com/mySingleLive/shakeink-desktop",
                    ],
                    "descriptionStyles": ["label", "plain", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["github"] == (
            "https://github.com/mySingleLive/shakeink-desktop"
        )
        assert project.get("website") is None
        assert project["description"] == [
            "技术栈：",
            "Kotlin、Compose Desktop",
        ]
        assert project["descriptionStyles"] == ["label", "plain"]

    def test_markdown_link_row_collapses_to_url_target(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "技术栈：",
                        "Java",
                        "[Forest 官网](https://forest.dtflyx.com)",
                    ],
                    "descriptionStyles": ["label", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["website"] == "https://forest.dtflyx.com"
        assert project["description"] == ["技术栈：", "Java"]
        assert project["descriptionStyles"] == ["label", "plain"]

    def test_trailing_punctuation_on_bare_url_is_trimmed(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术栈：", "Java", "https://forest.dtflyx.com。"],
                    "descriptionStyles": ["label", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["website"] == "https://forest.dtflyx.com"

    def test_existing_header_field_is_never_overwritten(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "github": "https://github.com/keep/existing",
                    "description": [
                        "技术栈：",
                        "Java",
                        "https://github.com/another/repo",
                    ],
                    "descriptionStyles": ["label", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["github"] == "https://github.com/keep/existing"
        # The unroutable URL stays visible inside the joined tech-stack body.
        assert project["description"] == [
            "技术栈：",
            "Java、https://github.com/another/repo",
        ]

    def test_second_url_targeting_same_field_stays_in_body(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "技术栈：",
                        "Java",
                        "https://github.com/org/first",
                        "https://github.com/org/second",
                    ],
                    "descriptionStyles": ["label", "plain", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["github"] == "https://github.com/org/first"
        assert project["description"] == [
            "技术栈：",
            "Java、https://github.com/org/second",
        ]

    def test_structured_category_stack_keeps_row_boundaries(self) -> None:
        # "后端：…" is a structured category row: the renderer/DOCX exporter
        # number one row per category, so joining would destroy that layout.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "技术栈：",
                        "后端：Java 17、Spring Boot",
                        "Redis",
                        "https://example.com/docs",
                        "项目职责：",
                        "负责架构。",
                    ],
                    "descriptionStyles": [
                        "label",
                        "plain",
                        "plain",
                        "plain",
                        "label",
                        "bullet",
                    ],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["website"] == "https://example.com/docs"
        assert project["description"] == [
            "技术栈：",
            "后端：Java 17、Spring Boot",
            "Redis",
            "项目职责：",
            "负责架构。",
        ]
        assert project["descriptionStyles"] == [
            "label",
            "plain",
            "plain",
            "label",
            "bullet",
        ]

    def test_standalone_url_rows_never_count_as_category(self) -> None:
        # "https://…" matches the short-colon shape by accident (prefix
        # "https" + colon): a URL is a link, never a 分类：… enumeration row.
        # Without the guard the unroutable URL would force the structured
        # (no-join) branch and break the flat-stack merge.
        assert _is_tech_stack_category_row("https://github.com/org/repo") is False
        assert _is_tech_stack_category_row("http://example.com/docs") is False
        assert _is_tech_stack_category_row("www.example.com") is False
        assert _is_tech_stack_category_row("[Forest](https://forest.dtflyx.com)") is False
        # The guard must not blunt real category detection.
        assert _is_tech_stack_category_row("后端：Java 17、Spring Boot") is True
        assert _is_tech_stack_category_row("数据库：MySQL、Redis") is True

    def test_ascii_token_stack_under_chinese_label_uses_enumeration_comma(self) -> None:
        # The 技术栈 label is Chinese-context: even all-ASCII token names join
        # with 、 (zh typography), not the render helper's ", " fallback.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术栈：", "Spring Boot", "Nacos", "Kafka"],
                    "descriptionStyles": ["label", "plain", "plain", "plain"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["description"] == ["技术栈：", "Spring Boot、Nacos、Kafka"]
        assert project["descriptionStyles"] == ["label", "plain"]

    def test_all_url_region_is_left_verbatim(self) -> None:
        # A region whose only follower is a URL would orphan the 技术栈 label
        # if lifted: skip the whole region and leave fields empty.
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术栈：", "https://example.com"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        result = repair_project_tech_stack_rows(copy.deepcopy(parsed))
        project = result["personalProjects"][0]
        assert project.get("website") is None
        assert project.get("github") is None
        assert project["description"] == parsed["personalProjects"][0]["description"]
        assert project["descriptionStyles"] == ["label", "plain"]

    def test_bare_colon_less_label_is_recognized(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术栈", "Java", "Kotlin", "项目职责：", "开发"],
                    "descriptionStyles": ["label", "plain", "plain", "label", "bullet"],
                }
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["description"] == [
            "技术栈",
            "Java、Kotlin",
            "项目职责：",
            "开发",
        ]
        assert project["descriptionStyles"] == ["label", "plain", "label", "bullet"]

    def test_running_twice_is_idempotent(self) -> None:
        parsed = {
            "personalProjects": [
                {
                    "name": "Forest",
                    "description": [
                        "技术栈：",
                        "Java",
                        "Kotlin",
                        "https://forest.dtflyx.com",
                        "项目职责：",
                        "负责设计。",
                    ],
                    "descriptionStyles": [
                        "label",
                        "plain",
                        "plain",
                        "plain",
                        "label",
                        "bullet",
                    ],
                },
                {
                    "name": "Structured",
                    "description": ["技术栈：", "后端：Java", "Redis"],
                    "descriptionStyles": ["label", "plain", "plain"],
                },
            ]
        }
        once = repair_project_tech_stack_rows(copy.deepcopy(parsed))
        twice = repair_project_tech_stack_rows(copy.deepcopy(once))
        assert twice == once

    def test_work_entries_and_non_tech_rows_are_untouched(self) -> None:
        parsed = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["技术栈：", "Java", "Kotlin"],
                    "descriptionStyles": ["label", "plain", "plain"],
                }
            ],
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目背景：", "某业务系统。", "JDK 21"],
                    "descriptionStyles": ["label", "plain", "plain"],
                }
            ],
        }
        result = repair_project_tech_stack_rows(parsed)
        assert result["workExperience"][0]["description"] == [
            "技术栈：",
            "Java",
            "Kotlin",
        ]
        assert result["personalProjects"][0]["description"] == [
            "项目背景：",
            "某业务系统。",
            "JDK 21",
        ]

    def test_missing_styles_and_non_list_inputs_are_tolerated(self) -> None:
        parsed = {
            "personalProjects": [
                {"name": "NoStyles", "description": ["技术栈：", "Java", "Kotlin"]},
                {"name": "NoDescription"},
            ]
        }
        project = repair_project_tech_stack_rows(parsed)["personalProjects"][0]
        assert project["description"] == ["技术栈：", "Java、Kotlin"]
        assert project["descriptionStyles"] == ["label", "plain"]

        assert repair_project_tech_stack_rows({}) == {}
        assert repair_project_tech_stack_rows({"personalProjects": None}) == {
            "personalProjects": None
        }


class TestStripSourcePointNumbering:
    def test_strips_marker_from_single_value(self):
        assert strip_source_point_marker("1、配合需求评审。") == "配合需求评审。"
        assert strip_source_point_marker("1) 修复缺陷。") == "修复缺陷。"
        assert strip_source_point_marker("① Java 基础") == "Java 基础"
        assert strip_source_point_marker("一、踏实稳重") == "踏实稳重"
        assert strip_source_point_marker("• 持续学习") == "持续学习"

    def test_glyph_marker_strips_without_following_whitespace(self):
        # Rule 1 symbol unification: "•Java" carries the same bullet glyph and
        # must not survive as a literal point prefix.
        assert strip_source_point_marker("•Java 并发编程") == "Java 并发编程"
        assert strip_source_point_marker("·Redis 缓存") == "Redis 缓存"
        assert strip_source_point_marker("●  带多个空格") == "带多个空格"

    def test_dash_marker_keeps_negative_and_version_ranges(self):
        # Hyphens still require following whitespace, so minus signs and
        # ranges are never mistaken for bullet markers.
        assert strip_source_point_marker("-30% 延迟优化") == "-30% 延迟优化"
        assert strip_source_point_marker("-1~3 年经验") == "-1~3 年经验"
        assert strip_source_point_marker("- 用连字符开头的点") == "用连字符开头的点"
        assert strip_source_point_marker("— 破折号开头的点") == "破折号开头的点"

    def test_does_not_strip_leading_year_or_version_numbers(self):
        assert strip_source_point_marker("2021年 PMP 认证") == "2021年 PMP 认证"
        assert strip_source_point_marker("Java 8 / Spring Boot 2.x") == "Java 8 / Spring Boot 2.x"

    def test_strips_from_descriptions_skills_strings_items(self):
        parsed = {
            "personalProjects": [
                {"name": "P", "description": ["1、需求评审", "2、核心开发", "技术亮点："]}
            ],
            "workExperience": [
                {"company": "C", "description": ["1．保障稳定性", "(2) 值班响应"]}
            ],
            "additional": {
                "technicalSkills": ["1、Java 并发", "2、JVM"],
                "certificationsTraining": ["1．PMP"],
                "awards": ["① 优秀员工"],
                "languages": ["英语 CET-6"],
            },
            "customSections": {
                "other": {
                    "sectionType": "stringList",
                    "strings": ["1. 计算机三级", "2. CET-6"],
                },
                "volunteer": {
                    "sectionType": "itemList",
                    "items": [{"title": "V", "description": ["1、组织活动"]}],
                },
            },
        }
        result = strip_source_point_numbering(parsed)
        assert result["personalProjects"][0]["description"] == [
            "需求评审",
            "核心开发",
            "技术亮点：",
        ]
        assert result["workExperience"][0]["description"] == ["保障稳定性", "值班响应"]
        assert result["additional"]["technicalSkills"] == ["Java 并发", "JVM"]
        assert result["additional"]["certificationsTraining"] == ["PMP"]
        assert result["additional"]["awards"] == ["优秀员工"]
        assert result["additional"]["languages"] == ["英语 CET-6"]
        assert result["customSections"]["other"]["strings"] == ["计算机三级", "CET-6"]
        assert result["customSections"]["volunteer"]["items"][0]["description"] == [
            "组织活动"
        ]

    def test_prose_and_missing_sections_are_tolerated(self):
        parsed = {
            "summary": "15年经验\n1、不可剥除：summary 是散文",
            "customSections": {"eval": {"sectionType": "text", "text": "1、自我评价行"}},
            "personalProjects": None,
        }
        result = strip_source_point_numbering(parsed)
        assert result["summary"] == "15年经验\n1、不可剥除：summary 是散文"
        assert result["customSections"]["eval"]["text"] == "1、自我评价行"


class TestReconcileCustomSectionShapes:
    def test_string_list_migrates_titled_items_into_strings(self):
        # Real-world shape (leo resume 「其它」 block): declared stringList but
        # the entries were stored as items while strings stayed null, so every
        # template rendered a title-only block.
        parsed = {
            "customSections": {
                "other": {
                    "sectionType": "stringList",
                    "strings": None,
                    "items": [
                        {"id": 1, "title": "1、GitHub 开源项目：https://example.com/repo"},
                        {"id": 2, "title": "个人技术站点：https://example.com/blog"},
                        {"id": 3, "title": "   "},
                    ],
                    "text": None,
                }
            }
        }
        result = reconcile_custom_section_shapes(copy.deepcopy(parsed))
        section = result["customSections"]["other"]
        assert section["strings"] == [
            "GitHub 开源项目：https://example.com/repo",
            "个人技术站点：https://example.com/blog",
        ]
        assert section["items"] is None

    def test_item_list_migrates_strings_into_titled_items(self):
        parsed = {
            "customSections": {
                "volunteer": {
                    "sectionType": "itemList",
                    "strings": ["社区分享", "  ", "开源贡献"],
                    "items": None,
                    "text": None,
                }
            }
        }
        result = reconcile_custom_section_shapes(copy.deepcopy(parsed))
        section = result["customSections"]["volunteer"]
        assert section["items"] == [
            {"id": 1, "title": "社区分享"},
            {"id": 2, "title": "开源贡献"},
        ]
        assert section["strings"] is None

    def test_declared_container_with_content_is_untouched(self):
        parsed = {
            "customSections": {
                "links": {
                    "sectionType": "stringList",
                    "strings": ["博客"],
                    # Items alongside a populated strings container are left
                    # alone: the declared type already renders content.
                    "items": [{"id": 1, "title": "遗留条目"}],
                },
                "awards": {
                    "sectionType": "itemList",
                    "strings": ["遗留字符串"],
                    "items": [{"id": 1, "title": "优秀员工"}],
                },
            }
        }
        result = reconcile_custom_section_shapes(copy.deepcopy(parsed))
        assert result == parsed

    def test_text_and_truly_empty_sections_are_untouched(self):
        parsed = {
            "customSections": {
                "eval": {"sectionType": "text", "text": "踏实稳重", "items": None},
                "blank": {"sectionType": "stringList", "strings": None, "items": []},
            }
        }
        result = reconcile_custom_section_shapes(copy.deepcopy(parsed))
        assert result == parsed

    def test_malformed_custom_sections_are_tolerated(self):
        parsed = {"customSections": {"broken": "oops", None: 123}}
        reconcile_custom_section_shapes(parsed)  # must not raise
        assert "customSections" in parsed
        assert reconcile_custom_section_shapes({}) == {}
        assert reconcile_custom_section_shapes({"customSections": None}) == {
            "customSections": None
        }

    def test_reconciliation_is_idempotent(self):
        parsed = {
            "customSections": {
                "other": {
                    "sectionType": "stringList",
                    "strings": None,
                    "items": [
                        {"id": 1, "title": "GitHub 开源项目"},
                        {"id": 2, "title": "个人技术站点"},
                    ],
                }
            }
        }
        once = reconcile_custom_section_shapes(copy.deepcopy(parsed))
        twice = reconcile_custom_section_shapes(copy.deepcopy(once))
        assert once == twice


class TestMeaningfulResumeContent:
    def test_rejects_schema_defaults_only(self):
        assert has_meaningful_resume_content(
            {
                "personalInfo": {},
                "summary": "",
                "workExperience": [],
                "education": [],
                "personalProjects": [],
                "additional": {"technicalSkills": []},
                "customSections": {},
            }
        ) is False

    def test_accepts_experience_without_contact_details(self):
        assert has_meaningful_resume_content(
            {"personalInfo": {}, "workExperience": [{"title": "Engineer"}]}
        ) is True

    def test_rejects_default_only_section_entries(self):
        assert has_meaningful_resume_content(
            {
                "workExperience": [
                    {
                        "id": 0,
                        "title": "",
                        "company": "",
                        "years": "",
                        "description": [],
                        "descriptionStyles": [],
                    }
                ],
                "customSections": {
                    "empty": {
                        "sectionType": "itemList",
                        "items": [{"id": 0, "title": "", "description": []}],
                    }
                },
            }
        ) is False

    def test_accepts_additional_and_custom_section_text(self):
        assert has_meaningful_resume_content(
            {"additional": {"technicalSkills": ["Python"]}}
        ) is True
        assert has_meaningful_resume_content(
            {"customSections": {"publications": {"sectionType": "text", "text": "Paper"}}}
        ) is True

    def test_accepts_custom_section_with_a_reserved_identifier(self):
        assert has_meaningful_resume_content(
            {"customSections": {"key": {"sectionType": "text", "text": "Paper"}}}
        ) is True

    def test_rejects_content_beyond_the_recursion_limit(self):
        deeply_nested: object = "Resume content"
        for _ in range(11):
            deeply_nested = {"value": deeply_nested}

        assert has_meaningful_resume_content({"summary": deeply_nested}) is False

    def test_finds_content_at_the_last_allowed_depth(self):
        """Boundary: a value at depth ``limit - 1`` is still inspected."""
        nested = _wrap("Resume content", _MAX_RESUME_CONTENT_RECURSION - 1)

        assert has_meaningful_resume_content({"summary": nested}) is True

    def test_rejects_content_one_level_past_the_limit(self):
        """Boundary: a value at exactly ``limit`` is cut off (declared empty).

        This is the documented, accepted false negative. It is unreachable for
        schema-valid resumes -- see test_deepest_real_schema_content_is_found
        and the comment on _MAX_RESUME_CONTENT_RECURSION.
        """
        nested = _wrap("Resume content", _MAX_RESUME_CONTENT_RECURSION)

        assert has_meaningful_resume_content({"summary": nested}) is False

    def test_deepest_real_schema_content_is_found(self):
        """The deepest path ResumeData allows (depth 5) stays well inside 10.

        customSections(0) -> CustomSection(1) -> items(2) -> item(3)
        -> description(4) -> bullet(5).
        """
        assert has_meaningful_resume_content(
            {
                "customSections": {
                    "publications": {
                        "sectionType": "itemList",
                        "items": [
                            {
                                "id": 0,
                                "title": "",
                                "subtitle": None,
                                "years": "",
                                "description": ["A paper nobody should lose"],
                                "descriptionStyles": [],
                            }
                        ],
                    }
                }
            }
        ) is True

    @pytest.mark.asyncio
    @patch("app.services.parser.complete_json", new_callable=AsyncMock)
    async def test_parse_rejects_empty_llm_json(self, mock_complete_json):
        mock_complete_json.return_value = {}
        with pytest.raises(ValueError, match="empty structured resume"):
            await parse_resume_to_json("Jane Doe")

    @pytest.mark.asyncio
    @patch("app.services.parser.complete_json", new_callable=AsyncMock)
    async def test_parse_rejects_default_only_llm_entries(self, mock_complete_json):
        mock_complete_json.return_value = {"workExperience": [{}]}
        with pytest.raises(ValueError, match="empty structured resume"):
            await parse_resume_to_json("Jane Doe")


class TestSplitBlobTextSections:
    """split_blob_text_sections: ；/。 blobs become ordered-list points."""

    def test_self_evaluation_paragraph_splits_into_points(self) -> None:
        data = {
            "customSections": {
                "self_evaluation": {
                    "sectionType": "text",
                    "text": "做事认真负责；学习能力强。具有团队精神。",
                }
            }
        }
        split_blob_text_sections(data)
        assert data["customSections"]["self_evaluation"]["text"] == (
            "做事认真负责\n学习能力强\n具有团队精神"
        )

    def test_self_evaluation_alias_keys_split_too(self) -> None:
        data = {
            "customSections": {
                "self_appraisal": {
                    "sectionType": "text",
                    "text": "抗压能力强；主观能动性强。",
                }
            }
        }
        split_blob_text_sections(data)
        assert data["customSections"]["self_appraisal"]["text"] == (
            "抗压能力强\n主观能动性强"
        )

    def test_already_point_per_line_text_is_unchanged(self) -> None:
        original = "做事认真负责。\n学习能力强。\n具有团队精神。"
        data = {
            "customSections": {
                "self_evaluation": {"sectionType": "text", "text": original}
            }
        }
        split_blob_text_sections(data)
        # Lines with at most one clause survive verbatim, punctuation kept.
        assert data["customSections"]["self_evaluation"]["text"] == original

    def test_non_selfeval_text_block_is_untouched(self) -> None:
        blob = "阅读广泛；热爱跑步。每年参加两次马拉松。"
        data = {
            "customSections": {
                "hobbies": {"sectionType": "text", "text": blob}
            }
        }
        split_blob_text_sections(data)
        assert data["customSections"]["hobbies"]["text"] == blob

    def test_project_duty_blob_splits_within_duty_region_only(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "交易中台",
                    "description": [
                        "项目背景：",
                        "面向医疗行业的一体化平台，服务多家医院。",
                        "项目职责：",
                        "负责核心模块开发；负责性能调优。承担架构演进。",
                        "项目亮点：",
                        "时延降低 50%；吞吐翻倍。",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet", "label", "bullet"],
                }
            ]
        }
        split_blob_text_sections(data)
        project = data["personalProjects"][0]
        assert project["description"] == [
            "项目背景：",
            "面向医疗行业的一体化平台，服务多家医院。",
            "项目职责：",
            "负责核心模块开发",
            "负责性能调优",
            "承担架构演进",
            "项目亮点：",
            "时延降低 50%；吞吐翻倍。",
        ]
        assert project["descriptionStyles"] == [
            "label",
            "plain",
            "label",
            "bullet",
            "bullet",
            "bullet",
            "label",
            "bullet",
        ]

    def test_project_duty_blob_after_glued_label_row(self) -> None:
        # normalize_item_sub_labels already separates "项目职责：a；b。" into a
        # label row + one content row; splitting expands the content row.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目职责：", "负责 A；负责 B。"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        split_blob_text_sections(data)
        project = data["personalProjects"][0]
        assert project["description"] == ["项目职责：", "负责 A", "负责 B"]
        assert project["descriptionStyles"] == ["label", "plain", "plain"]

    def test_project_without_label_rows_is_untouched(self) -> None:
        # Without label rows the duty region cannot be located: the
        # background/tech-stack prose must not be split blindly.
        description = ["介绍系统背景。第二句背景。", "JDK 21.0.1；Spring Boot 3.3.4"]
        data = {
            "personalProjects": [
                {"name": "P", "description": description, "descriptionStyles": []}
            ]
        }
        split_blob_text_sections(data)
        assert data["personalProjects"][0]["description"] == description

    def test_residual_source_markers_are_stripped_per_segment(self) -> None:
        data = {
            "customSections": {
                "self_evaluation": {
                    "sectionType": "text",
                    "text": "1、做事认真；2、学习能力强。",
                }
            }
        }
        split_blob_text_sections(data)
        assert data["customSections"]["self_evaluation"]["text"] == (
            "做事认真\n学习能力强"
        )


class TestCjkCompatNormalization:
    def test_kangxi_radicals_become_normal_chars(self) -> None:
        assert normalize_cjk_compat("⼯作职责与项⽬简介") == "工作职责与项目简介"

    def test_simplified_radical_supplement_glyphs(self) -> None:
        assert normalize_cjk_compat("组⻓负责⻅证成⻓") == "组长负责见证成长"

    def test_kangxi_door_becomes_simplified_hu(self) -> None:
        assert normalize_cjk_compat("⼾籍") == "户籍"

    def test_punctuation_is_not_normalized(self) -> None:
        text = "时间：2020年6月（括号）；点号。"
        assert normalize_cjk_compat(text) == text

    def test_non_string_passes_through(self) -> None:
        assert normalize_cjk_compat(None) is None
        assert normalize_cjk_compat(123) == 123

    def test_deep_normalizes_nested_leaves(self) -> None:
        value = {
            "a": ["⼯作", {"b": "组⻓"}],
            "customSections": {"k": {"text": "⾃我评价⼀样"}},
        }
        cleaned = normalize_cjk_compat_deep(value)
        assert cleaned["a"][0] == "工作"
        assert cleaned["a"][1]["b"] == "组长"
        assert cleaned["customSections"]["k"]["text"] == "自我评价一样"


class TestRepairProjectLabelRegions:
    def test_tech_entries_become_plain_even_if_model_labels_them(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["技术栈：", "Java", "Spring Boot"],
                    "descriptionStyles": ["label", "label", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == ["label", "plain", "plain"]

    def test_duty_prose_on_label_row_is_demoted_to_bullet(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "负责整体架构：基于双框架分工，避免配置漂移。",
                        "负责性能调优。",
                    ],
                    "descriptionStyles": ["label", "label", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == ["label", "bullet", "bullet"]

    def test_glued_intro_with_radical_glyphs_splits_and_goes_plain(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项⽬简介：面向企业营销场景。", "技术栈：", "Kafka"],
                    "descriptionStyles": ["label", "label", "plain"],
                }
            ]
        }
        data = normalize_cjk_compat_deep(data)
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["description"] == [
            "项目背景：",
            "面向企业营销场景。",
            "技术栈：",
            "Kafka",
        ]
        assert project["descriptionStyles"] == ["label", "plain", "label", "plain"]

    def test_unplanned_label_closes_known_region(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "负责 A。",
                        "难点/方案/效果：",
                        "无表头表格内容",
                    ],
                    "descriptionStyles": ["label", "bullet", "label", "plain"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        # The free-form plain row after the unplanned label is left untouched.
        assert project["descriptionStyles"] == ["label", "bullet", "label", "plain"]

    def test_project_without_known_headings_is_untouched(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["介绍系统背景。第二句。", "JDK 21.0.1"],
                    "descriptionStyles": ["plain", "plain"],
                }
            ]
        }
        repair_project_label_regions(data)
        assert data["personalProjects"][0]["descriptionStyles"] == ["plain", "plain"]

    def test_work_entries_are_not_repaired(self) -> None:
        data = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["技术栈：", "Java"],
                    "descriptionStyles": ["label", "label"],
                }
            ],
            "personalProjects": [],
        }
        repair_project_label_regions(data)
        assert data["workExperience"][0]["descriptionStyles"] == ["label", "label"]

    def test_four_canonical_modules_restore_names_regions_and_source_layout(self) -> None:
        # Mirrors real upload shapes: "个人职责：" stored plain, a bare
        # colon-less "项目成果" stored plain. After the full normalize + repair
        # chain the project is organized under the four canonical modules while
        # every source line keeps its place and layout (background/tech-stack
        # unnumbered plain incl. verbatim category rows; duty/highlight bullets).
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目背景：",
                        "面向多子系统重复建设与交付效率问题。",
                        "技术栈：",
                        "后端：Java 17、Spring Boot",
                        "Redis",
                        "个人职责：",
                        "负责核心交易链路设计与落地。",
                        "负责高峰流量削峰与稳定性治理。",
                        "项目成果",
                        "核心链路 P99 时延下降 40%。",
                    ],
                    "descriptionStyles": ["plain"] * 10,
                }
            ]
        }
        normalize_item_sub_labels(data)
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["description"] == [
            "项目背景：",
            "面向多子系统重复建设与交付效率问题。",
            "技术栈：",
            "后端：Java 17、Spring Boot",
            "Redis",
            "项目职责：",
            "负责核心交易链路设计与落地。",
            "负责高峰流量削峰与稳定性治理。",
            "项目亮点",
            "核心链路 P99 时延下降 40%。",
        ]
        assert project["descriptionStyles"] == [
            "label",  # 项目背景：
            "plain",  # background prose stays unnumbered
            "label",  # 技术栈：
            "plain",  # category row kept verbatim as ONE plain row
            "plain",  # bare tech name stays plain
            "label",  # 个人职责： -> 项目职责：
            "bullet",  # duty content becomes numbered points
            "bullet",
            "label",  # bare 项目成果 -> bare 项目亮点 (no colon invented)
            "bullet",  # highlight content becomes numbered points
        ]

    def test_bare_personal_duty_alias_opens_bullet_region(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["个人职责", "负责模块编码实现。"],
                    "descriptionStyles": ["plain", "plain"],
                }
            ]
        }
        normalize_item_sub_labels(data)
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["description"] == ["项目职责", "负责模块编码实现。"]
        assert project["descriptionStyles"] == ["label", "bullet"]

    def test_bare_group_headings_inside_duty_region_become_nested_labels(self) -> None:
        # Real upload shape (邹利平.pdf): "核心职责与成果：" module containing
        # bare bold group titles stored as plain rows interleaved with bullets.
        # The titles must be promoted to label (not coerced to bullets) so the
        # renderer can number them 1./1.1/1.2/2./2.1 hierarchically.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "核心职责与成果：",
                        "架构演进与技术债务治理",
                        "担任商城板块技术负责人，主导架构设计与版本迭代。",
                        "梳理历史技术债务，建立代码质量规范。",
                        "主导促销中心组件设计",
                        "将营销活动流程组件化，提升代码复用性。",
                        "新活动接入周期缩短 30%，支撑十万级 GMV 交易。",
                    ],
                    "descriptionStyles": [
                        "label",
                        "plain",
                        "bullet",
                        "bullet",
                        "plain",
                        "bullet",
                        "bullet",
                    ],
                }
            ]
        }
        normalize_item_sub_labels(data)
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["description"][0] == "项目职责："
        assert project["descriptionStyles"] == [
            "label",  # 核心职责与成果： -> 项目职责：
            "label",  # bare group heading promoted
            "bullet",
            "bullet",
            "label",  # second bare group heading promoted
            "bullet",
            "bullet",
        ]
        # Row text is never rewritten by the region repair.
        assert project["description"][1] == "架构演进与技术债务治理"
        assert project["description"][4] == "主导促销中心组件设计"

    def test_source_numbered_enumeration_is_not_promoted_to_group_head(self) -> None:
        # "2）机审" is a source-numbered enumeration item, not a bold heading.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "1）系统需求调研",
                        "2）功能设计",
                        "负责核心模块开发。",
                    ],
                    "descriptionStyles": ["label", "plain", "plain", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == [
            "label",
            "bullet",  # coerced as ordinary region content, never a label
            "bullet",
            "bullet",
        ]

    def test_long_or_punctuated_plain_row_is_not_promoted_to_group_head(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "作为后端技术组长，牵头项目从调研到运维的全流程交付工作。",
                        "负责核心模块开发。",
                    ],
                    "descriptionStyles": ["label", "plain", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        # The long sentence is plain region content coerced to bullet, not a
        # bold nested head.
        assert project["descriptionStyles"] == ["label", "bullet", "bullet"]

    def test_bare_heading_without_following_bullet_is_not_promoted(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": ["项目职责：", "收尾工作"],
                    "descriptionStyles": ["label", "plain"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        # No bullet follows the short plain row, so it stays ordinary content.
        assert project["descriptionStyles"] == ["label", "bullet"]

    def test_short_bullet_point_is_not_promoted_to_group_head(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "技术方案设计",
                        "负责核心模块编码实现。",
                    ],
                    "descriptionStyles": ["label", "bullet", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        # The head-shaped bullet is the ONLY short row in the module: the
        # >=2-qualified-heads structural gate keeps it an ordinary point.
        assert project["descriptionStyles"] == ["label", "bullet", "bullet"]

    def test_bullet_styled_group_heads_are_promoted_across_all_projects(self) -> None:
        # 邹利平.pdf 沃尔沃内领商城 shape: the weak model stored EVERY row as a
        # bullet, including the bare group titles. A head-shaped bullet with a
        # detail-shaped successor inside a multi-group module is still a head.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责",
                        "系统从 0 到 1 搭建",
                        "主导内领商城架构设计与核心模块开发，负责需求评审与落地。",
                        "设计并实现三方系统对接的高可用方案",
                        "对接阿里 1688：完成商品分类映射、商品同步及库存对接。",
                        "履约层策略化重构",
                        "基于策略模式重构订单履约层，新增履约方式零侵入。",
                        "自研轻量级流程编排框架",
                        "问题：校验商品信息、库存、下单代码，有大量重复冗余代码",
                        "将业务流程拆解为可复用原子节点并支持多流程共享",
                        "新订单类型接入周期缩短 40%。",
                        "商品初始化同步方案",
                        "通过分类治理与多轮对账，保障商品同步准确率 100%。",
                    ],
                    "descriptionStyles": ["label"] + ["bullet"] * 12,
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == [
            "label",   # 项目职责
            "label",   # 系统从 0 到 1 搭建 (head 1)
            "bullet",
            "bullet",
            "bullet",
            "label",   # 履约层策略化重构 (head 2)
            "bullet",
            "label",   # 自研轻量级流程编排框架 (head 3)
            "bullet",
            "bullet",
            "bullet",
            "label",   # 商品初始化同步方案 (head 4)
            "bullet",
        ]

    def test_flat_peer_bullet_list_is_never_split_into_groups(self) -> None:
        # 叶宏汉.pdf shape: uniformly short "负责…" peer duties, some rows
        # head-shaped by length alone but no head/detail alternation.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "负责内网穿透项目单连接多路复用通信架构的设计与实现",
                        "负责自定义二进制通信协议设计与帧解析实现",
                        "负责高吞吐传输与反压机制建设",
                        "负责分布式长连接注册与路由方案设计",
                        "负责长连接重连与服务滚动升级机制实现",
                    ],
                    "descriptionStyles": ["label"] + ["bullet"] * 5,
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == ["label"] + ["bullet"] * 5

    def test_adjacent_head_shaped_bullets_are_peer_points(self) -> None:
        # Two short rows next to each other cannot be head+head; neither
        # qualifies (a head needs a detail-shaped successor).
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "负责消息可靠性与消费位点管理",
                        "负责操作审计可靠投递方案设计与实现",
                        "负责统一事件协议与渐进式迁移推进服务平滑迁移落地。",
                        "负责高可用容灾演练与故障预案体系建设",
                        "主导跨机房双活架构改造，核心链路 RTO 缩短至分钟级。",
                    ],
                    "descriptionStyles": ["label"] + ["bullet"] * 5,
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == ["label"] + ["bullet"] * 5

    def test_isolated_short_bullet_between_long_points_is_not_a_head(self) -> None:
        # 张向科.pdf shape: one short point sandwiched between long detail
        # points under the same implicit group — a single candidate never
        # satisfies the >=2-heads module gate.
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "负责大批量任务执行与可观测建设：XXL-Job 分片产生任务、Kafka 异步派发，Watchdog 与业务幂等处理重复执行",
                        "SSE 流式返回话术与任务进度",
                        "OpenTelemetry 与 Micrometer 记录 Agent Trace、Token 与延迟，Token 用量写入 ES 支撑成本分析。",
                        "负责智能决策域整体架构：基于 Spring AI 与 LangChain4j 双框架分工，LLM 调用统一收口到代理层。",
                        "模型及外部服务通过 Resilience4j 熔断降级，异常时返回缓存兜底",
                    ],
                    "descriptionStyles": ["label"] + ["bullet"] * 5,
                }
            ]
        }
        repair_project_label_regions(data)
        project = data["personalProjects"][0]
        assert project["descriptionStyles"] == ["label"] + ["bullet"] * 5

    def test_group_head_planning_is_idempotent_on_re_heal(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目职责：",
                        "系统从 0 到 1 搭建",
                        "主导架构设计与核心模块开发，负责需求评审与落地。",
                        "履约层策略化重构",
                        "基于策略模式重构订单履约层，新增渠道零侵入。",
                    ],
                    "descriptionStyles": ["label", "bullet", "bullet", "bullet", "bullet"],
                }
            ]
        }
        repair_project_label_regions(data)
        once = list(data["personalProjects"][0]["descriptionStyles"])
        repair_project_label_regions(data)
        twice = data["personalProjects"][0]["descriptionStyles"]
        assert once == twice == ["label", "label", "bullet", "label", "bullet"]


class TestCanonicalizeDatePeriod:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # Numeric / Chinese numeric forms, every connector style.
            ("2020.06 - 2023.09", "2020.06~2023.09"),
            ("2020/06 – 2023/09", "2020.06~2023.09"),
            ("2020-06~2023-09", "2020.06~2023.09"),
            ("2017.9~2021.7", "2017.09~2021.07"),
            ("2020 年 06 月 - 2023 年 09 月", "2020.06~2023.09"),
            ("2020年5月 至 2023年8月", "2020.05~2023.08"),
            # Open-ended periods: every marker becomes Chinese 至今, tilde.
            ("2025.07 - 至今", "2025.07~至今"),
            ("2025.07～至今", "2025.07~至今"),
            ("May 2021 - Present", "2021.05~至今"),
            ("January 2020 - Current", "2020.01~至今"),
            ("2024.03 - Now", "2024.03~至今"),
            # English month names become numeric on every resume.
            ("Jan 2020 - Dec 2023", "2020.01~2023.12"),
            ("Jun 2023", "2023.06"),
            ("Jan 2020 to Mar 2021", "2020.01~2021.03"),
            # Year-only precision is kept (months must never be invented).
            ("2020 - 2021", "2020~2021"),
            ("2020", "2020"),
            # One trailing parenthesized note survives.
            ("2019.07 - 2021.12（实习）", "2019.07~2021.12（实习）"),
        ],
    )
    def test_canonical_forms(self, raw: str, expected: str) -> None:
        assert canonicalize_date_period(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "三年经验",
            "2020年入职",
            "至今",
            "2020.06~2023.09 备注文字",
            "2020.06~至今~2023.09",
            "2020-06-2023-09",  # glued, no real connector: do not guess
        ],
    )
    def test_unparseable_values_pass_through_unchanged(self, raw: str) -> None:
        assert canonicalize_date_period(raw) == raw

    def test_idempotent(self) -> None:
        once = canonicalize_date_period("Jan 2020 - Dec 2023")
        assert canonicalize_date_period(once) == once == "2020.01~2023.12"

    def test_normalize_date_periods_walks_every_years_field(self) -> None:
        data = {
            "personalInfo": {"workYears": "8年"},
            "workExperience": [
                {"company": "甲", "title": "工程师", "years": "2020.06 - 至今"}
            ],
            "education": [{"institution": "乙大学", "degree": "本科", "years": "2016 - 2020"}],
            "personalProjects": [{"name": "丙项目", "role": "", "years": "Mar 2021 - Present"}],
            "customSections": {
                "pubs": {
                    "sectionType": "itemList",
                    "items": [{"title": "论文", "subtitle": "", "years": "2019.05 - 2020.02"}],
                },
                "hobbies": {"sectionType": "text", "text": "阅读"},
            },
        }
        normalize_date_periods(data)
        assert data["workExperience"][0]["years"] == "2020.06~至今"
        assert data["education"][0]["years"] == "2016~2020"
        assert data["personalProjects"][0]["years"] == "2021.03~至今"
        assert data["customSections"]["pubs"]["items"][0]["years"] == "2019.05~2020.02"
        # workYears is a duration, not a date field.
        assert data["personalInfo"]["workYears"] == "8年"


class TestNumericDateRestoration:
    def test_empty_education_years_filled_from_numeric_range(self) -> None:
        data = {
            "education": [
                {
                    "institution": "河北工业大学城市学院",
                    "degree": "公办本科 - 物联网工程",
                    "years": "",
                }
            ]
        }
        markdown = (
            "教育背景\n"
            "河北工业大学城市学院 - 公办本科 - 物联网工程 2017.09 - 2021.07\n"
        )
        restore_dates_from_markdown(data, markdown)
        assert data["education"][0]["years"] == "2017.09~2021.07"

    def test_year_only_education_replaced_with_numeric_months(self) -> None:
        data = {
            "education": [
                {
                    "institution": "某大学",
                    "degree": "本科",
                    "years": "2017 - 2021",
                }
            ]
        }
        markdown = "某大学 本科 2017.09 - 2021.07"
        restore_dates_from_markdown(data, markdown)
        assert data["education"][0]["years"] == "2017.09~2021.07"

    def test_chinese_present_marker_restored(self) -> None:
        data = {
            "workExperience": [
                {"company": "某公司", "title": "工程师", "years": "2025"}
            ]
        }
        markdown = "某公司 工程师 2025.07 - 至今"
        restore_dates_from_markdown(data, markdown)
        assert data["workExperience"][0]["years"] == "2025.07~至今"

    def test_projects_without_dates_do_not_steal_periods(self) -> None:
        data = {
            "workExperience": [
                {"company": "甲公司", "title": "负责人（P6）", "years": ""}
            ],
            "education": [
                {"institution": "某大学", "degree": "本科", "years": ""}
            ],
            "personalProjects": [
                {"name": "智能平台", "role": "核心研发", "years": ""}
            ],
        }
        markdown = (
            "1. 甲公司 负责人（P6） 2023.10 - 2025.06\n"
            "某大学 本科 2017.09 - 2021.07\n"
            "智能平台项目简介：本人作为核心研发。\n"
        )
        restore_dates_from_markdown(data, markdown)
        assert data["workExperience"][0]["years"] == "2023.10~2025.06"
        assert data["education"][0]["years"] == "2017.09~2021.07"
        assert data["personalProjects"][0]["years"] == ""

    def test_version_numbers_are_not_dates(self) -> None:
        assert _MD_NUMERIC_DATE_RE.findall("JDK 21.0.1，权重0.6，QPS 1200") == []
        match = _MD_NUMERIC_DATE_RE.search("2020.06 - 2023.08")
        assert match is not None
        assert _canonical_numeric_date(match.group(0)) == "2020.06~2023.08"


class TestGlyphLossRecovery:
    def test_detects_long_space_gap_and_radicals(self) -> None:
        assert _shows_glyph_loss("2017.09 - 2021.07".replace("2017", "    "))
        assert _shows_glyph_loss("⼯" * 12)
        assert not _shows_glyph_loss("正常文本，没有字形丢失。" * 3)

    def test_replaces_with_pdfium_text_when_it_recovers_digits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys
        import types

        class FakeTextPage:
            def __init__(self, text: str) -> None:
                self._text = text

            def get_text_range(self) -> str:
                return self._text

            def close(self) -> None:
                pass

        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def get_textpage(self) -> FakeTextPage:
                return FakeTextPage(self._text)

        recovered_text = "教育 2017.09 - 2021.07 学校经历" + "工作内容" * 20

        class FakeDocument:
            def __init__(self, _content: bytes) -> None:
                pass

            def __iter__(self):
                return iter([FakePage(recovered_text)])

            def close(self) -> None:
                pass

        fake_module = types.ModuleType("pypdfium2")
        fake_module.PdfDocument = FakeDocument  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pypdfium2", fake_module)

        damaged = "教育        .  -        . 学校经历" + "工作内容" * 20
        recovered = _recover_glyph_loss(b"pdf-bytes", damaged)
        assert "2017.09 - 2021.07" in recovered

    def test_keeps_markitdown_when_pdfium_has_no_extra_digits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys
        import types

        class FakeTextPage:
            def get_text_range(self) -> str:
                return "纯中文没有数字" + "内容" * 30

            def close(self) -> None:
                pass

        class FakePage:
            def get_textpage(self) -> FakeTextPage:
                return FakeTextPage()

        class FakeDocument:
            def __init__(self, _content: bytes) -> None:
                pass

            def __iter__(self):
                return iter([FakePage()])

            def close(self) -> None:
                pass

        fake_module = types.ModuleType("pypdfium2")
        fake_module.PdfDocument = FakeDocument  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pypdfium2", fake_module)

        damaged = "日期    .  -    ." + "工作" * 20
        assert _recover_glyph_loss(b"pdf-bytes", damaged) == damaged


class TestExtractEducationCredentials:
    """extract_education_credentials: 教育描述中的奖项/证书行迁移到 additional。"""

    def test_real_glued_newline_shape_moves_credentials_and_keeps_major(self) -> None:
        # Observed resume 5b6b6e77: LLM duplicated the award/cert lines into
        # the education description (the single major cell).
        data = {
            "education": [
                {
                    "id": 1,
                    "institution": "天津大学仁爱学院",
                    "degree": "本科",
                    "years": "2017.10 - 2021.06",
                    "description": (
                        "专业：计算机科学与技术\n"
                        "奖项：国家励志奖学金、杯全国软件和信息技术三等奖。\n"
                        "证书：PMP项目管理证书。"
                    ),
                }
            ],
            "additional": {
                "technicalSkills": [],
                "languages": [],
                "certificationsTraining": ["PMP项目管理证书"],
                "awards": ["国家励志奖学金", "杯全国软件和信息技术三等奖"],
            },
        }

        extract_education_credentials(data)
        # Same as the parse pipeline: final de-dupe collapses credentials the
        # LLM had already extracted into the additional arrays.
        dedupe_resume_lists(data)

        assert data["education"][0]["description"] == "计算机科学与技术"
        assert data["additional"]["awards"] == [
            "国家励志奖学金",
            "杯全国软件和信息技术三等奖",
        ]
        assert data["additional"]["certificationsTraining"] == ["PMP项目管理证书"]

    def test_single_line_glued_segments_split_on_labels(self) -> None:
        data = {
            "education": [
                {
                    "description": "专业：计算机科学与技术 奖项：校三好学生、国家奖学金。 证书：英语六级证书。",
                }
            ],
            "additional": {},
        }

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "计算机科学与技术"
        assert data["additional"]["awards"] == ["校三好学生", "国家奖学金"]
        assert data["additional"]["certificationsTraining"] == ["英语六级证书"]

    def test_leading_unlabeled_text_is_kept_as_major(self) -> None:
        data = {
            "education": [
                {"description": "计算机科学与技术 获奖情况：国家奖学金。"}
            ],
            "additional": {},
        }

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "计算机科学与技术"
        assert data["additional"]["awards"] == ["国家奖学金"]

    def test_mixed_honor_certificate_label_routes_items_by_keyword(self) -> None:
        data = {
            "education": [
                {"description": "荣誉证书：校三好学生、PMP项目管理证书、优秀毕业生。"}
            ],
            "additional": {},
        }

        extract_education_credentials(data)

        assert data["education"][0]["description"] == ""
        assert data["additional"]["awards"] == ["校三好学生", "优秀毕业生"]
        assert data["additional"]["certificationsTraining"] == ["PMP项目管理证书"]

    def test_major_only_label_is_stripped_without_touching_additional(self) -> None:
        data = {
            "education": [{"description": "专业：软件工程"}],
            "additional": {"awards": ["已有的奖"]},
        }

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "软件工程"
        assert data["additional"]["awards"] == ["已有的奖"]

    def test_description_without_labels_is_byte_identical(self) -> None:
        original = "主修计算机科学与技术，辅修金融学"
        data = {"education": [{"description": original}], "additional": {}}

        extract_education_credentials(data)

        assert data["education"][0]["description"] == original
        assert data["additional"] == {}

    def test_source_numbering_on_items_is_stripped(self) -> None:
        data = {
            "education": [{"description": "奖项：1、国家奖学金；2、校三好学生。"}],
            "additional": {},
        }

        extract_education_credentials(data)

        assert data["additional"]["awards"] == ["国家奖学金", "校三好学生"]

    def test_missing_additional_dict_is_created_and_idempotent(self) -> None:
        data = {
            "education": [
                {
                    "description": "专业：计算机科学与技术\n证书：PMP项目管理证书。",
                }
            ],
        }

        extract_education_credentials(data)
        assert data["additional"]["certificationsTraining"] == ["PMP项目管理证书"]
        assert data["education"][0]["description"] == "计算机科学与技术"

        # Second run finds no labels and must not duplicate anything.
        extract_education_credentials(data)
        assert data["additional"]["certificationsTraining"] == ["PMP项目管理证书"]

    def test_english_substring_labels_do_not_false_match(self) -> None:
        # "Rewards：" contains "Awards：" but is not an awards label.
        original = "Loyalty Rewards：membership programme participation"
        data = {"education": [{"description": original}], "additional": {}}

        extract_education_credentials(data)

        assert data["education"][0]["description"] == original
        assert data["additional"] == {}

    def test_multiple_education_entries_processed_independently(self) -> None:
        data = {
            "education": [
                {"description": "专业：软件工程 奖项：国家奖学金。"},
                {"description": "交流学习一年"},
            ],
            "additional": {},
        }

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "软件工程"
        assert data["education"][1]["description"] == "交流学习一年"
        assert data["additional"]["awards"] == ["国家奖学金"]


class TestExtractMisfiledCredentials:
    """extract_misfiled_credentials: 工作/项目列表描述中带标签的奖项/证书/语言区域归位。"""

    def _work(self, rows: list[object], styles: list[str]) -> dict:
        return {
            "workExperience": [
                {"id": 1, "title": "工程师", "company": "Acme", "description": rows, "descriptionStyles": styles}
            ]
        }

    def _project(self, rows: list[object], styles: list[str]) -> dict:
        return {
            "personalProjects": [
                {"id": 1, "name": "结算系统", "description": rows, "descriptionStyles": styles}
            ]
        }

    def test_block_region_label_style_moves_items_and_drops_rows(self) -> None:
        data = self._work(["奖项：", "国家奖学金", "校优秀学生干部"], ["label", "bullet", "bullet"])

        extract_misfiled_credentials(data)

        entry = data["workExperience"][0]
        assert entry["description"] == []
        assert entry["descriptionStyles"] == []
        assert data["additional"]["awards"] == ["国家奖学金", "校优秀学生干部"]

    def test_glued_single_row_splits_award_and_cert(self) -> None:
        data = self._work(["奖项：国家奖学金、PMP项目管理证书。"], ["bullet"])

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == []
        assert data["additional"]["awards"] == ["国家奖学金"]
        assert data["additional"]["certificationsTraining"] == ["PMP项目管理证书"]

    def test_legacy_plain_styled_label_is_still_recognized(self) -> None:
        data = self._project(["奖项：", "国家奖学金"], ["plain", "bullet"])

        extract_misfiled_credentials(data)

        assert data["personalProjects"][0]["description"] == []
        assert data["additional"]["awards"] == ["国家奖学金"]

    def test_bare_heading_needs_label_style(self) -> None:
        labeled = self._work(["奖项", "国家奖学金"], ["label", "bullet"])
        extract_misfiled_credentials(labeled)
        assert labeled["additional"]["awards"] == ["国家奖学金"]
        assert labeled["workExperience"][0]["description"] == []

        bulleted = self._work(["奖项", "国家奖学金"], ["bullet", "bullet"])
        extract_misfiled_credentials(bulleted)
        assert "additional" not in bulleted
        assert bulleted["workExperience"][0]["description"] == ["奖项", "国家奖学金"]

    def test_language_block_and_glued_rows(self) -> None:
        data = self._work(
            ["语言：", "英语 CET-6", "日语 N1", "语言：雅思7.0"],
            ["label", "bullet", "bullet", "bullet"],
        )

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == []
        assert data["additional"]["languages"] == ["英语 CET-6", "日语 N1", "雅思7.0"]

    def test_strong_certificate_signal_wins_inside_language_region(self) -> None:
        data = self._work(["语言：英语六级、PMP证书"], ["bullet"])

        extract_misfiled_credentials(data)

        assert data["additional"]["languages"] == ["英语六级"]
        assert data["additional"]["certificationsTraining"] == ["PMP证书"]

    def test_region_stops_at_next_sublabel_and_keeps_duty_rows(self) -> None:
        data = self._work(
            ["奖项：", "国家奖学金", "工作职责：", "负责支付系统开发"],
            ["label", "bullet", "label", "bullet"],
        )

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == ["工作职责：", "负责支付系统开发"]
        assert data["workExperience"][0]["descriptionStyles"] == ["label", "bullet"]
        assert data["additional"]["awards"] == ["国家奖学金"]

    def test_multi_label_glued_row_routes_each_segment(self) -> None:
        data = self._work(["奖项：国家奖学金 证书：PMP证书"], ["bullet"])

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == []
        assert data["additional"]["awards"] == ["国家奖学金"]
        assert data["additional"]["certificationsTraining"] == ["PMP证书"]

    def test_mixed_honor_certificate_label_routes_items_by_keyword(self) -> None:
        data = self._work(["荣誉证书：校三好学生、PMP证书、优秀毕业生"], ["bullet"])

        extract_misfiled_credentials(data)

        assert data["additional"]["awards"] == ["校三好学生", "优秀毕业生"]
        assert data["additional"]["certificationsTraining"] == ["PMP证书"]

    def test_evidence_gate_keeps_labeled_duty_block_byte_identical(self) -> None:
        rows = ["奖项：", "负责日常运营支持", "参与团队建设"]
        styles = ["label", "bullet", "bullet"]
        data = self._work(rows, styles)

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] is rows
        assert "additional" not in data

    def test_one_unknown_item_in_glued_row_keeps_the_whole_row(self) -> None:
        rows = ["奖项：国家奖学金、负责年会组织工作"]
        data = self._work(rows, ["bullet"])

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] is rows
        assert "additional" not in data

    def test_unlabeled_keyword_rows_are_never_touched(self) -> None:
        for row in ("负责年会奖品采购", "持有 PMP 证书的轮岗", "获校二等奖学金", "编写内部工具"):
            data = self._work([row], ["bullet"])
            extract_misfiled_credentials(data)
            assert data["workExperience"][0]["description"] == [row]
            assert "additional" not in data

    def test_programming_language_rows_are_never_touched(self) -> None:
        rows = ["编程语言：Java、Python", "开发语言：Go", "脚本语言：Bash"]
        data = self._work(rows, ["bullet", "bullet", "bullet"])

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == rows
        assert "additional" not in data

    def test_region_cap_abandons_over_long_blocks(self) -> None:
        # Label + 7 content rows without a boundary: abandon everything.
        long_rows = ["奖项：", "国家奖学金", "b奖", "c奖", "d奖", "e奖", "f奖", "g奖"]
        data = self._work(long_rows, ["label"] + ["bullet"] * 7)
        extract_misfiled_credentials(data)
        assert data["workExperience"][0]["description"] is long_rows
        assert "additional" not in data

        # Label + exactly 6 content rows: accepted.
        ok_rows = ["奖项：", "国家奖学金", "b奖", "c奖", "d奖", "e奖", "f奖"]
        ok_data = self._work(ok_rows, ["label"] + ["bullet"] * 6)
        extract_misfiled_credentials(ok_data)
        assert ok_data["workExperience"][0]["description"] == []
        assert len(ok_data["additional"]["awards"]) == 6

    def test_source_point_markers_are_stripped(self) -> None:
        data = self._work(
            ["1、奖项：", "1、国家奖学金", "2、校三好学生"],
            ["label", "bullet", "bullet"],
        )

        extract_misfiled_credentials(data)

        assert data["additional"]["awards"] == ["国家奖学金", "校三好学生"]

    def test_idempotent_and_dedupes_pre_existing_items(self) -> None:
        data = self._work(["奖项：国家奖学金、校三好学生"], ["bullet"])
        data["additional"] = {"awards": ["国家奖学金"]}

        extract_misfiled_credentials(data)
        dedupe_resume_lists(data)
        snapshot = copy.deepcopy(data)
        extract_misfiled_credentials(data)
        dedupe_resume_lists(data)

        assert data == snapshot
        assert data["additional"]["awards"] == ["国家奖学金", "校三好学生"]

    def test_styles_stay_aligned_when_middle_rows_vanish(self) -> None:
        data = self._work(
            ["职责行一", "奖项：国家奖学金", "职责行二"],
            ["plain", "bullet", "plain"],
        )

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == ["职责行一", "职责行二"]
        assert data["workExperience"][0]["descriptionStyles"] == ["plain", "plain"]

    def test_additional_lazily_created_and_existing_values_appended(self) -> None:
        data = self._work(["证书：PMP证书"], ["bullet"])
        data["additional"] = {"awards": ["已有的奖"], "certificationsTraining": ["已有证书"]}

        extract_misfiled_credentials(data)

        assert data["additional"]["awards"] == ["已有的奖"]
        assert data["additional"]["certificationsTraining"] == ["已有证书", "PMP证书"]

    def test_english_labels_recognized_but_substring_lookalikes_not(self) -> None:
        data = self._work(
            ["Awards: Dean's List", "Certifications: PMP", "Languages: English (CET-6)"],
            ["bullet", "bullet", "bullet"],
        )
        extract_misfiled_credentials(data)
        assert data["additional"]["awards"] == ["Dean's List"]
        assert data["additional"]["certificationsTraining"] == ["PMP"]
        assert data["additional"]["languages"] == ["English (CET-6)"]

        lookalike = self._work(["Loyalty Rewards: membership programme"], ["bullet"])
        extract_misfiled_credentials(lookalike)
        assert "additional" not in lookalike

    def test_non_string_rows_and_non_list_descriptions_are_safe(self) -> None:
        data = self._work(
            ["奖项：", "国家奖学金", None, "证书：PMP证书"],
            ["label", "bullet", "bullet", "bullet"],
        )

        extract_misfiled_credentials(data)

        # None terminates the first region; both credential groups still move.
        assert None in data["workExperience"][0]["description"]
        assert data["additional"]["awards"] == ["国家奖学金"]
        assert data["additional"]["certificationsTraining"] == ["PMP证书"]

        # String / missing descriptions are skipped, not crashed on.
        data["workExperience"][0]["description"] = "奖项：国家奖学金"
        extract_misfiled_credentials(data)
        data["workExperience"][0].pop("description")
        extract_misfiled_credentials(data)

    def test_missing_styles_array_defaults_to_bullet(self) -> None:
        data = {
            "workExperience": [
                {"id": 1, "title": "工程师", "description": ["奖项：国家奖学金"]}
            ]
        }

        extract_misfiled_credentials(data)

        assert data["workExperience"][0]["description"] == []
        assert data["workExperience"][0]["descriptionStyles"] == []
        assert data["additional"]["awards"] == ["国家奖学金"]


class TestExtractEducationLanguage:
    """教育描述语言标签扩展（_extract_education_credentials_text 4-tuple）。"""

    def test_language_segment_moves_to_languages_and_keeps_major(self) -> None:
        data = {"education": [{"description": "专业：计算机科学与技术\n语言：英语六级"}]}

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "计算机科学与技术"
        assert data["additional"]["languages"] == ["英语六级"]

    def test_programming_language_in_education_string_is_untouched(self) -> None:
        original = "专业：计算机科学与技术，编程语言：Java"
        data = {"education": [{"description": original}]}

        extract_education_credentials(data)

        assert data["education"][0]["description"] == "计算机科学与技术，编程语言：Java"
        assert data.get("additional", {}).get("languages", []) == []



class TestNormalizeTextHygiene:
    """规则一/二 的确定性呈现卫生（trim、空行锁位、空白折叠、句尾统一）。"""

    def test_blank_rows_and_styles_dropped_in_lockstep(self) -> None:
        data = {
            "workExperience": [
                {
                    "company": "  某公司  ",
                    "description": ["负责架构", "  ", "推进微服务", ""],
                    "descriptionStyles": ["bullet", "plain", "bullet", "bullet"],
                }
            ],
        }

        normalize_text_hygiene(data)

        entry = data["workExperience"][0]
        assert entry["description"] == ["负责架构", "推进微服务"]
        # The two blank rows take THEIR OWN styles with them; later bullets do
        # not shift onto their neighbour's style.
        assert entry["descriptionStyles"] == ["bullet", "bullet"]
        assert entry["company"] == "某公司"

    def test_bullet_endings_stripped_plain_and_label_kept(self) -> None:
        data = {
            "personalProjects": [
                {
                    "name": "P",
                    "description": [
                        "项目背景：",
                        "这是一段散文描述。",
                        "完成性能优化；",
                        "可用性提升至 99.99%。",
                    ],
                    "descriptionStyles": ["label", "plain", "bullet", "bullet"],
                }
            ]
        }

        normalize_text_hygiene(data)

        assert data["personalProjects"][0]["description"] == [
            "项目背景：",
            "这是一段散文描述。",
            "完成性能优化",
            "可用性提升至 99.99%",
        ]

    def test_whitespace_runs_collapse_inside_rows(self) -> None:
        data = {
            "workExperience": [
                {
                    "company": "C",
                    "description": ["Java\t\t并发   与  JVM", " 带不间断空格 "],
                    "descriptionStyles": ["bullet", "plain"],
                }
            ]
        }

        normalize_text_hygiene(data)

        assert data["workExperience"][0]["description"] == [
            "Java 并发 与 JVM",
            "带不间断空格",
        ]

    def test_summary_trims_blank_lines_and_row_endings(self) -> None:
        data = {
            "summary": (
                "  10 年研发管理经验。\n"
                "\n"
                "  \n"
                "主导过多个大型平台；\n"
                "带过 200 人技术团队。"
            )
        }

        normalize_text_hygiene(data)

        assert data["summary"] == (
            "10 年研发管理经验\n主导过多个大型平台\n带过 200 人技术团队"
        )

    def test_string_lists_trim_drop_blank_and_unify_endings(self) -> None:
        data = {
            "additional": {
                "technicalSkills": ["  Java / Spring 生态。", "", "  ", "Python；"],
                "languages": ["英语六级 "],
                "certificationsTraining": ["PMP。"],
                "awards": ["优秀员工。"],
            }
        }

        normalize_text_hygiene(data)

        assert data["additional"]["technicalSkills"] == [
            "Java / Spring 生态",
            "Python",
        ]
        assert data["additional"]["languages"] == ["英语六级"]
        assert data["additional"]["certificationsTraining"] == ["PMP"]
        assert data["additional"]["awards"] == ["优秀员工"]

    def test_custom_text_selfeval_endings_stripped_other_text_kept(self) -> None:
        data = {
            "customSections": {
                "self_evaluation": {
                    "sectionType": "text",
                    "text": "踏实肯干。\n\n持续学习。",
                },
                "hobbies": {"sectionType": "text", "text": "阅读。\n\n跑步。"},
            }
        }

        normalize_text_hygiene(data)

        # Self-evaluation renders as numbered points: endings unified.
        assert data["customSections"]["self_evaluation"]["text"] == (
            "踏实肯干\n持续学习"
        )
        # Ordinary prose text blocks keep their periods but lose blank lines.
        assert data["customSections"]["hobbies"]["text"] == "阅读。\n跑步。"

    def test_custom_item_list_cleans_titles_and_descriptions(self) -> None:
        data = {
            "customSections": {
                "papers": {
                    "sectionType": "itemList",
                    "items": [
                        {
                            "title": "  某核心期刊论文  ",
                            "subtitle": "第一作者 ",
                            "description": ["提出一种新架构。", " "],
                            "descriptionStyles": ["bullet", "plain"],
                        }
                    ],
                }
            }
        }

        normalize_text_hygiene(data)

        item = data["customSections"]["papers"]["items"][0]
        assert item["title"] == "某核心期刊论文"
        assert item["subtitle"] == "第一作者"
        assert item["description"] == ["提出一种新架构"]
        assert item["descriptionStyles"] == ["bullet"]

    def test_personal_info_header_trim_but_content_preserved(self) -> None:
        data = {
            "personalInfo": {
                "name": "  李勇 ",
                "workYears": "15年+ 5年大型医院项目 ",
                "title": " 架构师 ",
            }
        }

        normalize_text_hygiene(data)

        info = data["personalInfo"]
        assert info["name"] == "李勇"
        assert info["title"] == "架构师"
        # workYears is a fact, not a list point: only the outer trim applies.
        assert info["workYears"] == "15年+ 5年大型医院项目"

    def test_idempotent_second_run_deep_equal(self) -> None:
        data = {
            "summary": " 10 年经验。\n\n\n主导架构演进。\n",
            "workExperience": [
                {
                    "company": " 某公司 ",
                    "description": ["负责架构。", " ", "推进微服务。"],
                    "descriptionStyles": ["bullet", "plain", "bullet"],
                }
            ],
            "additional": {"technicalSkills": [" Java。", "", "Python；"]},
            "customSections": {
                "self_evaluation": {
                    "sectionType": "text",
                    "text": "踏实肯干。\n\n持续学习。",
                }
            },
        }

        normalize_text_hygiene(data)
        snapshot = copy.deepcopy(data)
        normalize_text_hygiene(data)

        assert data == snapshot
