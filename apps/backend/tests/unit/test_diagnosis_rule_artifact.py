"""Golden locks and fail-fast tests for the diagnosis rule artifact.

Phase 1 externalized the objective checkers' thresholds, regex strings and
vocabularies from diagnosis_checks.py into diagnosis_rules.yaml ->
diagnosis_rules.json. These tests pin the shipped defaults to the exact
pre-migration constants (the 120 checker tests in test_diagnosis_checks.py
remain the behavioral zero-drift net) and prove the Pydantic loader rejects
corrupt artifacts loudly at load time.
"""

import re
from typing import Any

import pytest
from pydantic import ValidationError

from app.services import diagnosis_rules
from app.services.diagnosis_rules import (
    DiagnosisParameters,
    DiagnosisVocabularies,
    StackGroup,
    get_rules,
)

VALID_PARAMETERS: dict[str, Any] = {
    "chars_per_line": 46,
    "chars_per_page": 950,
    "max_point_lines": 6,
    "max_pages": 3,
    "advantage_points_min": 2,
    "advantage_points_max": 5,
    "selfeval_points_min": 3,
    "selfeval_points_max": 5,
    "skill_count_min": 8,
    "skill_count_max": 15,
    "stack_conform_ratio": 0.75,
    "stack_partial_ratio": 0.5,
    "project_count_min": 2,
    "project_count_max": 4,
    "project_tech_vocab_min_hits": 2,
    "gap_partial_months": 3,
    "gap_nonconform_months": 6,
    "recent_window_months": 60,
    "job_hop_company_count": 4,
    "short_stint_months": 12,
    "short_stint_strong_months": 6,
    "work_education_lead_months": 6,
    "stated_years_tolerance": 0.5,
    "advantage_required_tenure_years": 8,
    "internship_experienced_tenure_years": 1,
    "growth_gate_years": 5,
}

VALID_VOCABULARIES: dict[str, Any] = {
    "regex_patterns": {"phone": {"pattern": r"1[3-9]\d{9}"}},
    "degree_rank_patterns": [
        {"rank": 5, "pattern": "博士"},
        {"rank": 1, "pattern": "高中"},
    ],
    "mainstream_stack_groups": [
        {
            "key": "spring_boot",
            "name": "Spring Boot",
            "pattern": r"spring\s*boot",
            "flags": ["IGNORECASE"],
            "hint": "服务框架",
            "equiv": "服务端框架等价口径",
        }
    ],
    "advantage_title_tokens": ["个人优势"],
    "advantage_key_tokens": ["advantage"],
    "selfeval_title_tokens": ["自我评价"],
    "selfeval_key_tokens": ["self_eval"],
    "template_labels": {"swiss-single": "经典单栏"},
}


# ---------------------------------------------------------------------------
# Golden defaults — every value must equal the pre-externalization constant.
# ---------------------------------------------------------------------------


def test_shipped_parameters_match_legacy_constants() -> None:
    params = get_rules().parameters
    assert params is not None
    assert params.model_dump() == VALID_PARAMETERS


