"""Service-level diagnosis tests with the LLM call mocked (rubric V4).

Pins the V4-optimized contract:

* the checklist always carries 22 items / 7 dimensions (competence items
  18–22 are base items, filled in place by the matched level model — no
  synthetic ids, no trailing dimension);
* prerequisite gating: item 17 is na without a JD; items 18–22 are na only
  when no target intention resolves to a level model (a JD is NOT required —
  a no-JD run with a matching intention still judges 18–22); item 15 is
  objectively na below 5 effective dev years;
* the rubric standards (criteria, QC-level guidance, level behavioral
  standards) are sent to the LLM server-side but never appear in the returned
  report — clients only see topic + evidence + suggestion. The V4 workbook
  ships no global-rule sheet.
"""

import copy
import json
import re
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.services.diagnosis import diagnose_resume
from app.services.diagnosis_rules import DiagnosisRules, get_rules

SAMPLE_RESUME: dict = {
    "personalInfo": {
        "name": "王浩",
        "gender": "男",
        "phone": "13812345678",
        "email": "wang@example.com",
        "title": "Java 开发工程师",
        "location": "上海",
    },
    "summary": "",
    "workExperience": [
        {
            "id": 1,
            "company": "甲公司",
            "title": "Java 开发工程师",
            "years": "2023.01 至今",
            "description": ["负责交易系统开发"],
        }
    ],
    "education": [
        {
            "id": 1,
            "institution": "甲大学",
            "description": "软件工程",
            "degree": "统招本科",
            "years": "2015.09 - 2019.06",
        }
    ],
    "personalProjects": [],
    "additional": {
        "technicalSkills": ["Java", "Spring Boot", "MySQL"],
        # Entries keep modules 11/12 present, so they stay in the LLM-judged
        # set; the empty-module na path is covered separately below.
        "certificationsTraining": ["Oracle 认证 Java 程序员（OCP）"],
        "awards": ["公司年度技术之星"],
        "languages": ["英语四级"],
    },
}

SAMPLE_JD = "招聘 Java 开发工程师，要求 Spring Cloud、K8s、高并发经验"

# The sample's intention title auto-matches the shipped P4 model.
DEFAULT_TITLE = "Java 开发工程师"
DEFAULT_MODEL_KEY = "java-p4"
JD_GATED_IDS = {17}
COMPETENCE_IDS = {18, 19, 20, 21, 22}
# Content items judged by the LLM without any prerequisite gate.
SEMANTIC_BASE_IDS = {11, 12}


async def _all_conform_side_effect(*args: object, **kwargs: object) -> dict:
    """Answer exactly the ids this run asked for (extra ids would fail the
    service-side validator)."""
    prompt = str(kwargs["prompt"])
    return _llm_payload(sorted(_requested_ids(prompt)))


@contextmanager
def _patched_llm():
    config = object()
    with patch(
        "app.services.diagnosis.complete_json", new_callable=AsyncMock
    ) as mock_complete, patch(
        "app.services.diagnosis.get_llm_config", return_value=config
    ), patch(
        "app.services.diagnosis.get_model_name", return_value="openai/test-model"
    ), patch(
        "app.services.diagnosis.get_safe_max_tokens", return_value=12000
    ):
        mock_complete.side_effect = _all_conform_side_effect
        yield mock_complete


def _llm_payload(item_ids: list[int], rating: str = "conform") -> dict:
    return {
        "items": [
            {
                "id": item_id,
                "rating": rating,
                "evidence": f"证据-{item_id}",
                "suggestion": f"建议-{item_id}" if rating != "conform" else "",
            }
            for item_id in item_ids
        ]
    }


def _all_conform_payload() -> dict:
    """Payload covering every id; the service only merges requested ones."""
    return _llm_payload(list(range(1, 23)))


def _requested_ids(prompt: str) -> set[int]:
    """Extract the id list from the prompt's assigned-items section."""
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# 需要你评估的检查项"):
            raw = lines[index + 1]
            return {int(token) for token in re.findall(r"\d+", raw)}
    raise AssertionError("assigned-items section not found in prompt")


def _p4_standard_snippet() -> str:
    """A distinctive slice of the shipped P4 item-18 standard (server-only)."""
    raw = get_rules().competency_models
    p4 = next(model for model in raw if model["key"] == "java-p4")
    criterion = next(item["criterion"] for item in p4["items"] if item["item_id"] == 18)
    snippet = criterion[:18].strip()
    assert len(snippet) >= 10
    return snippet


