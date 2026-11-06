"""Tests for competency models (Java P3–P8 level matrix shipped, rubric V4)."""

import re

import pytest

from app.services.diagnosis_competency import (
    NO_COMPETENCY_MODEL_KEY,
    CompetencyModel,
    expand_rules,
    get_competency_model,
    parse_competency_models,
    resolve_competency_model,
    select_competency_model,
)
from app.services.diagnosis_rules import COMPETENCE_DIMENSION_KEY, get_rules


def test_shipped_catalog_is_the_java_level_matrix() -> None:
    models = parse_competency_models(get_rules().competency_models)
    assert [m.key for m in models] == ["java-p3", "java-p4", "java-p5", "java-p6", "java-p7", "java-p8"]
    assert [m.level for m in models] == ["P3", "P4", "P5", "P6", "P7", "P8"]
    assert all(m.family == "Java" for m in models)
    # Five capability elements per level, each filling one base item 18–22.
    assert all(len(m.items) == 5 for m in models)
    p5 = next(m for m in models if m.key == "java-p5")
    assert {item["item_id"] for item in p5.items} == {18, 19, 20, 21, 22}
    assert {item["sub_dimension"] for item in p5.items} == {
        "系统架构",
        "业务架构",
        "开发技能",
        "应用技能",
        "项目管理",
    }
    assert all(item["criterion"] for item in p5.items)


@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Java 开发工程师", "java-p4"),  # generic title defaults to mid level
        ("初级Java开发工程师", "java-p3"),
        ("高级Java开发工程师", "java-p5"),
        ("资深 Java 开发工程师", "java-p6"),
        ("Java架构师", "java-p7"),
        ("Java 技术专家", "java-p8"),
        ("大数据开发工程师", None),  # no match → the UI lets the user choose
        ("Java/大数据/前端", None),
    ],
)
def test_shipped_title_auto_matching(title: str, expected_key: str | None) -> None:
    models = parse_competency_models(get_rules().competency_models)
    chosen = select_competency_model(models, title)
    assert (chosen.key if chosen else None) == expected_key


def test_parse_valid_model_and_skips_malformed() -> None:
    raw = [
        {
            "key": "java-backend",
            "name": "Java 后端专业能力模型",
            "family": "Java",
            "level": "P5",
            "title_patterns": ["(?i)java", "后端开发"],
            "items": [
                {"item_id": 17, "sub_dimension": "系统架构", "criterion": "熟悉 Spring Cloud"}
            ],
        },
        {"key": "", "name": "无 key 模型", "items": []},  # skipped: no key
        {"key": "x", "name": "无 items 模型"},  # kept but itemless (expand is no-op)
    ]
    models = parse_competency_models(raw)
    assert len(models) == 2
    java = models[0]
    assert java.key == "java-backend"
    assert java.family == "Java"
    assert java.level == "P5"
    assert len(java.title_patterns) == 2
    assert len(java.items) == 1


def test_invalid_regex_raises() -> None:
    with pytest.raises(re.error):
        parse_competency_models(
            [{"key": "k", "name": "n", "title_patterns": ["([unclosed"], "items": []}]
        )


def test_select_matches_title_and_handles_blank() -> None:
    models = parse_competency_models(
        [
            {
                "key": "java-backend",
                "name": "Java 后端专业能力模型",
                "title_patterns": ["(?i)java"],
                "items": [{"item_id": 17, "criterion": "a"}],
            },
            {
                "key": "frontend",
                "name": "前端专业能力模型",
                "title_patterns": ["前端|frontend"],
                "items": [{"item_id": 17, "criterion": "b"}],
            },
        ]
    )
    assert select_competency_model(models, None) is None
    assert select_competency_model(models, "   ") is None
    chosen = select_competency_model(models, "高级 Java 架构师")
    assert chosen is not None and chosen.key == "java-backend"
    assert select_competency_model(models, "数据分析师") is None
    # First matching model in document order wins on overlap.
    overlap = select_competency_model(models, "Java 前端工程师")
    assert overlap is not None and overlap.key == "java-backend"


def test_matches_uses_search_not_fullmatch() -> None:
    model = parse_competency_models(
        [{"key": "k", "name": "n", "title_patterns": ["(?i)java"], "items": [{"item_id": 17}]}]
    )[0]
    assert isinstance(model, CompetencyModel)
    assert model.matches("资深 Java 开发") is True
    assert model.matches("产品经理") is False


