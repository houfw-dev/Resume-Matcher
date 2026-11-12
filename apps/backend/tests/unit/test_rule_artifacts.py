"""Fail-fast contract tests for the externalized rule artifacts.

The parser rule artifact (parser_rules.json) is data maintained outside the
codebase, so the loader must reject corruption loudly at load time rather than
failing deep inside the parser: missing sections, unknown keys, non-scalar
thresholds, blank/duplicate vocabulary entries and uncompilable regex strings
all raise during validation. The shipped artifact itself must always load.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.parser_rules import (
    PatternSpec,
    ParserRules,
    _read_json,
    get_parser_rules,
    parse_rules,
)

VALID_DOCUMENT: dict[str, Any] = {
    "spec_version": "1.0",
    "thresholds": {"header_search_limit": 2000},
    "vocabularies": {
        "heading_words": ["个人信息", "求职意向"],
        "label_aliases": {"姓名": ["name"], "电话": ["phone", "mobile"]},
    },
    "patterns": {
        "phone": {"pattern": r"1[3-9]\d{9}", "flags": ["IGNORECASE"]},
        "plain": {"pattern": r"\d{4}"},
    },
}


def test_shipped_artifact_loads_and_exposes_typed_view() -> None:
    rules = get_parser_rules()
    assert rules.spec_version == "1.0"
    assert isinstance(rules.thresholds, dict)
    assert isinstance(rules.vocabularies, dict)
    assert isinstance(rules.patterns, dict)
    # The cached accessor must return the same instance within the process.
    assert get_parser_rules() is rules


def test_shipped_json_matches_validated_view() -> None:
    artifact_path = Path(__file__).resolve().parents[2] / (
        "app/services/parser_rules.json"
    )
    raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert parse_rules(raw) == get_parser_rules()


def test_valid_document_compiles_patterns_once() -> None:
    rules = parse_rules(VALID_DOCUMENT)
    compiled = rules.compiled_patterns
    assert compiled is rules.compiled_patterns  # cached on the instance
    assert compiled["phone"].pattern == r"1[3-9]\d{9}"
    assert compiled["phone"].flags & re.IGNORECASE
    assert rules.pattern("plain").search("year 2024") is not None
    with pytest.raises(KeyError):
        rules.pattern("does_not_exist")
    assert rules.vocabulary("heading_words") == ["个人信息", "求职意向"]


@pytest.mark.parametrize("missing", ["spec_version", "thresholds", "vocabularies", "patterns"])
def test_missing_top_level_section_fails(missing: str) -> None:
    raw = {key: value for key, value in VALID_DOCUMENT.items() if key != missing}
    with pytest.raises(ValidationError):
        parse_rules(raw)


def test_unknown_top_level_section_fails() -> None:
    raw = {**VALID_DOCUMENT, "pipeline_order": ["step_one"]}
    with pytest.raises(ValidationError):
        parse_rules(raw)


def test_blank_spec_version_fails() -> None:
    raw = {**VALID_DOCUMENT, "spec_version": "  "}
    with pytest.raises(ValidationError):
        parse_rules(raw)


def test_uncompilable_regex_fails_fast() -> None:
    raw = {
        **VALID_DOCUMENT,
        "patterns": {"broken": {"pattern": r"(unclosed group"}},
    }
    with pytest.raises(ValidationError, match="does not compile"):
        parse_rules(raw)


def test_unknown_regex_flag_fails() -> None:
    raw = {
        **VALID_DOCUMENT,
        "patterns": {"broken": {"pattern": r"\d+", "flags": ["VERBOSE"]}},
    }
    with pytest.raises(ValidationError, match="unknown regex flags"):
        parse_rules(raw)


def test_pattern_spec_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        PatternSpec.model_validate({"pattern": r"\d+", "flags": [], "extra": 1})


def test_pattern_spec_requires_pattern_string() -> None:
    with pytest.raises(ValidationError):
        PatternSpec.model_validate({"flags": []})


@pytest.mark.parametrize("bad_value", [[1, 2], {"nested": 1}, True, 1.5j])
def test_non_scalar_threshold_fails(bad_value: Any) -> None:
    raw = {**VALID_DOCUMENT, "thresholds": {"bad": bad_value}}
    with pytest.raises(ValidationError):
        parse_rules(raw)


def test_boolean_threshold_is_rejected_even_though_bool_is_int() -> None:
    raw = {**VALID_DOCUMENT, "thresholds": {"enabled": True}}
    with pytest.raises(ValidationError, match="bool is not allowed"):
        parse_rules(raw)


def test_vocabulary_blank_and_duplicate_entries_fail() -> None:
    blank = {**VALID_DOCUMENT, "vocabularies": {"words": ["ok", "  "]}}
    with pytest.raises(ValidationError, match="blank entries"):
        parse_rules(blank)

    duplicate = {**VALID_DOCUMENT, "vocabularies": {"words": ["ok", "ok"]}}
    with pytest.raises(ValidationError, match="duplicate entry"):
        parse_rules(duplicate)

    nested_duplicate = {
        **VALID_DOCUMENT,
        "vocabularies": {"aliases": {"key": ["ok", "ok"]}},
    }
    with pytest.raises(ValidationError, match="duplicate entry"):
        parse_rules(nested_duplicate)


def test_non_mapping_document_fails() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        parse_rules(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_corrupt_json_file_raises(tmp_path: Path) -> None:
    bad_file = tmp_path / "parser_rules.json"
    bad_file.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _read_json(bad_file)


def test_loader_returns_pydantic_model_not_raw_dict() -> None:
    assert isinstance(get_parser_rules(), ParserRules)


# ---------------------------------------------------------------------------
# Golden locks for the shipped parser vocabularies (Phase 2 batch 1). The
# 215 parser tests remain the behavioral zero-drift net; these pin the
# artifact contents so a YAML edit cannot silently shrink a vocabulary.
# ---------------------------------------------------------------------------

EXPECTED_HEADER_FIELD_ORDER = (
    "name",
    "gender",
    "age",
    "workYears",
    "educationLevel",
    "languages",
    "phone",
    "email",
    "title",
    "location",
    "website",
    "linkedin",
    "github",
)
CANONICAL_PROJECT_LABELS = frozenset({"项目职责", "项目亮点", "项目背景", "技术栈"})


def test_shipped_header_vocabularies_match_legacy_tuples() -> None:
    rules = get_parser_rules()
    field_labels = rules.vocabulary_mapping("header_field_labels")
    assert tuple(field_labels) == EXPECTED_HEADER_FIELD_ORDER
    assert len(field_labels) == 13
    # Every leaf is a standalone-compilable regex fragment.
    for fragment in field_labels.values():
        re.compile(fragment)  # type: ignore[arg-type]
    assert rules.vocabulary_list("header_basic_headings") == [
        "基本资料",
        "个人信息",
        "基本信息",
        "个人资料",
        "个人概况",
    ]
    stop_headings = rules.vocabulary_list("header_stop_headings")
    assert len(stop_headings) == 41
    assert stop_headings[0] == "教育背景"
    assert stop_headings[-1] == "兴趣特长"
    assert len(set(stop_headings)) == 41  # no duplicates


def test_shipped_sub_label_vocabularies_match_legacy_tuples() -> None:
    rules = get_parser_rules()
    candidates = rules.vocabulary_list("sub_label_candidates")
    assert len(candidates) == 72
    assert candidates[0] == "技术难点及亮点"
    assert candidates[-1] == "担任角色"
    assert len(set(candidates)) == 72

    canonical = rules.vocabulary_mapping("project_sub_label_canonical")
    assert len(canonical) == 35
    assert set(canonical.values()) <= CANONICAL_PROJECT_LABELS
    # Every alias is itself a recognized sub-label candidate.
    assert set(canonical) <= set(candidates)

    plain_labels = rules.vocabulary_list("project_inline_plain_labels")
    assert len(plain_labels) == 16
    assert len(set(plain_labels)) == 16
    assert rules.vocabulary_list("dedupable_additional_fields") == [
        "technicalSkills",
        "certificationsTraining",
        "awards",
        "languages",
    ]


def test_outcome_labels_are_recognized_but_never_canonicalized() -> None:
    """The 成效/效果 peer modules must stay verbatim (documented invariant)."""
    rules = get_parser_rules()
    candidates = set(rules.vocabulary_list("sub_label_candidates"))
    canonical = rules.vocabulary_mapping("project_sub_label_canonical")
    outcome_labels = [label for label in candidates if label.endswith(("成效", "效果"))]
    assert len(outcome_labels) == 16
    assert not set(outcome_labels) & set(canonical)


def test_parser_bindings_match_artifact_and_keep_legacy_shapes() -> None:
    from app.services import parser

    rules = get_parser_rules()
    assert tuple(parser._HEADER_FIELD_LABELS) == tuple(
        (field, pattern)
        for field, pattern in rules.vocabulary_mapping("header_field_labels").items()
    )
    assert parser._HEADER_BASIC_HEADINGS == tuple(
        rules.vocabulary_list("header_basic_headings")
    )
    assert parser._HEADER_STOP_HEADINGS == tuple(
        rules.vocabulary_list("header_stop_headings")
    )
    assert parser._SUB_LABEL_CANDIDATES == tuple(
        rules.vocabulary_list("sub_label_candidates")
    )
    assert parser.PROJECT_SUB_LABEL_CANONICAL == dict(
        rules.vocabulary_mapping("project_sub_label_canonical")
    )
    assert parser.PROJECT_INLINE_PLAIN_LABELS == frozenset(
        rules.vocabulary_list("project_inline_plain_labels")
    )
    assert parser._DEDUPABLE_ADDITIONAL_FIELDS == tuple(
        rules.vocabulary_list("dedupable_additional_fields")
    )
    # Imported by resume_docx / description_regions: shapes stay importable.
    assert isinstance(parser.PROJECT_SUB_LABEL_CANONICAL, dict)
    assert isinstance(parser.PROJECT_INLINE_PLAIN_LABELS, frozenset)


def test_regex_leaf_vocabulary_rejects_uncompilable_fragment() -> None:
    raw = {
        **VALID_DOCUMENT,
        "vocabularies": {
            "header_field_labels": {"name": "(unclosed group"}
        },
    }
    with pytest.raises(ValidationError, match="regex leaf does not compile"):
        parse_rules(raw)


def test_vocabulary_typed_accessors_enforce_shape() -> None:
    rules = parse_rules(VALID_DOCUMENT)
    assert rules.vocabulary_list("heading_words") == ["个人信息", "求职意向"]
    assert rules.vocabulary_mapping("label_aliases") == {
        "姓名": ["name"],
        "电话": ["phone", "mobile"],
    }
    with pytest.raises(ValueError, match="expected a list"):
        rules.vocabulary_list("label_aliases")
    with pytest.raises(ValueError, match="expected a mapping"):
        rules.vocabulary_mapping("heading_words")
    with pytest.raises(KeyError):
        rules.vocabulary_list("does_not_exist")


# ---------------------------------------------------------------------------
# Golden locks for the shipped date-family regex patterns (Phase 2 batch 2a).
# ---------------------------------------------------------------------------

DATE_FAMILY_PATTERNS = (
    "md_date",
    "month_en",
    "numeric_date",
    "present_marker",
    "numeric_month_precise",
    "canon_numeric_point",
    "canon_bare_year",
    "canon_present",
    "canon_connector_word",
    "canon_trailing_note",
)
IGNORECASE_DATE_PATTERNS = (
    "md_date",
    "month_en",
    "numeric_date",
    "present_marker",
    "canon_present",
    "canon_connector_word",
)


def test_shipped_date_family_patterns_keep_legacy_behavior() -> None:
    rules = get_parser_rules()
    assert tuple(rules.compiled_patterns)[: len(DATE_FAMILY_PATTERNS)] == (
        DATE_FAMILY_PATTERNS
    )
    for name in DATE_FAMILY_PATTERNS:
        assert rules.pattern(name) is rules.compiled_patterns[name]
    for name in IGNORECASE_DATE_PATTERNS:
        assert rules.pattern(name).flags & re.IGNORECASE

    assert rules.pattern("md_date").search("May 2021 - Present") is not None
    assert rules.pattern("month_en").search("born in March") is not None
    # Version strings must never be read as dates (negative lock from
    # test_parser.py::test markdown numeric date extraction).
    assert rules.pattern("numeric_date").findall("JDK 21.0.1，权重0.6") == []
    assert rules.pattern("numeric_date").search("2020.06 - 2023.08") is not None
    assert rules.pattern("present_marker").search("目前在职") is not None
    assert rules.pattern("numeric_month_precise").search("2020年6月") is not None
    point = rules.pattern("canon_numeric_point").search("2020/6")
    assert point is not None and point.groups() == ("2020", "6")
    bare = rules.pattern("canon_bare_year").search("abc 2020 def")
    assert bare is not None and bare.group(1) == "2020"
    # A year glued to another date component must not match as a bare year.
    assert rules.pattern("canon_bare_year").search("2020.06") is None
    assert rules.pattern("canon_present").search("Current") is not None
    assert rules.pattern("canon_connector_word").search("Jan to Dec") is not None
    assert rules.pattern("canon_trailing_note").fullmatch("（实习）") is not None


def test_parser_date_regexes_are_artifact_bindings() -> None:
    from app.services import parser

    rules = get_parser_rules()
    for module_name, artifact_name in (
        ("_MD_DATE_RE", "md_date"),
        ("_MONTH_RE", "month_en"),
        ("_MD_NUMERIC_DATE_RE", "numeric_date"),
        ("_PRESENT_MARKER_RE", "present_marker"),
        ("_NUMERIC_MONTH_PRECISE_RE", "numeric_month_precise"),
        ("_CANON_NUMERIC_POINT_RE", "canon_numeric_point"),
        ("_CANON_BARE_YEAR_RE", "canon_bare_year"),
        ("_CANON_PRESENT_RE", "canon_present"),
        ("_CANON_CONNECTOR_WORD_RE", "canon_connector_word"),
        ("_CANON_TRAILING_NOTE_RE", "canon_trailing_note"),
    ):
        assert getattr(parser, module_name) is rules.pattern(artifact_name)


# ---------------------------------------------------------------------------
# Golden locks for markdown / URL / point-marker patterns (Phase 2 batch 2b).
# ---------------------------------------------------------------------------

MARKDOWN_FAMILY_PATTERNS = (
    "markdown_inline_link",
    "bare_url",
    "point_marker",
    "md_bold_star",
    "md_bold_under",
    "md_italic_star",
    "md_italic_under",
    "md_code",
    "md_strike",
    "md_orphan_bold",
    "md_orphan_strike",
    "github_host",
)


def test_shipped_markdown_family_patterns_keep_legacy_behavior() -> None:
    rules = get_parser_rules()
    for name in MARKDOWN_FAMILY_PATTERNS:
        assert rules.pattern(name) is rules.compiled_patterns[name]
    # Bold patterns span newlines; the rest carry no explicit flags.
    assert rules.pattern("md_bold_star").flags & re.DOTALL
    assert rules.pattern("md_bold_under").flags & re.DOTALL
    assert rules.pattern("github_host").flags & re.IGNORECASE

    link = rules.pattern("markdown_inline_link").search("[blog](https://x.io/a)")
    assert link is not None and link.group(1) == "https://x.io/a"
    assert rules.pattern("bare_url").search("see www.example.com/path now") is not None

    marker = rules.pattern("point_marker")
    assert marker.match("1、内容") is not None
    assert marker.match("① 内容") is not None
    assert marker.match("•Java") is not None
    # A minus without trailing whitespace is a sign, not a bullet.
    assert marker.match("-30%") is None

    bold = rules.pattern("md_bold_star").search("a **b\nc** d")
    assert bold is not None and bold.group(1) == "b\nc"
    assert rules.pattern("md_italic_star").search("a *b* c") is not None
    code = rules.pattern("md_code").search("use `dict` now")
    assert code is not None and code.group(1) == "dict"
    assert rules.pattern("md_strike").search("~~old~~") is not None
    assert rules.pattern("md_orphan_bold").search("dangling ** tail") is not None
    assert rules.pattern("md_orphan_strike").search("dangling ~~ tail") is not None

    host = rules.pattern("github_host")
    assert host.search("gist.github.com") is not None
    assert host.search("example.com") is None


def test_parser_markdown_regexes_are_artifact_bindings() -> None:
    from app.services import parser

    rules = get_parser_rules()
    for module_name, artifact_name in (
        ("_MARKDOWN_INLINE_LINK_RE", "markdown_inline_link"),
        ("_BARE_URL_RE", "bare_url"),
        ("_POINT_MARKER_RE", "point_marker"),
        ("_MD_BOLD_STAR_RE", "md_bold_star"),
        ("_MD_BOLD_UNDER_RE", "md_bold_under"),
        ("_MD_ITALIC_STAR_RE", "md_italic_star"),
        ("_MD_ITALIC_UNDER_RE", "md_italic_under"),
        ("_MD_CODE_RE", "md_code"),
        ("_MD_STRIKE_RE", "md_strike"),
        ("_MD_ORPHAN_BOLD_RE", "md_orphan_bold"),
        ("_MD_ORPHAN_STRIKE_RE", "md_orphan_strike"),
        ("_GITHUB_HOST_RE", "github_host"),
    ):
        assert getattr(parser, module_name) is rules.pattern(artifact_name)


# ---------------------------------------------------------------------------
# Golden locks for education/misfile vocabularies and credential / tech-stack
# patterns (Phase 2 batch 2c).
# ---------------------------------------------------------------------------


def test_shipped_education_vocabularies_match_legacy_tuples() -> None:
    rules = get_parser_rules()
    major = rules.vocabulary_list("edu_major_label_cores")
    assert major == ["专业方向", "主修专业", "专业名称", "专业"]
    award = rules.vocabulary_list("edu_award_label_cores")
    assert len(award) == 16 and award[0] == "奖项名称" and award[-1] == "Honor"
    cert = rules.vocabulary_list("edu_cert_label_cores")
    assert len(cert) == 20 and cert[0] == "资格证书" and cert[-1] == "Licence"
    mixed = rules.vocabulary_list("edu_mixed_label_cores")
    assert set(mixed) == {"荣誉证书", "荣誉资质", "资质荣誉"}
    assert rules.vocabulary_list("extra_award_label_cores") == [
        "所获荣誉",
        "个人荣誉",
        "荣誉表彰",
        "获奖荣誉",
        "所获奖励",
    ]
    assert rules.vocabulary_list("extra_cert_label_cores") == [
        "执业资格",
        "职业证书",
        "专业证书",
        "技能证书",
    ]
    lang = rules.vocabulary_list("edu_lang_label_cores")
    assert len(lang) == 12
    # The bare 语言 core must stay last so the composed lookbehind regex keeps
    # its fixed-width negative-lookbehind ordering.
    assert lang[-1] == "外语"
    assert "语言" in lang
    # No vocabulary may carry duplicate cores.
    for name in (
        "edu_major_label_cores",
        "edu_award_label_cores",
        "edu_cert_label_cores",
        "edu_mixed_label_cores",
        "extra_award_label_cores",
        "extra_cert_label_cores",
        "edu_lang_label_cores",
    ):
        entries = rules.vocabulary_list(name)
        assert len(entries) == len(set(entries))


def test_shipped_credential_and_tech_patterns_keep_legacy_behavior() -> None:
    rules = get_parser_rules()
    for name in (
        "misfile_cert_item_hint",
        "misfile_lang_item_hint",
        "misfile_award_item_hint",
    ):
        assert rules.pattern(name).flags & re.IGNORECASE

    assert rules.pattern("edu_cert_item_hint").search("PMP 证书") is not None
    clause = rules.pattern("edu_credential_clause")
    assert clause.split("a；b。c") == ["a", "b", "c"]
    assert rules.pattern("misfile_cert_item_hint").search("aws 认证") is not None
    lang_hint = rules.pattern("misfile_lang_item_hint")
    assert lang_hint.search("英语六级") is not None
    assert lang_hint.search("N3 证书") is not None
    assert rules.pattern("misfile_award_item_hint").search("国家奖学金") is not None

    category = rules.pattern("tech_stack_category")
    assert category.search("后端：Java 8、Spring Boot") is not None
    assert rules.pattern("category_sentence").search("一句话。") is not None

    header = rules.pattern("project_header_field").search("项目角色：核心开发")
    assert header is not None
    assert header.group("label") == "项目角色"
    assert header.group("value") == "核心开发"

    department = rules.pattern("work_department_line")
    assert department.match("全球资金部") is not None
    assert department.match("Payments Department") is not None
    assert rules.pattern("work_department_sentence_punct").search("研发，测试") is not None


def test_parser_education_bindings_match_artifact_and_keep_shapes() -> None:
    from app.services import parser

    rules = get_parser_rules()
    assert parser._EDU_MAJOR_LABEL_CORES == tuple(
        rules.vocabulary_list("edu_major_label_cores")
    )
    assert parser._EDU_MIXED_LABEL_CORES == frozenset(
        rules.vocabulary_list("edu_mixed_label_cores")
    )
    # Derived misfile tuples are compositions over the artifact-backed cores.
    assert parser._MISFILE_CERT_LABEL_CORES == (
        parser._EDU_CERT_LABEL_CORES + parser._EXTRA_CERT_LABEL_CORES
    )
    assert parser._MISFILE_AWARD_LABEL_CORES == (
        parser._EDU_AWARD_LABEL_CORES + parser._EXTRA_AWARD_LABEL_CORES
    )
    assert parser._MISFILE_MIXED_CORES is not None
    for module_name, artifact_name in (
        ("_EDU_CERT_ITEM_HINT_RE", "edu_cert_item_hint"),
        ("_EDU_CREDENTIAL_CLAUSE_RE", "edu_credential_clause"),
        ("_MISFILE_CERT_ITEM_HINT_RE", "misfile_cert_item_hint"),
        ("_MISFILE_LANG_ITEM_HINT_RE", "misfile_lang_item_hint"),
        ("_MISFILE_AWARD_ITEM_HINT_RE", "misfile_award_item_hint"),
        ("_TECH_STACK_CATEGORY_RE", "tech_stack_category"),
        ("_CATEGORY_SENTENCE_RE", "category_sentence"),
        ("_PROJECT_HEADER_FIELD_RE", "project_header_field"),
        ("_WORK_DEPARTMENT_LINE_RE", "work_department_line"),
        ("_WORK_DEPARTMENT_SENTENCE_PUNCT_RE", "work_department_sentence_punct"),
    ):
        assert getattr(parser, module_name) is rules.pattern(artifact_name)


# ---------------------------------------------------------------------------
# Golden locks for thresholds and the length-driven composed regexes
# (Phase 2 batch 3).
# ---------------------------------------------------------------------------

EXPECTED_THRESHOLDS: dict[str, int | float] = {
    "header_search_limit": 2000,
    "skill_group_head_max_len": 14,
    "skill_group_min_heads": 2,
    "skill_detail_min_len": 16,
    "nested_group_head_max_len": 16,
    "nested_group_min_heads": 2,
    "misfile_region_max_rows": 6,
    "pdfium_min_cjk_ratio": 0.6,
    "embedded_label_max_len": 11,
    "standalone_label_cjk_max_len": 11,
    "standalone_label_latin_max_len": 20,
}


def test_shipped_thresholds_match_legacy_constants() -> None:
    rules = get_parser_rules()
    assert rules.thresholds == EXPECTED_THRESHOLDS
    # The ratio stays a float; every other threshold is an int, never bool.
    assert isinstance(rules.threshold("pdfium_min_cjk_ratio"), float)
    assert all(
        isinstance(rules.threshold(name), int)
        and not isinstance(rules.threshold(name), bool)
        for name in EXPECTED_THRESHOLDS
        if name != "pdfium_min_cjk_ratio"
    )


def test_threshold_typed_accessors_enforce_types() -> None:
    rules = parse_rules(VALID_DOCUMENT)
    assert rules.int_threshold("header_search_limit") == 2000
    assert rules.float_threshold("header_search_limit") == 2000.0
    with pytest.raises(KeyError):
        rules.threshold("does_not_exist")

    string_threshold = {
        **VALID_DOCUMENT,
        "thresholds": {"mode": "strict"},
    }
    string_rules = parse_rules(string_threshold)
    assert string_rules.threshold("mode") == "strict"
    with pytest.raises(ValueError, match="expected an int"):
        string_rules.int_threshold("mode")
    with pytest.raises(ValueError, match="expected a number"):
        string_rules.float_threshold("mode")


def test_parser_threshold_bindings_match_artifact() -> None:
    from app.services import parser

    rules = get_parser_rules()
    assert parser._HEADER_SEARCH_LIMIT == rules.int_threshold("header_search_limit")
    assert parser._SKILL_GROUP_HEAD_MAX_LEN == 14
    assert parser._SKILL_GROUP_MIN_HEADS == 2
    assert parser._SKILL_DETAIL_MIN_LEN == 16
    assert parser._NESTED_GROUP_HEAD_MAX_LEN == 16
    assert parser._NESTED_GROUP_MIN_HEADS == 2
    assert parser._MISFILE_REGION_MAX_ROWS == 6
    assert parser._PDFIUM_MIN_CJK_RATIO == 0.6
    assert parser._EMBEDDED_LABEL_MAX_LEN == 11
    assert parser._STANDALONE_LABEL_CJK_MAX_LEN == 11
    assert parser._STANDALONE_LABEL_LATIN_MAX_LEN == 20


def test_length_driven_regexes_keep_legacy_shapes() -> None:
    from app.services import parser

    # The embedded-label cut still happens at 11 chars; a 12-char label does
    # not match (threshold-driven composition, verified byte-identically by the
    # zero-drift script against HEAD).
    embedded = parser._EMBEDDED_LABEL_RE
    assert embedded.search("前缀 博客地址：链接") is not None
    standalone = parser._STANDALONE_SUB_LABEL_RE
    assert standalone.match("工作职责：") is not None
    assert standalone.match("CPU 飙升问题：") is not None
    # Pattern strings carry the threshold quantifiers, not literal names.
    assert "{0,11}" in embedded.pattern
    assert "{0,11}" in standalone.pattern and "{0,20}" in standalone.pattern


# ---------------------------------------------------------------------------
# Golden locks for the resume_docx backend mirror (Phase 2 batch 4): the DOCX
# renderer used to hand-keep copies of parser constants; it now binds through
# the same artifact. These tests fail if either side drifts.
# ---------------------------------------------------------------------------


def test_resume_docx_vocabularies_bind_to_the_shared_artifact() -> None:
    from app.services import parser, resume_docx

    rules = get_parser_rules()
    assert resume_docx._SUB_LABEL_CANDIDATES == frozenset(
        rules.vocabulary_list("sub_label_candidates")
    )
    assert resume_docx._SUB_LABEL_CANDIDATES == frozenset(
        parser._SUB_LABEL_CANDIDATES
    )
    assert resume_docx._PROJECT_INLINE_PLAIN_LABELS == frozenset(
        rules.vocabulary_list("project_inline_plain_labels")
    )
    assert (
        resume_docx._PROJECT_INLINE_PLAIN_LABELS
        is parser.PROJECT_INLINE_PLAIN_LABELS
        or resume_docx._PROJECT_INLINE_PLAIN_LABELS
        == parser.PROJECT_INLINE_PLAIN_LABELS
    )
    # The legacy promotion set includes the outcome/effectiveness peers that
    # must never be canonicalized (same lock as the parser-side vocabulary).
    assert "项目成效" in resume_docx._SUB_LABEL_CANDIDATES
    assert "实际效果" in resume_docx._SUB_LABEL_CANDIDATES


def test_resume_docx_patterns_and_thresholds_are_artifact_bindings() -> None:
    from app.services import parser, resume_docx

    rules = get_parser_rules()
    # Compiled patterns are the loader's cached objects themselves.
    assert resume_docx._TECH_STACK_CATEGORY_RE is rules.pattern("tech_stack_category")
    assert resume_docx._CATEGORY_SENTENCE_RE is rules.pattern("category_sentence")
    assert resume_docx._TECH_STACK_CATEGORY_RE is parser._TECH_STACK_CATEGORY_RE
    assert resume_docx._CATEGORY_SENTENCE_RE is parser._CATEGORY_SENTENCE_RE
    assert resume_docx._NESTED_GROUP_HEAD_MAX_LEN == rules.int_threshold(
        "nested_group_head_max_len"
    )
    assert resume_docx._NESTED_GROUP_MIN_HEADS == rules.int_threshold(
        "nested_group_min_heads"
    )
    assert resume_docx._NESTED_GROUP_HEAD_MAX_LEN == parser._NESTED_GROUP_HEAD_MAX_LEN
    assert resume_docx._NESTED_GROUP_MIN_HEADS == parser._NESTED_GROUP_MIN_HEADS


def test_resume_docx_standalone_label_regex_keeps_its_shape_contract() -> None:
    from app.services import parser, resume_docx

    rules = get_parser_rules()
    cjk_max = rules.int_threshold("standalone_label_cjk_max_len")
    latin_max = rules.int_threshold("standalone_label_latin_max_len")
    # Same two length thresholds as the parser, rebuilt independently here so
    # the pattern string itself is golden-locked.
    expected = (
        r"^\s*(?:[一-鿿A-Za-z][一-鿿A-Za-z0-9/（）() -]{0,"
        + str(cjk_max)
        + r"}|[A-Za-z][A-Za-z /-]{0,"
        + str(latin_max)
        + r"})\s*[：:]\s*$"
    )
    assert resume_docx._STANDALONE_LABEL_RE.pattern == expected
    assert resume_docx._STANDALONE_LABEL_RE.flags == re.UNICODE
    # Behavior: plain label rows match; the parser pipeline additionally
    # accepts a source-number prefix, which the DOCX mirror deliberately
    # rejects (its callers strip point markers before this check).
    assert resume_docx._STANDALONE_LABEL_RE.match("工作职责：") is not None
    assert resume_docx._STANDALONE_LABEL_RE.match("1. 工作职责：") is None
    assert parser._STANDALONE_SUB_LABEL_RE.match("1. 工作职责：") is not None