@pytest.mark.asyncio
async def test_diagnose_always_returns_22_items_across_7_dimensions() -> None:
    # Tenure ("2023.01 至今") is counted inclusively against the wall clock,
    # so freeze the reference month — otherwise the pinned "3.8 年" flips to
    # 3.9 every November and the test goes red on a calendar boundary.
    with patch(
        "app.services.diagnosis_checks._now_point", return_value=(2026, 10)
    ), _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    assert report.spec_version == "V4"
    assert len(report.items) == 22
    assert {item.id for item in report.items} == set(range(1, 23))
    assert [dim.key for dim in report.dimensions] == [
        "appearance",
        "content",
        "stability",
        "growth",
        "compliance",
        "fit",
        "competence",
    ]
    assert report.dimensions[-1].name == "专业能力"
    assert [redline.id for redline in report.redlines] == [16]

    # Counts cover every item exactly once.
    counts = report.counts
    assert counts.conform + counts.partial + counts.nonconform == counts.effective
    assert counts.effective + counts.na == 22

    by_id = {item.id: item for item in report.items}
    # Objective items keep their deterministic verdicts (sample: item 16 privacy
    # conforms, item 4 basic info is complete).
    assert by_id[16].rating == "conform"
    assert by_id[16].judgment_method == "objective"
    assert by_id[4].judgment_method == "objective"
    # The semantic content items (11 certifications/training, 12 awards) come
    # from the LLM.
    assert by_id[11].judgment_method == "subjective"
    assert by_id[12].judgment_method == "subjective"

    # Contract: a conforming row is a clean checkbox — no problem description
    # and no advice, regardless of whether the checker or the LLM produced it.
    for item in report.items:
        if item.rating == "conform":
            assert item.evidence == "", item.id
            assert item.suggestion == "", item.id
    # The LLM payload carried positive "证据-11/12" text for the conforming rows;
    # the service must strip it rather than trusting the model to obey.
    for item_id in (11, 12):
        assert by_id[item_id].rating == "conform"
        assert by_id[item_id].evidence == ""
        assert by_id[item_id].suggestion == ""
    # Sample tenure (~3.8y) is below 5 effective dev years: item 15 objectively
    # na and never sent to the LLM.
    assert by_id[15].rating == "na"
    assert by_id[15].judgment_method == "objective"
    # Evidence states the resume fact only; the five-year cutoff is server-side.
    assert "3.8 年" in by_id[15].evidence
    assert "5 年" not in by_id[15].evidence and "按规则" not in by_id[15].evidence
    assert report.warnings == []
    _, kwargs = mock_complete.await_args
    assert kwargs["schema_type"] == "diagnosis"


@pytest.mark.asyncio
async def test_problem_text_flows_only_for_nonconforming_rows() -> None:
    """partial keeps its problem text; conform rows stay blank even when the
    model disobeys the prompt and fills them with praise / keep-it-up advice."""

    async def chatty_side_effect(*args: object, **kwargs: object) -> dict:
        requested = sorted(_requested_ids(str(kwargs["prompt"])))
        return {
            "items": [
                {
                    "id": item_id,
                    "rating": "partial" if item_id == 11 else "conform",
                    "evidence": f"证据-{item_id}",
                    "suggestion": (
                        f"建议-{item_id}"
                        if item_id == 11
                        else "整体表现良好，建议继续保持"
                    ),
                }
                for item_id in requested
            ]
        }

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = chatty_side_effect
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    # The problem row keeps both its grounded description and its fix.
    assert by_id[11].rating == "partial"
    assert by_id[11].evidence == "证据-11"
    assert by_id[11].suggestion == "建议-11"
    # Every conforming row — objective and subjective — is silent.
    for item in report.items:
        if item.rating == "conform":
            assert item.evidence == "", item.id
            assert item.suggestion == "", item.id

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "没有问题就不要写问题描述" in prompt
    assert "conform 一律返回空的 evidence 和空的 suggestion" in prompt


