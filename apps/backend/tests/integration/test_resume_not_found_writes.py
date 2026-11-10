"""Concurrent-delete races on resume writes must surface as HTTP 404.

Every write endpoint performs an upfront ``get_resume()`` 404 check, but the
check-then-write window is not atomic: a delete landing in between makes
``db.update_resume`` raise ``ResumeNotFoundError``. These tests pin the
mapping to 404 (instead of an opaque 500) at the real ASGI boundary.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.database import ResumeNotFoundError
from app.main import app
from app.routers import resumes
from app.schemas.models import InterviewPrepData

pytestmark = pytest.mark.asyncio


def _client() -> AsyncClient:
    # raise_app_exceptions=False so the pre-fix behavior arrives as a real
    # 500 response rather than an exception escaping the transport.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


async def _ready_resume(
    isolated_db: Any, sample_resume: dict[str, Any]
) -> dict[str, Any]:
    return await isolated_db.create_resume(
        content="Synthetic resume",
        content_type="json",
        processed_data=sample_resume,
        processing_status="ready",
    )


def _raise_not_found_on_update(
    monkeypatch: pytest.MonkeyPatch, isolated_db: Any, resume_id: str
) -> None:
    monkeypatch.setattr(
        isolated_db,
        "update_resume",
        AsyncMock(side_effect=ResumeNotFoundError(resume_id)),
    )


SIMPLE_PATCHES = [
    ("title", {"title": "New Title"}),
    ("cover-letter", {"content": "Dear hiring manager..."}),
    ("outreach-message", {"content": "Hi, I saw your posting."}),
]


@pytest.mark.parametrize("suffix,payload", SIMPLE_PATCHES)
async def test_simple_patch_maps_concurrent_delete_to_404(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    payload: dict[str, str],
) -> None:
    row = await _ready_resume(isolated_db, sample_resume)
    _raise_not_found_on_update(monkeypatch, isolated_db, row["resume_id"])

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/resumes/{row['resume_id']}/{suffix}", json=payload
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resume not found"}


async def test_full_patch_maps_concurrent_delete_to_404(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = await _ready_resume(isolated_db, sample_resume)
    _raise_not_found_on_update(monkeypatch, isolated_db, row["resume_id"])

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/resumes/{row['resume_id']}", json=sample_resume
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resume not found"}


# The endpoint serializes via model_dump(), so the service mock must return a
# model instance rather than a plain dict.
INTERVIEW_PREP = InterviewPrepData(
    role_fit_analysis=["Strong backend background"],
    resume_questions=[],
    project_follow_ups=[],
    skill_gaps=[],
    talking_points=["Lead with the payments rewrite"],
)

GENERATE_CASES = [
    ("cover-letter/generate", "generate_cover_letter", "Dear hiring team"),
    ("generate-cover-letter", "generate_cover_letter", "Dear hiring team"),
    ("generate-outreach", "generate_outreach_message", "Hi, I saw your posting."),
    ("generate-interview-prep", "generate_interview_prep", INTERVIEW_PREP),
]


@pytest.mark.parametrize("path_suffix,service_name,generated", GENERATE_CASES)
async def test_generate_endpoint_maps_concurrent_delete_to_404(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    service_name: str,
    generated: Any,
) -> None:
    row = await _ready_resume(isolated_db, sample_resume)
    # The generation succeeds; only the persistence write loses the row.
    monkeypatch.setattr(
        resumes, service_name, AsyncMock(return_value=generated)
    )
    _raise_not_found_on_update(monkeypatch, isolated_db, row["resume_id"])

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{row['resume_id']}/{path_suffix}", json={}
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Resume not found"}


async def test_update_resume_or_404_helper_passes_through_and_maps(
    isolated_db: Any, sample_resume: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    row = await _ready_resume(isolated_db, sample_resume)

    # Success path returns the refreshed row from the real database.
    updated = await resumes._update_resume_or_404(
        row["resume_id"], {"title": "Renamed"}
    )
    assert updated["title"] == "Renamed"

    # A vanished row becomes an HTTP 404, not the facade's ValueError.
    monkeypatch.setattr(
        isolated_db,
        "update_resume",
        AsyncMock(side_effect=ResumeNotFoundError("gone-id")),
    )
    with pytest.raises(HTTPException) as exc_info:
        await resumes._update_resume_or_404("gone-id", {"title": "Never stored"})
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Resume not found"
