"""Contract locks on the shipped diagnosis rubric artifact.

The rubric text is LLM-judged, so a wording regression silently changes real
diagnoses. These tests lock user-mandated rubric constraints at the artifact
level (and, where the judge prompt repeats them, at the prompt level).
"""

from app.prompts.diagnosis import DIAGNOSIS_PROMPT
from app.services.diagnosis_rules import get_rules


def test_item_11_certificate_issuer_and_date_are_never_mandatory() -> None:
    """Missing issuer/date must never lower a certificate item's verdict.

    A bare "(选填)" marker did not stop the judge from downgrading
    name-only certificates. The criterion must state the prohibition
    explicitly: no 不符合/部分符合, no scoring penalty for missing fields.
    """
    item = get_rules().item(11)
    assert item["sub_dimension"] == "培训与证书"

    criterion = item["criterion"]
    assert "证书 / 培训名称为必填" in criterion
    assert "颁发机构、获取时间均为选填" in criterion
    assert "不得判为不符合 / 部分符合" in criterion
    assert "扣分" in criterion

    # The 🟡 time-format finding applies only when a date was actually given.
    qc = item["qc"]
    assert "已填写获取时间但格式不符合" in qc


def test_item_11_no_penalty_guard_is_in_judge_prompt() -> None:
    """The judge prompt repeats the rule so the model cannot miss it."""
    assert "颁发机构与获取时间均为选填" in DIAGNOSIS_PROMPT
    assert "不得判为不符合 / 部分符合" in DIAGNOSIS_PROMPT


def test_item_12_award_issuer_and_date_are_never_mandatory() -> None:
    """A missing award issuer/date must never lower the item's verdict.

    Only the award name is required; issuer and date are optional. The 🟡
    time-format finding applies only when a date was actually given.
    """
    item = get_rules().item(12)
    assert item["sub_dimension"] == "荣誉奖项"

    criterion = item["criterion"]
    assert "奖项名称为必填" in criterion
    assert "颁发主体、获奖时间均为选填" in criterion
    assert "不得判为不符合 / 部分符合" in criterion
    assert "扣分" in criterion

    assert "已填写获奖时间但格式不符合" in item["qc"]
    assert "缺少获奖时间或颁发主体本身不违规" in item["qc"]


def test_item_12_no_penalty_guard_is_in_judge_prompt() -> None:
    """The judge prompt repeats the award rule so the model cannot miss it."""
    assert "颁发主体、获奖时间均为选填" in DIAGNOSIS_PROMPT
    # The shared prohibition clause covers both items 11 and 12.
    assert "不得判为不符合 / 部分符合" in DIAGNOSIS_PROMPT