@pytest.mark.asyncio
async def test_judge_is_grounded_in_the_original_resume_text() -> None:
    """The uploaded resume verbatim reaches the judge prompt as the fact basis;
    the structured JSON is demoted to a locating view."""
    original = (
        "# 王浩 简历\n\n求职意向：Java 开发工程师\n\n"
        "独特原文片段：在交易中台主导了幂等对账改造，覆盖跨境清结算链路。\n"
    )
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            original_markdown=original,
        )

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "用户原始简历" in prompt
    assert "独特原文片段：在交易中台主导了幂等对账改造" in prompt
    # Module organization is anchored to structured data / facts; raw text is
    # the content-detail basis — the old "single source of truth" framing is
    # what allowed the 「其他」-section false positive.
    assert "事实依据分两层" in prompt
    # The structured view is still sent for module/field location.
    assert "结构化数据" in prompt
    assert report.warnings == []


@pytest.mark.asyncio
async def test_without_original_text_the_prompt_omits_the_original_block() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    prompt = mock_complete.await_args.kwargs["prompt"]
    # The grounding rule is always present; the verbatim resume section is not.
    assert "# 用户原始简历（上传简历的原文转写；内容细节以此为准，模块归属以结构化数据为准）" not in prompt


@pytest.mark.asyncio
async def test_original_resume_block_is_bounded_and_flags_omission() -> None:
    """Originals over the prompt bound are truncated with an explicit notice
    instead of silently dropping the tail."""
    tail_marker = "末尾锚点：这一段只出现在原文最后，截断后不应进入提示词。"
    original = "# 王浩\n\n" + ("负责交易系统的日常开发与维护工作。\n" * 1300) + tail_marker
    assert len(original) > 20_000
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            original_markdown=original,
        )

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert tail_marker not in prompt
    assert "[Content truncated for prompt length." in prompt


@pytest.mark.asyncio
async def test_privacy_redline_scans_the_original_resume_text() -> None:
    """A sensitive token dropped by structured extraction still fails #16:
    deterministic grounding must cover the original upload, not just JSON."""
    clean_resume = {
        "personalInfo": {"name": "王浩", "phone": "13812345678"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    original = "王浩 简历\n身份证号码：110101199003071234\n电话 13812345678"
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            clean_resume,
            resume_id="r1",
            language="zh",
            original_markdown=original,
        )

    item16 = {item.id: item for item in report.items}[16]
    assert item16.rating == "nonconform"
    assert "身份证" in item16.evidence
    assert report.redline_passed is False


@pytest.mark.asyncio
async def test_objective_problem_rows_carry_signal_specific_suggestions() -> None:
    """Deterministic findings carry their own matching fix; a merged item's
    suggestion never covers sub-checks that passed."""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    # SAMPLE_RESUME lists only 3 skills: item 7 objectively fails and the fix
    # must be the skill-specific one.
    item7 = by_id[7]
    assert item7.rating == "nonconform"
    assert "技能" in item7.evidence
    assert item7.suggestion
    # Item 3 fails solely on missing projects; its fix names 项目经验 and says
    # nothing about skills, ordering or paragraphs (those signals passed).
    item3 = by_id[3]
    assert item3.rating in ("partial", "nonconform")
    assert "项目经验" in item3.evidence
    assert "项目经验" in item3.suggestion
    assert "技能条目" not in item3.suggestion
    assert "段落" not in item3.suggestion
    # A conforming objective row stays silent even at the report boundary.
    assert by_id[4].rating == "conform"
    assert by_id[4].evidence == "" and by_id[4].suggestion == ""


@pytest.mark.asyncio
async def test_no_jd_gates_only_item_17_but_competence_still_judged() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    item17 = by_id[17]
    assert item17.rating == "na"
    assert "JD" in item17.evidence
    # V4: a matching 求职意向 is enough — 18–22 are judged without a JD.
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "conform"
        assert by_id[item_id].judgment_method == "subjective"
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert 17 not in requested
    assert COMPETENCE_IDS <= requested
    # Plus the two ordinary semantic items (11/12) the objective layer doesn't cover.
    assert requested == SEMANTIC_BASE_IDS | COMPETENCE_IDS


@pytest.mark.asyncio
async def test_empty_optional_modules_are_objectively_na_even_with_catchall_markdown() -> None:
    """Regression: a raw upload grouping the cert under 「◆ 其他」 once made
    the LLM report the 培训与证书 module as empty and a language line as
    duplicated. With no structured entries, 11/12 are deterministically na
    and never reach the LLM — module existence is not a model judgment."""
    resume = copy.deepcopy(SAMPLE_RESUME)
    resume["additional"] = {"technicalSkills": ["Java", "Spring Boot", "MySQL"]}
    raw_markdown = (
        "# 王浩\n\n"
        "外语水平：**英语四级** 求职意向：Java 开发工程师\n\n"
        "◆ 其他\n1. 项目管理：信息系统项目管理师（高项）证书；\n"
        "2. 外语水平：英语四级。\n"
    )
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            resume,
            resume_id="r1",
            language="zh",
            original_markdown=raw_markdown,
        )

    by_id = {item.id: item for item in report.items}
    assert by_id[11].rating == "na"
    assert by_id[12].rating == "na"
    assert by_id[11].judgment_method == "objective"
    assert by_id[12].judgment_method == "objective"
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert 11 not in requested and 12 not in requested


