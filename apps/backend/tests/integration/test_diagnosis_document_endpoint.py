"""End-to-end test for POST /resumes/{id}/diagnose/document (Word export)."""

import io
import re
from urllib.parse import unquote

import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _report_payload() -> dict:
    return {
        "resume_id": "placeholder",
        "spec_version": "V4",
        "language": "zh",
        "target_title": "Java 开发工程师",
        "competency_model": None,
        "counts": {"conform": 1, "partial": 0, "nonconform": 0, "na": 0, "effective": 1},
        "redline_passed": True,
        "failed_redline_ids": [],
        "dimensions": [
            {
                "key": "content",
                "name": "内容质量",
                "counts": {"conform": 1, "partial": 0, "nonconform": 0, "na": 0, "effective": 1},
            }
        ],
        "redlines": [],
        "items": [
            {
                "id": 1,
                "dimension": "content",
                "dimension_name": "内容质量",
                "sub_dimension": "格式",
                "topic": "区块顺序",
                "severity": "normal",
                "judgment_method": "objective",
                "rating": "conform",
                "evidence": "顺序正确",
                "suggestion": "",
            }
        ],
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_diagnosis_document_returns_valid_docx(isolated_db: object) -> None:
    processed_data = {"personalInfo": {"name": "王浩"}}
    created = await isolated_db.create_resume(  # type: ignore[attr-defined]
        content="{}",
        content_type="json",
        processed_data=processed_data,
        title="后端开发简历",
    )
    payload = _report_payload()
    payload["resume_id"] = created["resume_id"]

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{created['resume_id']}/diagnose/document", json=payload
        )

    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment" in response.headers["content-disposition"]
    # 简历诊断报告-姓名-时间.docx (RFC 5987 UTF-8 filename, minute stamp).
    utf8_part = response.headers["content-disposition"].split("filename*=UTF-8''")[1]
    assert re.fullmatch(
        r"简历诊断报告-王浩-\d{8}-\d{4}\.docx", unquote(utf8_part)
    ), unquote(utf8_part)
    body = response.content
    assert body[:4] == b"PK\x03\x04"  # ZIP local file header = valid .docx container

    doc = Document(io.BytesIO(body))
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "简历诊断报告" in text
    assert "王浩" in text  # candidate name resolved from the stored resume
    # Checklist contract carried into the document: counts + target title,
    # never a score.
    assert "适用 1 项" in text
    assert "Java 开发工程师" in text
    assert "/100" not in text
    # Appendix shows the public topic label, never a criterion standard.
    table_text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert "区块顺序" in table_text
    assert "模块顺序固定" not in table_text


@pytest.mark.asyncio
async def test_diagnosis_document_404_unknown_resume(isolated_db: object) -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-exist/diagnose/document", json=_report_payload()
        )
    assert response.status_code == 404
