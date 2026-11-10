"""End-to-end tests for POST /resumes/{id}/diagnose with the LLM mocked (V4)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.diagnosis_checks import run_objective_checks
from app.services.diagnosis_competency import (
    expand_rules,
    parse_competency_models,
    resolve_competency_model,
)
from app.services.diagnosis_rules import get_rules

JD_GATED_IDS = {17}
COMPETENCE_IDS = {18, 19, 20, 21, 22}
EXPECTED_DIMENSION_KEYS = {
    "appearance",
    "content",
    "stability",
    "growth",
    "compliance",
    "fit",
    "competence",
}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _resolve_title(resume_data: dict, target_title: str | None) -> str | None:
    if target_title is not None:
        return target_title.strip() or None
    info = resume_data.get("personalInfo") or {}
    raw_title = info.get("title")
    return raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else None


def _llm_payload(
    resume_data: dict,
    *,
    with_jd: bool,
    target_title: str | None = None,
    model_key: str | None = None,
) -> dict:
    """Build a conform payload for exactly the ids the service will judge."""
    base = get_rules()
    title = _resolve_title(resume_data, target_title)
    # Mirror the service's mode contract: JD mode suppresses title
    # auto-matching unless an explicit (real) model key was supplied — that
    # combination is rejected with 400 before the LLM is ever called.
    effective_key = model_key
    if with_jd and not model_key:
        effective_key = "none"
    model = resolve_competency_model(
        parse_competency_models(base.competency_models), title, effective_key
    )
    rules = expand_rules(base, model)
    excluded = set(run_objective_checks(resume_data)[0])
    if not with_jd:
        excluded |= JD_GATED_IDS
    if model is None:
        # JD mode suppresses the model; model mode has no JD — the two
        # enhanced gates never run inside one request.
        excluded |= COMPETENCE_IDS
    ids = sorted(item_id for item_id in rules.items if item_id not in excluded)
    return {
        "items": [
            {"id": item_id, "rating": "conform", "evidence": f"e-{item_id}", "suggestion": ""}
            for item_id in ids
        ]
    }


def _llm_patches(payload: dict):
    return (
        patch(
            "app.services.diagnosis.complete_json",
            new_callable=AsyncMock,
            return_value=payload,
        ),
        patch("app.services.diagnosis.get_llm_config", return_value=object()),
        patch("app.services.diagnosis.get_model_name", return_value="openai/test"),
        patch("app.services.diagnosis.get_safe_max_tokens", return_value=12000),
    )


@pytest.mark.asyncio
async def test_diagnose_endpoint_returns_full_checklist(isolated_db: object) -> None:
    processed_data = {
        "personalInfo": {
            "name": "王浩",
            "gender": "男",
            "phone": "13812345678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "上海",
        },
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    resume_id = created["resume_id"]
    payload = _llm_payload(processed_data, with_jd=False)

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(f"/api/v1/resumes/{resume_id}/diagnose", json={})

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    assert report["spec_version"] == "V4"
    # Always 22 items / 7 dimensions: competence items are base rows filled in
    # place by the matched P4 model, never synthetic appended items.
    assert len(report["items"]) == 22
    assert {d["key"] for d in report["dimensions"]} == EXPECTED_DIMENSION_KEYS
    assert [redline["id"] for redline in report["redlines"]] == [16]
    # Score-era fields are gone; counts are the only aggregate.
    assert "rate" not in report
    assert "band" not in report
    assert {"conform", "partial", "nonconform", "na", "effective"} <= set(report["counts"])
    by_id = {item["id"]: item for item in report["items"]}
    # Item 4 (required basic info) is objectively satisfied; item 8 (work three
    # elements) is na without work experience.
    assert by_id[4]["rating"] == "conform"
    assert by_id[8]["rating"] == "na"
    # No JD -> only item 17 is na; the JD gate does not touch competence.
    assert by_id[17]["rating"] == "na"
    # Default target title comes from 求职意向 and P4 is auto-matched, so V4
    # judges the competence rows 18–22 even without a JD.
    assert report["target_title"] == "Java 开发工程师"
    assert report["competency_model"]["key"] == "java-p4"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id]["dimension"] == "competence"
        assert by_id[item_id]["rating"] == "conform"
    assert all(item["id"] < 1000 for item in report["items"])

    # Confidentiality: only the public topic label is serialized, never the
    # criterion/QC standard, on both items and red lines.
    assert all("criterion" not in item for item in report["items"])
    assert all("qc" not in item for item in report["items"])
    assert all(item["topic"] for item in report["items"])
    assert all("criterion" not in redline for redline in report["redlines"])


@pytest.mark.asyncio
async def test_diagnose_endpoint_grounds_judgement_in_stored_original_markdown(
    isolated_db: object,
) -> None:
    processed_data = {
        "personalInfo": {
            "name": "王浩",
            "gender": "男",
            "phone": "13812345678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "上海",
        },
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    original_md = "# 王浩\n\n独特原文锚点：负责支付核心链路的幂等改造。\n"
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content=original_md,
        content_type="md",
        processed_data=processed_data,
        original_markdown=original_md,
    )
    captured: dict = {}

    async def _capture(*args: object, **kwargs: object) -> dict:
        captured["prompt"] = kwargs["prompt"]
        return _llm_payload(processed_data, with_jd=False)

    async with _client() as client:
        with patch(
            "app.services.diagnosis.complete_json", new_callable=AsyncMock, side_effect=_capture
        ), patch("app.services.diagnosis.get_llm_config", return_value=object()), patch(
            "app.services.diagnosis.get_model_name", return_value="openai/test"
        ), patch(
            "app.services.diagnosis.get_safe_max_tokens", return_value=12000
        ):
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose", json={}
            )

    assert response.status_code == 200
    prompt = captured["prompt"]
    assert "用户原始简历" in prompt
    assert "独特原文锚点：负责支付核心链路的幂等改造" in prompt


@pytest.mark.asyncio
async def test_diagnose_endpoint_jd_suppresses_title_model_match(isolated_db: object) -> None:
    # Mode contract: a JD activates JD mode and suppresses the title-based
    # model match, so item 17 is judged while the competence rows 18–22 stay
    # na even though the title would otherwise auto-match a Java level model.
    processed_data = {
        "personalInfo": {
            "name": "王浩",
            "gender": "男",
            "phone": "13812345678",
            "email": "wang@example.com",
            "title": "Java 开发工程师",
            "location": "上海",
        },
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    payload = _llm_payload(processed_data, with_jd=True)

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={"job_description": "Java 工程师，要求 Spring Cloud、K8s"},
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    assert report["competency_model"] is None
    by_id = {item["id"]: item for item in report["items"]}
    for item_id in JD_GATED_IDS:
        assert by_id[item_id]["rating"] == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id]["rating"] == "na"


@pytest.mark.asyncio
async def test_diagnose_endpoint_honors_explicit_target_title(isolated_db: object) -> None:
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678", "title": "Java/大数据/前端"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    payload = _llm_payload(processed_data, with_jd=True, target_title="大数据开发工程师")

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={
                    "target_title": "大数据开发工程师",
                    "job_description": "大数据平台开发，要求 Spark、Flink",
                },
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    assert report["target_title"] == "大数据开发工程师"
    # A non-Java title matches no shipped model: checklist size is unchanged;
    # item 17 is judged with the JD while competence rows 18–22 come back na.
    assert report["competency_model"] is None
    assert len(report["items"]) == 22
    by_id = {item["id"]: item for item in report["items"]}
    assert by_id[17]["rating"] == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id]["rating"] == "na"


@pytest.mark.asyncio
async def test_diagnose_endpoint_honors_explicit_competency_model_key(
    isolated_db: object,
) -> None:
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678", "title": "大数据开发工程师"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    payload = _llm_payload(
        processed_data,
        with_jd=False,
        target_title="大数据开发工程师",
        model_key="java-p7",
    )

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={
                    "target_title": "大数据开发工程师",
                    "competency_model_key": "java-p7",
                },
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    # Explicit user confirmation overrides the (missing) title match.
    assert report["competency_model"]["key"] == "java-p7"
    assert len(report["items"]) == 22
    by_id = {item["id"]: item for item in report["items"]}
    assert all(by_id[item_id]["rating"] == "conform" for item_id in COMPETENCE_IDS)


@pytest.mark.asyncio
async def test_diagnose_endpoint_400_when_model_and_jd_combined(isolated_db: object) -> None:
    # The triple overlap (base + competency model + JD) is not a supported
    # mode: the request is rejected with 400 before any LLM call happens.
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678", "title": "大数据开发工程师"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )

    with patch(
        "app.services.diagnosis.complete_json", new_callable=AsyncMock
    ) as complete_json:
        async with _client() as client:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={
                    "competency_model_key": "java-p7",
                    "job_description": "Java 架构师岗位",
                },
            )

    assert response.status_code == 400
    complete_json.assert_not_called()


@pytest.mark.asyncio
async def test_diagnose_endpoint_none_key_opts_out_of_auto_match(
    isolated_db: object,
) -> None:
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678", "title": "Java 开发工程师"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    payload = _llm_payload(
        processed_data,
        with_jd=True,
        target_title="Java 开发工程师",
        model_key="none",
    )

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={"competency_model_key": "none", "job_description": "Java 工程师岗位"},
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    # Explicit opt-out wins over the P4 title auto-match: item 17 judged with
    # the JD, competence rows na.
    assert report["competency_model"] is None
    assert len(report["items"]) == 22
    by_id = {item["id"]: item for item in report["items"]}
    assert by_id[17]["rating"] == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id]["rating"] == "na"


@pytest.mark.asyncio
async def test_diagnose_endpoint_400_for_unknown_competency_model_key(
    isolated_db: object,
) -> None:
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678", "title": "Java 开发工程师"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{created['resume_id']}/diagnose",
            json={"competency_model_key": "java-p99"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_diagnose_endpoint_404_for_unknown_resume(isolated_db: object) -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-exist/diagnose", json={}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_diagnose_endpoint_jd_without_title_judges_item_17(isolated_db: object) -> None:
    processed_data = {
        "personalInfo": {"name": "王浩", "phone": "13812345678"},
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    payload = _llm_payload(processed_data, with_jd=True)

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{created['resume_id']}/diagnose",
                json={"job_description": "Java 架构师，要求 Spring Cloud"},
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    by_id = {item["id"]: item for item in report["items"]}
    # V4 gates 17 on the JD and 18–22 on the intention/model: 17 is judged
    # without a title, 18–22 need a resolved model.
    assert by_id[17]["rating"] == "conform"
    for item_id in COMPETENCE_IDS:
        assert by_id[item_id]["rating"] == "na"


@pytest.mark.asyncio
async def test_competency_catalog_lists_shipped_models(isolated_db: object) -> None:
    async with _client() as client:
        response = await client.get("/api/v1/diagnosis/competency-models")

    assert response.status_code == 200
    catalog = response.json()
    assert [model["key"] for model in catalog["models"]] == [
        "java-p3",
        "java-p4",
        "java-p5",
        "java-p6",
        "java-p7",
        "java-p8",
    ]
    assert all(model["family"] == "Java" for model in catalog["models"])
    assert {model["level"] for model in catalog["models"]} == {
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
    }
    assert catalog["matched_key"] is None


@pytest.mark.asyncio
async def test_competency_catalog_auto_matches_title(isolated_db: object) -> None:
    async with _client() as client:
        matched = await client.get(
            "/api/v1/diagnosis/competency-models",
            params={"title": "Java 开发工程师"},
        )
        unmatched = await client.get(
            "/api/v1/diagnosis/competency-models",
            params={"title": "大数据开发工程师"},
        )

    assert matched.json()["matched_key"] == "java-p4"
    assert unmatched.json()["matched_key"] is None


@pytest.mark.asyncio
async def test_diagnose_endpoint_heals_custom_section_shape_before_checks(
    isolated_db: object,
) -> None:
    # Screenshot regression: a stringList custom section whose entries were
    # stored in ``items`` while ``strings`` stayed null rendered as a
    # title-only 「其它」 block, so item 1 failed with "有标题无内容". The
    # endpoint must judge the same read-healed form the UI actually renders;
    # healing happens on a copy, so the stored document stays untouched.
    processed_data = {
        "personalInfo": {
            "name": "张三",
            "gender": "男",
            "phone": "18991931111",
            "email": "zhangsan@example.com",
            "title": "高级 Java 开发工程师",
            # 期望城市 intentionally absent: item 4 must still conform (选填）.
        },
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {},
        "customSections": {
            "other": {
                "sectionType": "stringList",
                "strings": None,
                "items": [
                    {"id": 1, "title": "GitHub 开源项目：https://example.com/repo"},
                    {"id": 2, "title": "个人技术站点：https://example.com/blog"},
                ],
                "text": None,
            }
        },
        "sectionMeta": [
            {
                "id": "other",
                "key": "other",
                "displayName": "其它",
                "sectionType": "stringList",
                "isDefault": False,
                "isVisible": True,
                "order": 0,
            }
        ],
    }
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}", content_type="json", processed_data=processed_data
    )
    resume_id = created["resume_id"]
    payload = _llm_payload(processed_data, with_jd=False)

    patches = _llm_patches(payload)
    async with _client() as client:
        with patches[0], patches[1], patches[2], patches[3]:
            response = await client.post(
                f"/api/v1/resumes/{resume_id}/diagnose", json={}
            )

    assert response.status_code == 200
    body = response.json()
    report = body["data"] if "data" in body else body
    by_id = {item["id"]: item for item in report["items"]}
    assert by_id[1]["rating"] == "conform"
    assert by_id[4]["rating"] == "conform"

    stored = await isolated_db.get_resume(resume_id)  # type: ignore[attr-defined]
    stored_other = stored["processed_data"]["customSections"]["other"]
    assert stored_other["strings"] is None
    assert len(stored_other["items"]) == 2