@pytest.mark.asyncio
async def test_optional_module_entries_ride_the_facts_packet() -> None:
    """Entries under additional.certificationsTraining / .awards / .languages
    are presented as authoritative module content in facts, so the judge maps
    them to 培训与证书 / 荣誉奖项 / 表头外语水平 regardless of JSON field
    names or the raw upload's catch-all grouping."""
    raw_markdown = "# 王浩\n\n◆ 其他\n1. 项目管理：Oracle 认证 Java 程序员（OCP）；\n"
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            original_markdown=raw_markdown,
        )

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "certifications_training" in prompt
    assert "Oracle 认证 Java 程序员（OCP）" in prompt
    assert "公司年度技术之星" in prompt
    assert "英语四级" in prompt
    requested = _requested_ids(prompt)
    assert {11, 12} <= requested
    # The prompt explicitly remaps raw catch-all headings to canonical modules.
    assert "其他" in prompt and "certificationsTraining" in prompt


@pytest.mark.asyncio
async def test_matched_title_with_jd_judges_competence_18_to_22_in_place() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            language="zh",
        )

    assert report.competency_model is not None
    assert report.competency_model.key == DEFAULT_MODEL_KEY
    by_id = {item.id: item for item in report.items}
    for item_id, topic in zip(
        COMPETENCE_IDS, ("系统架构", "业务架构", "开发技能", "应用技能", "项目管理"), strict=True
    ):
        item = by_id[item_id]
        assert item.dimension == "competence"
        assert item.dimension_name == "专业能力"
        assert item.topic == topic
        assert item.judgment_method == "subjective"
        assert item.rating == "conform"
    # Item 17 (JD fit) is judged too once a JD is present.
    assert by_id[17].rating == "conform"
    assert by_id[17].judgment_method == "subjective"
    # No synthetic model items anywhere.
    assert all(item.id < 1000 for item in report.items)

    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert JD_GATED_IDS <= requested
    assert COMPETENCE_IDS <= requested


@pytest.mark.asyncio
async def test_target_title_defaults_to_resume_intention() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    assert report.target_title == DEFAULT_TITLE
    assert report.competency_model is not None
    assert report.competency_model.key == DEFAULT_MODEL_KEY
    prompt = mock_complete.await_args.kwargs["prompt"]
    assert DEFAULT_TITLE in prompt
    assert report.competency_model.name in prompt


@pytest.mark.asyncio
async def test_jd_without_title_judges_item_17_but_competence_na() -> None:
    # V4 gates item 17 on the JD and 18–22 on a resolvable intention: with a JD
    # but no intention, item 17 is judged; the level-model items 18–22 go na.
    resume = {**SAMPLE_RESUME, "personalInfo": {**SAMPLE_RESUME["personalInfo"]}}
    resume["personalInfo"]["title"] = ""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            resume,
            resume_id="r1",
            job_description=SAMPLE_JD,
            language="zh",
        )

    assert report.target_title is None
    assert report.competency_model is None
    by_id = {item.id: item for item in report.items}
    assert by_id[17].rating == "conform"
    assert by_id[17].judgment_method == "subjective"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "na"
        assert "求职意向" in by_id[item_id].evidence
        assert "能力模型" in by_id[item_id].evidence
    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "# 诊断目标岗位" not in prompt
    requested = _requested_ids(prompt)
    assert 17 in requested
    assert COMPETENCE_IDS.isdisjoint(requested)