def test_resolve_explicit_key_wins_over_title_and_validates() -> None:
    models = parse_competency_models(get_rules().competency_models)
    # Non-matching title + explicit choice: the choice wins.
    chosen = resolve_competency_model(models, "大数据开发工程师", "java-p7")
    assert chosen is not None and chosen.key == "java-p7"
    assert get_competency_model(models, " java-p5 ").key == "java-p5"
    assert get_competency_model(models, None) is None
    with pytest.raises(KeyError):
        resolve_competency_model(models, "Java 开发工程师", "no-such-level")
    # Blank explicit key falls back to title matching.
    fallback = resolve_competency_model(models, "高级Java开发工程师", "  ")
    assert fallback is not None and fallback.key == "java-p5"


def test_resolve_explicit_none_opts_out_of_title_matching() -> None:
    models = parse_competency_models(get_rules().competency_models)
    # Even a title that would auto-match P4 runs base-only once the user
    # explicitly confirms "no competency model".
    assert (
        resolve_competency_model(models, "Java 开发工程师", NO_COMPETENCY_MODEL_KEY)
        is None
    )
    assert resolve_competency_model(models, "Java 开发工程师", " none ") is None


def test_expand_none_returns_base_untouched() -> None:
    base = get_rules()
    assert expand_rules(base, None) is base


def test_expand_itemless_model_is_noop() -> None:
    base = get_rules()
    models = parse_competency_models([{"key": "x", "name": "空模型", "items": []}])
    assert expand_rules(base, models[0]) is base


def test_expand_fills_competence_items_in_place() -> None:
    base = get_rules()
    # Pointer text shipped for the 专业能力 rows (the workbook says "去 Sheet2
    # 找对应职级……"); a matched model replaces it with concrete standards.
    assert "Sheet2" in base.items[18]["criterion"]

    models = parse_competency_models(
        [
            {
                "key": "java-backend",
                "name": "P5 高级Java开发工程师能力模型",
                "title_patterns": ["java"],
                "items": [
                    {"item_id": 18, "sub_dimension": "系统架构", "criterion": "标准 A"},
                    {"item_id": 22, "sub_dimension": "项目管理", "criterion": "标准 B"},
                    # Unknown / missing target ids are ignored, never appended.
                    {"item_id": 999, "sub_dimension": "不存在", "criterion": "X"},
                    {"sub_dimension": "无 id", "criterion": "Y"},
                ],
            }
        ]
    )
    expanded = expand_rules(base, models[0])

    # No synthetic items or dimensions: the checklist stays at 22 / 7.
    assert len(expanded.items) == 22
    assert expanded.dimension_order == base.dimension_order
    assert expanded.dimension_order[-1] == COMPETENCE_DIMENSION_KEY

    # The targeted base rows keep their public metadata, gain the standards.
    assert expanded.items[18]["criterion"] == "标准 A"
    assert expanded.items[18]["dimension"] == COMPETENCE_DIMENSION_KEY
    assert expanded.items[18]["dimension_name"] == "专业能力"
    assert expanded.items[18]["sub_dimension"] == "系统架构"
    assert expanded.items[18]["topic"] == "系统架构"
    assert expanded.items[22]["criterion"] == "标准 B"
    # Untouched competence rows still carry the pointer text.
    assert "Sheet2" in expanded.items[19]["criterion"]
    assert 999 not in expanded.items
    # Model items are normal severity and invent no red lines.
    assert expanded.redline_ids == base.redline_ids == (16,)
    # Global rules travel through the expansion unchanged.
    assert expanded.global_rules == base.global_rules

    # The cached base rules are never mutated.
    assert "Sheet2" in base.items[18]["criterion"]
    assert base.items[18]["criterion"] != "标准 A"


def test_shipped_p5_standards_differ_from_pointer_rows() -> None:
    """End-to-end: shipped P5 model fills all five base competence items."""
    base = get_rules()
    p5 = next(
        m
        for m in parse_competency_models(base.competency_models)
        if m.key == "java-p5"
    )
    expanded = expand_rules(base, p5)
    for item_id in (18, 19, 20, 21, 22):
        criterion = expanded.items[item_id]["criterion"]
        assert criterion
        assert "Sheet2" not in criterion
        assert criterion == next(
            e["criterion"] for e in p5.items if e["item_id"] == item_id
        )
