"""Tests for finding-text normalization (evidence/suggestion → point lines).

The UI and the Word export render findings as ordered lists, one point per
line. ``normalize_finding_points`` enforces that contract on whatever the LLM
or the deterministic checkers produced.
"""

import pytest

from app.services.diagnosis import normalize_finding_points


def test_empty_and_blank_return_empty_string() -> None:
    assert normalize_finding_points("") == ""
    assert normalize_finding_points("   \n  \n") == ""


def test_plain_prose_stays_a_single_line() -> None:
    text = "项目经历缺少技术栈字段，且职责描述没有量化结果。"
    assert normalize_finding_points(text) == text


def test_multiple_lines_keep_their_order_and_drop_blanks() -> None:
    assert normalize_finding_points("第一点。\n\n第二点。\n  第三点。\n") == (
        "第一点。\n第二点。\n第三点。"
    )


def test_strips_leading_numbering_per_line() -> None:
    assert normalize_finding_points("1、缺少技术栈字段。\n2. 缺少量化结果。\n3) 时间倒序错误。") == (
        "缺少技术栈字段。\n缺少量化结果。\n时间倒序错误。"
    )


def test_strips_bullet_and_circled_markers() -> None:
    assert normalize_finding_points("- 缺模块：项目经历\n• 缺时间") == (
        "缺模块：项目经历\n缺时间"
    )
    assert normalize_finding_points("①缺少教育模块\n②缺少证书模块") == (
        "缺少教育模块\n缺少证书模块"
    )


@pytest.mark.parametrize(
    "text",
    [
        "升级到 JDK 1.8，性能提升 2.5 倍。",
        "主导 SpringBoot 2.x 到 3.x 的升级。",
        "覆盖率从 60% 提升到 90%，QPS 达到 2.0 万。",
    ],
)
def test_decimals_and_versions_are_not_split(text: str) -> None:
    assert normalize_finding_points(text) == text


def test_splits_points_glued_after_sentence_punctuation() -> None:
    assert normalize_finding_points("项目缺少技术栈；2. 职责没有量化结果。3. 时间倒序。") == (
        "项目缺少技术栈\n职责没有量化结果。\n时间倒序。"
    )


def test_splits_whitespace_glued_points_when_the_line_started_numbered() -> None:
    assert normalize_finding_points("1. 缺技术栈 2. 缺量化结果 3. 时间倒序") == (
        "缺技术栈\n缺量化结果\n时间倒序"
    )


def test_splits_glued_circled_points_without_punctuation() -> None:
    assert normalize_finding_points("缺教育模块②缺证书模块③缺时间") == (
        "缺教育模块\n缺证书模块\n缺时间"
    )


def test_na_notice_with_no_markers_is_untouched() -> None:
    text = "未提供目标岗位 JD，岗位匹配度检查项不适用。"
    assert normalize_finding_points(text) == text