@pytest.mark.asyncio
async def test_no_jd_and_no_intention_leaves_both_gates_na() -> None:
    # No JD and no intention: item 17 na (JD gate) AND 18–22 na (model gate),
    # independently.
    resume = {**SAMPLE_RESUME, "personalInfo": {**SAMPLE_RESUME["personalInfo"]}}
    resume["personalInfo"]["title"] = ""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(resume, resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    assert by_id[17].rating == "na"
    assert "JD" in by_id[17].evidence
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "na"
        assert "能力模型" in by_id[item_id].evidence
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert requested == SEMANTIC_BASE_IDS


@pytest.mark.asyncio
async def test_explicit_target_title_overrides_resume_intention() -> None:
    # A non-Java title matches no shipped model: with a JD item 17 is judged and
    # competence items go na.
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            target_title="  大数据开发工程师  ",
            language="zh",
        )

    # Explicit choice is trimmed and wins over personalInfo.title.
    assert report.target_title == "大数据开发工程师"
    assert report.competency_model is None
    # Checklist size never changes — competence rows stay, rated na.
    assert len(report.items) == 22
    assert len(report.dimensions) == 7
    by_id = {item.id: item for item in report.items}
    assert by_id[17].rating == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "na"
        assert "能力模型" in by_id[item_id].evidence
    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "大数据开发工程师" in prompt
    requested = _requested_ids(prompt)
    assert 17 in requested
    assert COMPETENCE_IDS.isdisjoint(requested)


@pytest.mark.asyncio
async def test_non_matching_title_without_jd_keeps_competence_gate_na() -> None:
    # Without a JD item 17 is na regardless; a non-matching intention also
    # leaves 18–22 na.
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            target_title="大数据开发工程师",
            language="zh",
        )

    by_id = {item.id: item for item in report.items}
    assert by_id[17].rating == "na"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "na"
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert requested == SEMANTIC_BASE_IDS


@pytest.mark.asyncio
async def test_explicit_competency_model_key_overrides_title_match() -> None:
    # Non-matching title + explicit user pick: the chosen P7 model fills 18–22
    # even without a JD (the two gates are independent).
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            target_title="大数据开发工程师",
            competency_model_key="java-p7",
            language="zh",
        )

    assert report.competency_model is not None
    assert report.competency_model.key == "java-p7"
    by_id = {item.id: item for item in report.items}
    assert all(by_id[item_id].rating == "conform" for item_id in COMPETENCE_IDS)
    assert by_id[17].rating == "na"  # still no JD
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert COMPETENCE_IDS <= requested
    assert 17 not in requested


@pytest.mark.asyncio
async def test_explicit_none_key_opts_out_of_competence_model() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            competency_model_key="none",
            language="zh",
        )

    assert report.competency_model is None
    by_id = {item.id: item for item in report.items}
    # Item 17 only needs the JD, so it is still judged; 18–22 need a model.
    assert by_id[17].judgment_method == "subjective"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "na"
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert COMPETENCE_IDS.isdisjoint(requested)


@pytest.mark.asyncio
async def test_unknown_competency_model_key_raises_key_error() -> None:
    # The router translates this into HTTP 400 (model no longer available).
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        with pytest.raises(KeyError):
            await diagnose_resume(
                SAMPLE_RESUME,
                resume_id="r1",
                competency_model_key="java-p99",
                language="zh",
            )


@pytest.mark.asyncio
async def test_diagnose_with_jd_sends_fit_items_to_llm() -> None:
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            language="zh",
        )

    by_id = {item.id: item for item in report.items}
    assert by_id[17].rating == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id].rating == "conform"
    requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
    assert JD_GATED_IDS | COMPETENCE_IDS <= requested


@pytest.mark.asyncio
async def test_custom_model_fills_base_competence_items_in_place() -> None:
    # A future rules artifact shipping an item_id-shaped model: standards fill
    # the existing 18–22 rows — never appended as synthetic items.
    raw_models = [
        {
            "key": "java-backend",
            "name": "Java 后端专业能力模型",
            "title_patterns": ["(?i)java"],
            "items": [
                {"item_id": 18, "sub_dimension": "系统架构", "criterion": "自定义架构标尺 Alpha"},
                {"item_id": 22, "sub_dimension": "项目管理", "criterion": "自定义管理标尺 Beta"},
            ],
        }
    ]
    base = get_rules()
    rules_with_model = DiagnosisRules(
        spec_version=base.spec_version,
        items=base.items,
        dimensions=base.dimensions,
        dimension_order=base.dimension_order,
        global_rules=base.global_rules,
        competency_models=raw_models,
    )
    with _patched_llm() as mock_complete, patch(
        "app.services.diagnosis.get_rules", return_value=rules_with_model
    ):
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            language="zh",
        )

    assert len(report.items) == 22
    assert all(item.id < 1000 for item in report.items)
    assert report.competency_model is not None
    assert report.competency_model.key == "java-backend"
    by_id = {item.id: item for item in report.items}
    # Rows keep their base metadata; the dimension name is the rubric's own.
    assert by_id[18].topic == "系统架构"
    assert by_id[18].dimension_name == "专业能力"
    assert by_id[22].topic == "项目管理"
    competence_dim = next(dim for dim in report.dimensions if dim.key == "competence")
    assert competence_dim.name == "专业能力"
    assert report.counts.effective + report.counts.na == 22
    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "自定义架构标尺 Alpha" in prompt
    assert "自定义管理标尺 Beta" in prompt


