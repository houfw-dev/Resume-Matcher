"""Service tests: the measured rendered-layout block reaches the LLM prompt.

The browser-measured snapshot is only useful if (a) the deterministic items
1/2 judge its measurements, (b) the LLM judge receives the per-page mirror as
appearance ground truth, and (c) unusable/oversized snapshots degrade
gracefully. The LLM transport is mocked; these tests inspect the composed
prompt and the merged objective verdicts.
"""

import re
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.diagnosis import (
    LayoutPageMirrorIn,
    RenderedLayoutIn,
    TemplateSettingsIn,
)
from app.services.diagnosis import diagnose_resume

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
            "description": ["负责交易系统开发与维护"],
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
    "additional": {"technicalSkills": ["Java", "Spring Boot", "MySQL"]},
}

BLOCK_HEADER = "# 所选模板的实际渲染结果"
TRUNCATION_NOTICE = "[Content truncated for prompt length."


def _layout(page_count: int = 4, *, mirror_text: str = "") -> RenderedLayoutIn:
    return RenderedLayoutIn(
        template="swiss-single",
        page_size="A4",
        page_count=page_count,
        page_mirror=[LayoutPageMirrorIn(page=1, text=_mirror_page(mirror_text))]
        if mirror_text
        else [],
    )


def _mirror_page(text: str, page: int = 1, total: int = 4) -> str:
    """Mirror pages carry their own page heading (as the frontend builds)."""
    return f"===== 第 {page} 页（共 {total} 页） =====\n{text}"


def _requested_ids(prompt: str) -> set[int]:
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# 需要你评估的检查项"):
            return {int(token) for token in re.findall(r"\d+", lines[index + 1])}
    raise AssertionError("assigned-items section not found in prompt")


@contextmanager
def _patched_llm():
    config = object()

    def side_effect(*args: object, **kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        return {"items": [{"id": item_id, "rating": "conform", "evidence": "", "suggestion": ""}
                          for item_id in sorted(_requested_ids(prompt))]}

    with patch(
        "app.services.diagnosis.complete_json", new_callable=AsyncMock
    ) as mock_complete, patch(
        "app.services.diagnosis.get_llm_config", return_value=config
    ), patch(
        "app.services.diagnosis.get_model_name", return_value="openai/test-model"
    ), patch(
        "app.services.diagnosis.get_safe_max_tokens", return_value=12000
    ):
        mock_complete.side_effect = side_effect
        yield mock_complete


@pytest.mark.asyncio
async def test_usable_snapshot_adds_rendered_block_and_measured_verdicts() -> None:
    layout = _layout(
        page_count=4,
        mirror_text="独特镜像文本-甲负责交易系统开发（实测 8 行）",
    )
    with _patched_llm() as mock_complete:
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            template_settings=TemplateSettingsIn(),
            rendered_layout=layout,
        )
        prompt = str(mock_complete.call_args.kwargs["prompt"])

    # Deterministic item 2 judged the measured four pages, no LLM involved.
    item2 = next(item for item in report.items if item.id == 2)
    assert item2.judgment_method == "objective"
    assert item2.rating == "nonconform"
    assert "实际渲染" in item2.evidence

    # The LLM prompt carries the rendered block + mirror + measurements.
    assert BLOCK_HEADER in prompt
    assert "独特镜像文本-甲" in prompt
    assert '"page_count": 4' in prompt
    # Items 1/2 are owned by the engine; the LLM must never re-judge them.
    requested = _requested_ids(prompt)
    assert 1 not in requested and 2 not in requested


@pytest.mark.asyncio
async def test_no_snapshot_means_no_rendered_block() -> None:
    with _patched_llm() as mock_complete:
        await diagnose_resume(SAMPLE_RESUME, resume_id="r1", language="zh")
        prompt = str(mock_complete.call_args.kwargs["prompt"])
    assert BLOCK_HEADER not in prompt


@pytest.mark.asyncio
async def test_template_mismatch_snapshot_dropped_from_prompt() -> None:
    layout = RenderedLayoutIn(template="vivid", page_size="A4", page_count=9)
    with _patched_llm() as mock_complete:
        report = await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            template_settings=TemplateSettingsIn(),  # swiss-single
            rendered_layout=layout,
        )
        prompt = str(mock_complete.call_args.kwargs["prompt"])

    assert BLOCK_HEADER not in prompt
    item2 = next(item for item in report.items if item.id == 2)
    assert "实际渲染" not in item2.evidence


@pytest.mark.asyncio
async def test_rendered_block_capped_with_explicit_truncation_notice() -> None:
    # Per-page mirror text is bounded to 6 KB; twelve near-limit pages (~70 KB)
    # force the whole-block cap, so facts survive while the mirror is cut.
    layout = RenderedLayoutIn(
        template="swiss-single",
        page_size="A4",
        page_count=12,
        page_mirror=[
            LayoutPageMirrorIn(page=page, text=_mirror_page("镜" * 5_800, page, 12))
            for page in range(1, 13)
        ],
    )
    with _patched_llm() as mock_complete:
        await diagnose_resume(
            SAMPLE_RESUME,
            resume_id="r1",
            language="zh",
            template_settings=TemplateSettingsIn(),
            rendered_layout=layout,
        )
        prompt = str(mock_complete.call_args.kwargs["prompt"])

    block_start = prompt.index(BLOCK_HEADER)
    block_end = prompt.index("# 简历结构化数据", block_start)
    block = prompt[block_start:block_end]
    assert TRUNCATION_NOTICE in block
    # Facts survive (they precede the mirror and are bounded independently).
    assert '"page_count": 12' in block
    assert len(block) < 12_500
