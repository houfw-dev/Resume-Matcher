"""Integration tests for the measured rendered-layout fields on /diagnose.

Covers the request contract added for template-aware diagnosis:

* a usable snapshot makes item 2 a measured, objective verdict (the LLM is
  still mocked for the semantic items, but item 2 never reaches it);
* bodies over 128 KB are rejected with 413 before any resume lookup;
* malformed snapshots are rejected with 422 by the request schema;
* the legacy empty body ``{}`` keeps working unchanged.
"""

import re
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.diagnosis import RenderedLayoutIn, TemplateSettingsIn
from app.services.diagnosis_checks import run_objective_checks
from app.services.diagnosis_competency import (
    expand_rules,
    parse_competency_models,
    resolve_competency_model,
)
from app.services.diagnosis_rules import get_rules


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


PROCESSED_DATA: dict = {
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
    "additional": {"technicalSkills": ["Java", "Spring Boot", "MySQL"]},
}


def _requested_ids(prompt: str) -> set[int]:
    lines = prompt.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("# 需要你评估的检查项"):
            return {int(token) for token in re.findall(r"\d+", lines[index + 1])}
    raise AssertionError("assigned-items section not found in prompt")


@pytest.mark.asyncio
async def test_diagnose_with_measured_layout_marks_page_count_objective(
    isolated_db: object,
) -> None:
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=PROCESSED_DATA
    )
    resume_id = created["resume_id"]

    settings = TemplateSettingsIn()
    layout = RenderedLayoutIn(template="swiss-single", page_size="A4", page_count=4)
    # Objective ids under the measured run determine what the LLM must answer.
    objective_ids = set(
        run_objective_checks(
            PROCESSED_DATA, rendered_layout=layout, template_settings=settings
        )[0]
    )
    base = get_rules()
    model = resolve_competency_model(
        parse_competency_models(base.competency_models), "Java 开发工程师", None
    )
    rules = expand_rules(base, model)

    async def answer(*args: object, **kwargs: object) -> dict:
        asked = _requested_ids(str(kwargs["prompt"]))
        # Engine-owned items are never delegated to the LLM under measurement.
        assert 1 not in asked and 2 not in asked
        return {
            "items": [
                {"id": item_id, "rating": "conform", "evidence": "", "suggestion": ""}
                for item_id in sorted(asked)
            ]
        }

    body = {
        "template_settings": settings.model_dump(),
        "rendered_layout": layout.model_dump(),
    }
    async with _client() as client:
        with patch(
            "app.services.diagnosis.complete_json", new_callable=AsyncMock, side_effect=answer
        ), patch(
            "app.services.diagnosis.get_llm_config", return_value=object()
        ), patch(
            "app.services.diagnosis.get_model_name", return_value="openai/test"
        ), patch(
            "app.services.diagnosis.get_safe_max_tokens", return_value=12000
        ):
            response = await client.post(
                f"/api/v1/resumes/{resume_id}/diagnose", json=body
            )

    assert response.status_code == 200
    payload = response.json()
    report = payload["data"] if "data" in payload else payload
    assert 2 in objective_ids
    item2 = next(item for item in report["items"] if item["id"] == 2)
    assert item2["judgment_method"] == "objective"
    assert item2["rating"] == "nonconform"
    assert "实际渲染" in item2["evidence"]
    assert "估算" not in item2["evidence"]


@pytest.mark.asyncio
async def test_diagnose_oversized_body_returns_413(isolated_db: object) -> None:
    # job_description is a free string; inflate it past the 128 KB request cap.
    body = {"job_description": "x" * (140 * 1024)}
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-matter/diagnose", json=body
        )
    assert response.status_code == 413
    # Generic client message, no internals leaked.
    assert "too large" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_diagnose_invalid_snapshot_returns_422(isolated_db: object) -> None:
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=PROCESSED_DATA
    )
    resume_id = created["resume_id"]
    body = {
        "template_settings": {"template": "swiss-single"},
        "rendered_layout": {
            "template": "swiss-single",
            "page_size": "A4",
            "page_count": 99,  # outside 1-12
        },
    }
    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/diagnose", json=body
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_diagnose_empty_body_still_accepted(isolated_db: object) -> None:
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=PROCESSED_DATA
    )
    resume_id = created["resume_id"]
    base = get_rules()
    model = resolve_competency_model(
        parse_competency_models(base.competency_models), "Java 开发工程师", None
    )
    rules = expand_rules(base, model)
    excluded = set(run_objective_checks(PROCESSED_DATA)[0])
    payload = {
        "items": [
            {"id": item_id, "rating": "conform", "evidence": "", "suggestion": ""}
            # Item 17 (JD fit) is not judged: the request carries no JD.
            for item_id in sorted(set(rules.items) - excluded - {17})
        ]
    }
    async with _client() as client:
        with patch(
            "app.services.diagnosis.complete_json",
            new_callable=AsyncMock,
            return_value=payload,
        ), patch(
            "app.services.diagnosis.get_llm_config", return_value=object()
        ), patch(
            "app.services.diagnosis.get_model_name", return_value="openai/test"
        ), patch(
            "app.services.diagnosis.get_safe_max_tokens", return_value=12000
        ):
            response = await client.post(
                f"/api/v1/resumes/{resume_id}/diagnose", json={}
            )
    assert response.status_code == 200