@pytest.mark.asyncio
async def test_missing_llm_item_defaults_partial_with_warning() -> None:
    # Without a JD the semantic ids are 11/12 plus the five competence items;
    # drop item 11 from the payload and check the partial fallback + warning.
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report_ok = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")
        assert report_ok.warnings == []
        requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
        assert requested == SEMANTIC_BASE_IDS | COMPETENCE_IDS

    with _patched_llm() as mock_complete:
        ids = [item_id for item_id in range(1, 23) if item_id != 11]
        mock_complete.side_effect = None
        mock_complete.return_value = _llm_payload(ids)
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    item = next(i for i in report.items if i.id == 11)
    assert item.rating == "partial"
    assert "人工复核" in item.evidence
    assert item.suggestion == ""
    assert any("11" in warning for warning in report.warnings)


@pytest.mark.asyncio
async def test_diagnosis_drops_global_reasoning_effort_for_judging() -> None:
    """DeepSeek burns the whole output budget on hidden reasoning when
    reasoning_effort is set, returning empty content. The judging call must
    pass an effort-free config copy without mutating the global config."""
    from app.llm import LLMConfig

    cfg = LLMConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        api_base="https://api.deepseek.com",
        reasoning_effort="medium",
    )
    with patch(
        "app.services.diagnosis.complete_json", new_callable=AsyncMock
    ) as mock_complete, patch(
        "app.services.diagnosis.get_llm_config", return_value=cfg
    ), patch(
        "app.services.diagnosis.get_model_name", return_value="deepseek/deepseek-chat"
    ), patch(
        "app.services.diagnosis.get_safe_max_tokens", return_value=8192
    ):
        mock_complete.return_value = _all_conform_payload()
        await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")

    _, kwargs = mock_complete.await_args
    assert kwargs["config"].reasoning_effort is None
    # The caller's config object is untouched.
    assert cfg.reasoning_effort == "medium"


@pytest.mark.asyncio
async def test_validator_drops_bad_rating_but_keeps_usable_items() -> None:
    """One bad entry is dropped; entries with valid ratings survive."""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")
        requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
        bad_id = sorted(requested)[0]
        good_id = sorted(requested)[1]
        assert bad_id == 11

    async def fake_complete(**kwargs: object) -> dict:
        validator = kwargs["response_validator"]  # type: ignore[assignment]
        return validator(  # type: ignore[operator]
            {
                "items": [
                    {"id": bad_id, "rating": "weird", "evidence": "", "suggestion": ""},
                    {
                        "id": str(good_id),  # numeric string id is tolerated
                        "rating": "partial",
                        "evidence": "e",
                        "suggestion": "s",
                    },
                ]
            }
        )

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = fake_complete
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")
        verdicts = {item.id: item.rating for item in report.items}
        assert verdicts[good_id] == "partial"


@pytest.mark.asyncio
async def test_validator_rejects_response_with_no_usable_items() -> None:
    """A payload whose every entry is unusable still triggers the retry budget."""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")
        requested = _requested_ids(mock_complete.await_args.kwargs["prompt"])
        bad_id = sorted(requested)[0]

    async def fake_complete(**kwargs: object) -> dict:
        validator = kwargs["response_validator"]  # type: ignore[assignment]
        return validator(  # type: ignore[operator]
            {"items": [{"id": bad_id, "rating": "weird", "evidence": "", "suggestion": ""}]}
        )

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = fake_complete
        with pytest.raises(ValueError, match="no usable items"):
            await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")


