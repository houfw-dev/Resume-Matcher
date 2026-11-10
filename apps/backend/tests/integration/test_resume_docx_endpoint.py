"""Integration tests for GET /resumes/{id}/docx (canonical Word download)."""

import io
import json
import threading
from urllib.parse import unquote

import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import resumes
from app.services.resume_docx import DOCX_MEDIA_TYPE


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _processed_data() -> dict:
    return {
        "personalInfo": {
            "name": "王浩",
            "gender": "男",
            "age": "28岁",
            "workYears": "5年",
            "educationLevel": "硕士",
            "title": "后端开发工程师",
        },
        "summary": "多年后端开发经验",
        "workExperience": [
            {
                "years": "2021 - 至今",
                "company": "某公司",
                "department": "",
                "title": "高级工程师",
                "description": ["负责系统设计"],
                "descriptionStyles": ["bullet"],
            }
        ],
        "additional": {
            "technicalSkills": ["Python", "Go"],
            "certificationsTraining": ["PMP"],
            "awards": [],
        },
    }


@pytest.mark.asyncio
async def test_resume_docx_endpoint_returns_word_document(isolated_db: object) -> None:
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}",
        content_type="json",
        processed_data=_processed_data(),
        processing_status="ready",
        title="王浩的简历",
    )

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{created['resume_id']}/docx")

    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MEDIA_TYPE
    assert response.content[:4] == b"PK\x03\x04"

    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f'filename="resume-{created["resume_id"][:8]}.docx"' in disposition
    utf8_part = disposition.split("filename*=UTF-8''")[1]
    # 姓名-年龄-工作年限-学历-求职意向
    assert unquote(utf8_part) == "王浩-28岁-5年-硕士-后端开发工程师.docx"

    document = Document(io.BytesIO(response.content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "王浩" in text
    assert "工作经历" in text
    # Independent cert module, not folded into the skills list.
    assert "培训与证书" in text


@pytest.mark.asyncio
async def test_resume_docx_endpoint_honours_lang_query(isolated_db: object) -> None:
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}",
        content_type="json",
        processed_data=_processed_data(),
        processing_status="ready",
        title="resume",
    )

    async with _client() as client:
        response = await client.get(
            f"/api/v1/resumes/{created['resume_id']}/docx?lang=en-US"
        )

    assert response.status_code == 200
    document = Document(io.BytesIO(response.content))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Experience" in text
    assert "Training & Certifications" in text


@pytest.mark.asyncio
async def test_resume_docx_endpoint_404_unknown_resume(isolated_db: object) -> None:
    async with _client() as client:
        response = await client.get("/api/v1/resumes/does-not-exist/docx")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resume_docx_endpoint_409_while_not_ready(isolated_db: object) -> None:
    # A raw markdown upload whose parse never finished stays in a non-ready
    # state; the readiness gate must reject it before any DOCX work happens.
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="# 王浩\n后端工程师",
        content_type="md",
        processed_data=None,
        processing_status="processing",
    )

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{created['resume_id']}/docx")

    assert response.status_code == 409
    assert "still being processed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_resume_docx_endpoint_400_without_data(isolated_db: object) -> None:
    # Defensive branch: a record marked ready (so it passes the readiness gate)
    # but holding only non-JSON markdown has no structured ResumeData to build.
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="# 王浩\n后端工程师",
        content_type="md",
        processed_data=None,
        processing_status="ready",
    )

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{created['resume_id']}/docx")

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_resume_docx_endpoint_falls_back_to_json_content(isolated_db: object) -> None:
    # Builder-saved resumes have structured JSON in content even without
    # processed_data — the endpoint must use the same fallback as the PDF.
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content=json.dumps(_processed_data(), ensure_ascii=False),
        content_type="json",
        processed_data=None,
        processing_status="ready",
    )

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{created['resume_id']}/docx")

    assert response.status_code == 200
    assert response.content[:4] == b"PK\x03\x04"


@pytest.mark.asyncio
async def test_resume_docx_build_runs_off_event_loop_thread(
    isolated_db: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Synchronous python-docx generation must be offloaded via asyncio.to_thread
    # so it never blocks the event loop.
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}",
        content_type="json",
        processed_data=_processed_data(),
        processing_status="ready",
    )
    real_builder = resumes.build_resume_docx
    builder_thread: dict[str, int] = {}

    def recording_builder(*args: object, **kwargs: object) -> bytes:
        builder_thread["ident"] = threading.get_ident()
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(resumes, "build_resume_docx", recording_builder)
    loop_thread = threading.get_ident()

    async with _client() as client:
        response = await client.get(f"/api/v1/resumes/{created['resume_id']}/docx")

    assert response.status_code == 200
    assert response.content[:4] == b"PK\x03\x04"
    assert "ident" in builder_thread
    assert builder_thread["ident"] != loop_thread