def test_shipped_stack_groups_match_legacy_tuple() -> None:
    vocab = get_rules().vocabularies
    assert vocab is not None
    groups = vocab.mainstream_groups
    assert tuple(group.key for group in groups) == (
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
    assert all(isinstance(group, StackGroup) for group in groups)
    assert all(group.pattern.flags & re.IGNORECASE for group in groups)
    # The confidential equiv guidance ships server-side and is always populated.
    assert all(group.equiv and group.hint and group.name for group in groups)
    boot = groups[0]
    assert boot.name == "Spring Boot"
    assert boot.pattern.search("SPRING boot") is not None


def test_shipped_degree_rank_patterns_are_highest_first() -> None:
    vocab = get_rules().vocabularies
    assert vocab is not None
    ranks = vocab.degree_rank_patterns_compiled
    assert [rank for rank, _pattern in ranks] == [5, 4, 3, 2, 1]
    assert ranks[0][1].search("博士研究生") is not None
    assert ranks[-1][1].pattern == "中专|中职|技校|高中"


def test_shipped_regex_library_matches_legacy_behavior() -> None:
    vocab = get_rules().vocabularies
    assert vocab is not None
    assert len(vocab.regexes) == 23
    assert vocab.regex("phone").search("手机号 13812345678") is not None
    # 17 digits followed by X: the 18-character ID-card shape.
    assert vocab.regex("id_card").search("11010119900307123X") is not None
    assert vocab.regex("email").search("a.b@example.co") is not None
    assert vocab.regex("internship").search("实习工程师") is not None
    assert vocab.regex("work_overlap_note").search("外包驻场") is not None
    # IGNORECASE-flagged patterns survived the YAML round trip.
    assert vocab.regexes["open_ended"].flags & re.IGNORECASE
    assert vocab.regexes["tech_vocab"].flags & re.IGNORECASE
    assert vocab.regexes["amateur_project"].flags & re.IGNORECASE


def test_shipped_tokens_and_template_labels() -> None:
    vocab = get_rules().vocabularies
    assert vocab is not None
    assert tuple(vocab.advantage_title_tokens) == ("个人优势", "核心优势", "个人亮点")
    assert tuple(vocab.advantage_key_tokens) == (
        "personal_advantage",
        "advantage",
        "strength",
        "highlight",
        "competency",
    )
    assert tuple(vocab.selfeval_title_tokens) == ("自我评价", "个人总结", "个人评价")
    assert tuple(vocab.selfeval_key_tokens) == (
        "self_evaluation",
        "self_eval",
        "self_appraisal",
        "selfassessment",
    )
    assert vocab.template_labels["swiss-single"] == "经典单栏"
    assert len(vocab.template_labels) == 7


# ---------------------------------------------------------------------------
# Fail-fast validation on synthetic artifacts.
# ---------------------------------------------------------------------------


def test_parameters_require_every_field() -> None:
    raw = dict(VALID_PARAMETERS)
    del raw["chars_per_line"]
    with pytest.raises(ValidationError):
        DiagnosisParameters.model_validate(raw)


def test_parameters_reject_unknown_and_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        DiagnosisParameters.model_validate({**VALID_PARAMETERS, "unknown": 1})
    with pytest.raises(ValidationError):
        DiagnosisParameters.model_validate(
            {**VALID_PARAMETERS, "chars_per_line": 0}
        )
    with pytest.raises(ValidationError):
        DiagnosisParameters.model_validate(
            {**VALID_PARAMETERS, "stack_conform_ratio": 1.5}
        )


def test_parameter_band_ordering_is_validated() -> None:
    with pytest.raises(ValidationError, match="skill_count"):
        DiagnosisParameters.model_validate(
            {**VALID_PARAMETERS, "skill_count_min": 16, "skill_count_max": 15}
        )
    with pytest.raises(ValidationError, match="stack_partial_ratio"):
        DiagnosisParameters.model_validate(
            {
                **VALID_PARAMETERS,
                "stack_partial_ratio": 0.9,
                "stack_conform_ratio": 0.75,
            }
        )


def test_vocabularies_reject_bad_regex() -> None:
    raw = {
        **VALID_VOCABULARIES,
        "regex_patterns": {"broken": {"pattern": "(unclosed"}},
    }
    with pytest.raises(ValidationError, match="does not compile"):
        DiagnosisVocabularies.model_validate(raw)


def test_vocabularies_reject_duplicate_stack_keys_and_ranks() -> None:
    duplicated_group = {
        **VALID_VOCABULARIES,
        "mainstream_stack_groups": [
            VALID_VOCABULARIES["mainstream_stack_groups"][0],
            {
                **VALID_VOCABULARIES["mainstream_stack_groups"][0],
                "name": "Duplicate key group",
            },
        ],
    }
    with pytest.raises(ValidationError, match="keys must be present and unique"):
        DiagnosisVocabularies.model_validate(duplicated_group)

    duplicated_rank = {
        **VALID_VOCABULARIES,
        "degree_rank_patterns": [
            {"rank": 5, "pattern": "博士"},
            {"rank": 5, "pattern": "硕士"},
        ],
    }
    with pytest.raises(ValidationError, match="ranks must be present and unique"):
        DiagnosisVocabularies.model_validate(duplicated_rank)


def test_vocabularies_reject_blank_and_duplicate_tokens() -> None:
    with pytest.raises(ValidationError):
        DiagnosisVocabularies.model_validate(
            {**VALID_VOCABULARIES, "advantage_title_tokens": ["ok", "ok"]}
        )
    with pytest.raises(ValidationError):
        DiagnosisVocabularies.model_validate(
            {**VALID_VOCABULARIES, "advantage_title_tokens": ["ok", " "]}
        )


def test_get_rules_fails_loudly_when_artifact_section_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    minimal_doc = {"spec_version": "V4", "items": [], "dimensions": []}
    get_rules.cache_clear()
    monkeypatch.setattr(diagnosis_rules, "load_rules", lambda: minimal_doc)
    try:
        with pytest.raises(ValueError, match="missing section"):
            get_rules()
    finally:
        get_rules.cache_clear()
    # Restore the loader explicitly before touching the real artifact again;
    # the fixture's own teardown will simply undo an already-undone patch.
    monkeypatch.undo()
    get_rules.cache_clear()
    assert get_rules().parameters is not None