@pytest.mark.asyncio
async def test_report_never_leaks_rubric_standards() -> None:
    """Criteria, QC guidance and level standards reach the prompt only."""
    with _patched_llm() as mock_complete:
        mock_complete.return_value = _all_conform_payload()
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            job_description=SAMPLE_JD,
            language="zh",
        )
        prompt = mock_complete.await_args.kwargs["prompt"]

    # The level standards are present server-side in the judging prompt...
    snippet = _p4_standard_snippet()
    assert snippet in prompt
    # ...as is the QC-level guidance for the ordinary checklist items.
    assert "质检违规等级建议" in prompt
    assert "英语四六级重复填写" in prompt  # distinctive phrase from item 11's QC text
    # The V4 workbook ships no global-rule sheet: nothing of the kind exists.
    assert "全局通用规则" not in prompt
    assert "判定归属与去重规则" not in prompt

    # ...but nowhere in the client-facing report (items, red lines, the lot).
    report_text = json.dumps(report.model_dump(), ensure_ascii=False)
    assert snippet not in report_text
    assert "英语四六级重复填写" not in report_text
    assert "判定归属与去重规则" not in report_text
    assert "全局通用规则" not in report_text
    assert "质检违规等级建议" not in report_text
    assert "criterion" not in report.model_dump()
    for item in report.items:
        assert not hasattr(item, "criterion")
        assert not hasattr(item, "qc")
    for redline in report.redlines:
        assert not hasattr(redline, "criterion")
    # The competence pointer text ("go look up Sheet2") is internal too.
    assert "sheet2" not in report_text.casefold()

    # Every finding nevertheless carries the public location label and text.
    for item in report.items:
        assert item.topic


# --- item 7: LLM semantic review of regex-missed stack groups ---------------

# Six regex hits (boot/cloud/redis/mq/concurrency/ai_coding) plus three
# synonym entries the regex misses: MyBatis-Plus (RDBMS), GC/classloading
# (JVM), RAG (AI application). 9 entries keeps the skill-count signal conform.
_REVIEW_SKILLS = [
    "Spring Boot",
    "Spring Cloud Alibaba",
    "Redis",
    "RocketMQ",
    "多线程编程",
    "Claude Code",
    "MyBatis-Plus 持久层开发",
    "GC 调优与类加载机制",
    "RAG 检索增强应用开发",
]

_REVIEW_MISS_GROUPS = ("rdbms", "jvm", "ai_app")

_GROUNDED_REVIEWS = [
    {"group": "rdbms", "covered": True, "quote": "MyBatis-Plus"},
    {"group": "jvm", "covered": True, "quote": "GC 调优"},
    {"group": "ai_app", "covered": True, "quote": "RAG 检索增强"},
]


def _review_resume(skills: list[str] | None = None) -> dict:
    return {**SAMPLE_RESUME, "additional": {"technicalSkills": list(skills or _REVIEW_SKILLS)}}


def _payload_with_review(requested: set[int], review: list[dict] | None) -> dict:
    payload = _llm_payload(sorted(requested))
    if review is not None:
        payload["skill_group_review"] = review
    return payload


