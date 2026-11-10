"""Request body limits must hold against chunked transfers and lying headers.

A guard that only inspects ``Content-Length`` is bypassable: chunked requests
carry no such header, and the header value is client-controlled anyway. These
tests stream oversized real bodies (``Transfer-Encoding: chunked``) and pin
the 413 outcome at the real ASGI boundary, plus the helper-level contract.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers.request_bodies import (
    MAX_JSON_REQUEST_BYTES,
    read_limited_body,
    read_limited_json_model,
)
from app.schemas.models import JobUploadRequest

pytestmark = pytest.mark.asyncio


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def _chunked(payload: bytes, chunk_size: int = 4096):
    """httpx encodes an async iterator as chunked transfer with no Content-Length."""
    for offset in range(0, len(payload), chunk_size):
        yield payload[offset : offset + chunk_size]


class _FakeRequest:
    """Minimal Request surface used by the bounded-body helpers."""

    def __init__(
        self, chunks: list[bytes], *, headers: dict[str, str] | None = None
    ) -> None:
        self._chunks = chunks
        self.method = "POST"
        self.url = SimpleNamespace(path="/synthetic")
        self.headers = headers or {}

    async def stream(self):  # type: ignore[no-untyped-def]
        for chunk in self._chunks:
            yield chunk


# --- helper-level contract -------------------------------------------------


async def test_read_limited_body_counts_real_bytes_without_any_header() -> None:
    request = _FakeRequest([b"a" * 4096, b"b" * 4096], headers={})
    body = await read_limited_body(request, 8192, "too large")
    assert body == b"a" * 4096 + b"b" * 4096


async def test_read_limited_body_rejects_when_real_stream_exceeds_cap() -> None:
    # A lying Content-Length claiming 10 bytes must not protect a 9 KB body.
    request = _FakeRequest(
        [b"x" * 4096, b"y" * 4096, b"z" * 1024],
        headers={"content-length": "10"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await read_limited_body(request, 8192, "Request body is too large.")
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "Request body is too large."


async def test_read_limited_json_model_validates_and_preserves_422_contract() -> None:
    valid = _FakeRequest([b'{"job_descriptions": ["Python engineer"]}'])
    model = await read_limited_json_model(
        valid, JobUploadRequest, MAX_JSON_REQUEST_BYTES, "too large"
    )
    assert model.job_descriptions == ["Python engineer"]

    invalid = _FakeRequest([b"not-json"])
    with pytest.raises(RequestValidationError):
        await read_limited_json_model(
            invalid, JobUploadRequest, MAX_JSON_REQUEST_BYTES, "too large"
        )


# --- endpoint-level: chunked oversized bodies ------------------------------


async def test_diagnose_chunked_oversized_body_returns_413() -> None:
    # ~143 KB of real bytes, streamed chunked with no Content-Length.
    payload = (
        b'{"job_description": "' + b"x" * (140 * 1024) + b'"}'
    )
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-matter/diagnose",
            content=_chunked(payload),
        )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


async def test_diagnose_accepts_normal_sized_chunked_body() -> None:
    # Chunked encoding itself must not be rejected; a small body passes the
    # guard and reaches the resume lookup (404 for an unknown resume).
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-matter/diagnose",
            content=_chunked(b"{}"),
        )
    assert response.status_code == 404


async def test_diagnose_malformed_json_remains_422() -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/does-not-matter/diagnose",
            content=b"not-json",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422


async def test_resume_patch_chunked_oversized_body_returns_413(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> None:
    row = await isolated_db.create_resume(
        content="Synthetic", processing_status="ready"
    )
    payload = b'{"summary": "' + b"x" * (MAX_JSON_REQUEST_BYTES + 1024) + b'"}'
    async with _client() as client:
        response = await client.patch(
            f"/api/v1/resumes/{row['resume_id']}",
            content=_chunked(payload),
        )
    assert response.status_code == 413
    # The oversized write never reached the database.
    stored = await isolated_db.get_resume(row["resume_id"])
    assert stored is not None and stored["content"] == "Synthetic"


async def test_jobs_upload_chunked_oversized_body_returns_413(
    isolated_db: Any,
) -> None:
    payload = (
        b'{"job_descriptions": ["' + b"x" * (MAX_JSON_REQUEST_BYTES + 1024) + b'"]}'
    )
    async with _client() as client:
        response = await client.post(
            "/api/v1/jobs/upload", content=_chunked(payload)
        )
    assert response.status_code == 413
    assert (await isolated_db.get_stats())["total_jobs"] == 0


async def test_jobs_upload_accepts_normal_chunked_body(isolated_db: Any) -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/jobs/upload",
            content=_chunked(b'{"job_descriptions": ["Python engineer"]}'),
        )
    assert response.status_code == 200, response.text
    assert (await isolated_db.get_stats())["total_jobs"] == 1


@pytest.mark.parametrize(
    "suffix,payload",
    [
        ("title", b'{"title": "x"}'),
        ("cover-letter", b'{"content": "dear team"}'),
        ("outreach-message", b'{"content": "hi team"}'),
    ],
)
async def test_content_patch_endpoints_enforce_body_cap(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    suffix: str,
    payload: bytes,
) -> None:
    row = await isolated_db.create_resume(
        content="Synthetic",
        processed_data=sample_resume,
        processing_status="ready",
    )
    oversized = b'{"content": "' + b"x" * (MAX_JSON_REQUEST_BYTES + 1024) + b'"}'
    async with _client() as client:
        blocked = await client.patch(
            f"/api/v1/resumes/{row['resume_id']}/{suffix}",
            content=_chunked(oversized),
        )
        # A normal-sized chunked request on the same route still works (or
        # reaches the documented 404/200 path rather than 413).
        allowed = await client.patch(
            f"/api/v1/resumes/{row['resume_id']}/{suffix}",
            content=_chunked(payload),
        )
    assert blocked.status_code == 413
    assert allowed.status_code == 200, allowed.text