@pytest.mark.asyncio
async def test_skill_review_rescues_grounded_synonym_groups() -> None:
    """Grounded rescues flip item 7 partial→conform; item 7 rides the judge
    call as an auxiliary task (it never appears in the requested items)."""

    async def reviewing_side_effect(*args: object, **kwargs: object) -> dict:
        requested = _requested_ids(str(kwargs["prompt"]))
        assert 7 not in requested
        return _payload_with_review(requested, _GROUNDED_REVIEWS)

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = reviewing_side_effect
        report = await diagnose_resume(_review_resume(), resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    assert by_id[7].rating == "conform"
    assert by_id[7].evidence == ""
    assert by_id[7].suggestion == ""
    # The verdict involved the LLM review even though 7 is an objective item.
    assert by_id[7].judgment_method == "subjective"

    prompt = mock_complete.await_args.kwargs["prompt"]
    assert "# 附加任务：技能分组语义复核" in prompt
    assert "MyBatis-Plus 持久层开发" in prompt
    for key in _REVIEW_MISS_GROUPS:
        assert f"- {key}：" in prompt
    # Regex-hit groups are not offered for review (the rdbms equivalence note
    # itself mentions Redis, so assert on the group-line prefix).
    assert "- redis：" not in prompt
    assert "- spring_boot：" not in prompt


@pytest.mark.asyncio
async def test_skill_review_rejects_ungrounded_quotes() -> None:
    """covered=true with a quote absent from the skill entries cannot rescue:
    the deterministic partial verdict and its fix stand unchanged."""
    hallucinated = [
        {"group": "rdbms", "covered": True, "quote": "PostgreSQL 主从集群"},
        {"group": "jvm", "covered": True, "quote": "熟悉 Java 虚拟机底层原理"},
        {"group": "ai_app", "covered": True, "quote": "LangChain 智能客服"},
        # A regex-hit group is outside the miss set and must be ignored.
        {"group": "redis", "covered": False, "quote": ""},
    ]

    async def lying_side_effect(*args: object, **kwargs: object) -> dict:
        requested = _requested_ids(str(kwargs["prompt"]))
        return _payload_with_review(requested, hallucinated)

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = lying_side_effect
        report = await diagnose_resume(_review_resume(), resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    assert by_id[7].rating == "partial"
    assert "覆盖不足" in by_id[7].evidence
    assert "关系型数据库（MySQL）" in by_id[7].suggestion
    assert "JVM 原理与调优" in by_id[7].suggestion
    assert by_id[7].judgment_method == "objective"


@pytest.mark.asyncio
async def test_skill_review_omitted_by_model_falls_back_to_regex_verdict() -> None:
    """A weak/local model that ignores the auxiliary field degrades cleanly."""

    async def silent_side_effect(*args: object, **kwargs: object) -> dict:
        requested = _requested_ids(str(kwargs["prompt"]))
        return _payload_with_review(requested, None)

    with _patched_llm() as mock_complete:
        mock_complete.side_effect = silent_side_effect
        report = await diagnose_resume(_review_resume(), resume_id="r1", language="zh")

    by_id = {item.id: item for item in report.items}
    assert by_id[7].rating == "partial"
    assert "覆盖不足" in by_id[7].evidence
    assert by_id[7].judgment_method == "objective"
    assert "# 附加任务：技能分组语义复核" in mock_complete.await_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_skill_review_block_omitted_when_regex_stack_conforms() -> None:
    """A stack already at/over the coverage bar needs no semantic review."""
    conforming_skills = [
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
    with _patched_llm() as mock_complete:
        mock_complete.side_effect = _all_conform_side_effect
        report = await diagnose_resume(
            _review_resume(conforming_skills), resume_id="r1", language="zh"
        )

    by_id = {item.id: item for item in report.items}
    assert by_id[7].rating == "conform"
    assert by_id[7].judgment_method == "objective"
    assert "# 附加任务：技能分组语义复核" not in mock_complete.await_args.kwargs["prompt"]


def test_skill_review_block_escapes_braces_in_user_skill_text() -> None:
    """A skill entry containing braces must not break str.format rendering."""
    from app.services.diagnosis import _build_skill_review_block

    block = _build_skill_review_block(("jvm",), ["模板技能 {placeholder} 尾"])
    assert "模板技能 {placeholder} 尾" in block


def test_skill_review_quote_verification_rules() -> None:
    """Unit-level grounding rules for the rescue verifier."""
    from app.services.diagnosis import _verify_skill_group_review

    skills = ["MyBatis-Plus 持久层开发", "GC 调优与类加载机制"]
    # Case-insensitive verbatim substring rescues.
    assert _verify_skill_group_review(
        [{"group": "rdbms", "covered": True, "quote": "mybatis-plus"}],
        ("rdbms", "jvm"),
        skills,
    ) == frozenset({"rdbms"})
    # Interior whitespace differences are tolerated.
    assert _verify_skill_group_review(
        [{"group": "jvm", "covered": True, "quote": "GC  调优"}],
        ("rdbms", "jvm"),
        skills,
    ) == frozenset({"jvm"})
    # Paraphrase / non-substring quote rejected.
    assert _verify_skill_group_review(
        [{"group": "rdbms", "covered": True, "quote": "用过 MySQL 数据库"}],
        ("rdbms",),
        skills,
    ) == frozenset()
    # covered=false, missing quote, non-miss group, malformed payloads: no rescue.
    assert (
        _verify_skill_group_review(
            [
                {"group": "rdbms", "covered": False, "quote": "MyBatis-Plus"},
                {"group": "jvm", "covered": True, "quote": ""},
                {"group": "redis", "covered": True, "quote": "Redis"},
                "garbage",
            ],
            ("rdbms", "jvm"),
            skills,
        )
        == frozenset()
    )
    assert _verify_skill_group_review(None, ("rdbms",), skills) == frozenset()
