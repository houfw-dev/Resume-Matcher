"""Integration tests for the fine-tune preview/confirm endpoints.

Routers, schemas, preservation finalizer and SQLite (isolated per-test) are
real; the only mocked boundary is ``app.services.fine_tune.complete_json``,
so no LLM/network traffic happens.
"""

import asyncio
import copy
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.main import app
from app.models import FineTunePreview, Resume
from app.database import Database
from app.preview import hash_resume_data
from app.routers.fine_tune import fine_tune_confirm
from app.schemas.fine_tune import FineTuneConfirmRequest
from app.schemas.models import ResumeData
from app.services.fine_tune import _canonical_source
from tests.integration.test_storage_busy_writes import fast_busy_database  # noqa: F401

pytestmark = pytest.mark.asyncio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _canonical(data: dict[str, Any]) -> dict[str, Any]:
    return ResumeData.model_validate(data).model_dump()


EVIDENCE_MARKER = "Backend engineer leading 800 engineers across teams."

ORIGINAL_MARKDOWN = (
    "# Jane Doe\nSenior Backend Engineer\n\n"
    "Summary\n"
    f"{EVIDENCE_MARKER}\n"
    "- Mentored 3 junior developers\n"
)


async def _seed_resume(
    isolated_db: Any,
    data: dict[str, Any] | None,
    *,
    original_markdown: str | None = ORIGINAL_MARKDOWN,
    title: str = "Jane Doe Resume",
) -> str:
    if data is not None:
        content = json.dumps(data, ensure_ascii=False)
    else:
        content = "# unparsed resume\n"
    row = await isolated_db.create_resume(
        content=content,
        content_type="json" if data is not None else "md",
        filename="resume.pdf",
        is_master=True,
        processed_data=data,
        processing_status="ready" if data is not None else "failed",
        original_markdown=original_markdown,
        title=title,
    )
    return row["resume_id"]


def _grounded_candidate(source: dict[str, Any]) -> dict[str, Any]:
    """A model output mixing one evidence-grounded restore and two rogue rows."""
    candidate = copy.deepcopy(source)
    candidate["summary"] = EVIDENCE_MARKER
    first_job = candidate["workExperience"][0]
    first_job["description"] = list(first_job["description"]) + [
        "Led a program covering 999 new partners",
        "Professional skydiving coach on weekends.",
    ]
    first_job["descriptionStyles"] = list(first_job.get("descriptionStyles", [])) + [
        "bullet",
        "bullet",
    ]
    return candidate


async def _fine_tune_rows(isolated_db: Any) -> list[FineTunePreview]:
    async with isolated_db._session() as session:
        return list(
            (await session.execute(select(FineTunePreview))).scalars().all()
        )


@pytest.fixture
def patch_complete_json():
    """Patch the LLM boundary; each test sets the return value via the mock."""
    mock = AsyncMock()
    with patch("app.services.fine_tune.complete_json", new=mock):
        yield mock


# --- preview ---------------------------------------------------------------


async def test_preview_grounds_restores_and_rejects_fabrication(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = _grounded_candidate(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "all"}, "instruction": "emphasize impact"},
        )

    assert response.status_code == 200
    body = response.json()
    improved = body["improved_data"]

    # Grounded restore from the original upload text survives... summary lines
    # render as list points, so hygiene strips the trailing period.
    assert improved["summary"] == EVIDENCE_MARKER[:-1]
    # ...personal info is always frozen...
    assert improved["personalInfo"] == source["personalInfo"]
    # ...fabricated metric is stripped, ungrounded qualitative row survives as
    # a review claim and is surfaced as a GROUNDING_REVIEW warning.
    joined = json.dumps(improved)
    assert "999" not in joined
    assert "skydiving" in joined
    assert any(
        "GROUNDING_REVIEW" in warning
        and "workExperience[0].description" in warning
        for warning in body["warnings"]
    )
    assert body["diff_summary"] is not None
    assert isinstance(body["detailed_changes"], list)
    assert body["scope"] == {"kind": "all", "targets": []}

    rows = await _fine_tune_rows(isolated_db)
    assert len(rows) == 1
    assert rows[0].source_id == resume_id
    assert rows[0].prompt_id == "fine_tune_v1"


async def test_identical_preview_is_registered_once(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = _grounded_candidate(source)

    async with _client() as client:
        first = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "all"}},
        )
        second = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "all"}},
        )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["preview_id"] == second.json()["preview_id"]
    assert len(await _fine_tune_rows(isolated_db)) == 1


async def test_preview_without_structured_data_returns_400(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    resume_id = await _seed_resume(isolated_db, None)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "all"}},
        )

    assert response.status_code == 400
    patch_complete_json.assert_not_called()


async def test_preview_rejects_invalid_scope_and_oversized_instruction(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = copy.deepcopy(source)

    async with _client() as client:
        bad_target = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["personalInfo"]}},
        )
        bad_instruction = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "all"}, "instruction": "x" * 2001},
        )

    assert bad_target.status_code == 422
    assert bad_instruction.status_code == 422
    patch_complete_json.assert_not_called()


async def test_preview_reports_ignored_out_of_range_target(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = copy.deepcopy(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["work_9"]}},
        )

    assert response.status_code == 200
    assert "Ignored out-of-range target: work_9" in response.json()["warnings"]
    # Nothing matched the scope, so the result must equal the canonical
    # (read-time-governed) source exactly.
    expected = _canonical_source({"processed_data": source})
    assert response.json()["improved_data"] == expected


async def test_preview_unknown_resume_returns_404(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    async with _client() as client:
        response = await client.post(
            "/api/v1/resumes/missing/fine-tune/preview",
            json={"scope": {"kind": "all"}},
        )

    assert response.status_code == 404


# --- confirm: overwrite / copy ---------------------------------------------


async def _preview(
    client: AsyncClient,
    resume_id: str,
    candidate: dict[str, Any],
    mock: AsyncMock,
    *,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mock.return_value = candidate
    response = await client.post(
        f"/api/v1/resumes/{resume_id}/fine-tune/preview",
        json={"scope": scope or {"kind": "all"}},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_confirm_overwrite_updates_resume_and_keeps_original_text(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    candidate = _grounded_candidate(source)

    async with _client() as client:
        preview = await _preview(client, resume_id, candidate, patch_complete_json)
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "overwrite",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "resume_id": resume_id,
        "mode": "overwrite",
        "title": "Jane Doe Resume",
    }

    stored = await isolated_db.get_resume(resume_id)
    assert stored is not None
    assert stored["processed_data"]["summary"] == EVIDENCE_MARKER[:-1]
    assert json.loads(stored["content"])["summary"] == EVIDENCE_MARKER[:-1]
    assert stored["content_type"] == "json"
    assert stored["processing_status"] == "ready"
    assert stored["original_markdown"] == ORIGINAL_MARKDOWN
    assert stored["is_master"] is True
    assert stored["title"] == "Jane Doe Resume"


async def test_confirm_copy_creates_child_with_inherited_evidence(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)
    candidate = _grounded_candidate(source)

    async with _client() as client:
        preview = await _preview(client, resume_id, candidate, patch_complete_json)
        default_title = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
            },
        )

    assert default_title.status_code == 200
    copy_body = default_title.json()
    assert copy_body["mode"] == "copy"
    assert copy_body["title"] == "Jane Doe Resume (fine-tuned)"
    child_id = copy_body["resume_id"]
    assert child_id != resume_id

    child = await isolated_db.get_resume(child_id)
    assert child is not None
    assert child["parent_id"] == resume_id
    assert child["is_master"] is False
    assert child["original_markdown"] == ORIGINAL_MARKDOWN
    assert child["processed_data"]["summary"] == EVIDENCE_MARKER[:-1]
    assert child["filename"] == "finetuned_resume.pdf"

    # The source resume is untouched.
    parent = await isolated_db.get_resume(resume_id)
    assert parent is not None
    assert parent["processed_data"]["summary"] == source["summary"]


async def test_confirm_copy_accepts_custom_title(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
                "title": "Polished version",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Polished version"
    child = await isolated_db.get_resume(body["resume_id"])
    assert child is not None and child["title"] == "Polished version"


# --- confirm: guards, leases and replay ------------------------------------


async def test_confirm_after_resume_changed_returns_409(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        await isolated_db.update_resume(
            resume_id, {"content": json.dumps(source) + "\n// edited after preview"}
        )
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "overwrite",
            },
        )

    assert response.status_code == 409


async def test_confirm_with_unknown_preview_returns_400(
    isolated_db: Any,
    sample_resume: dict[str, Any],
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": "no-such-preview",
                "improved_data": source,
                "mode": "overwrite",
            },
        )

    assert response.status_code == 400


async def test_confirm_contention_returns_503_then_request_reaches_validation(
    fast_busy_database: Database,
    sample_resume: dict[str, Any],
) -> None:
    # The claim reservation is a write: real SQLite contention must reach the
    # client as the retryable 503 contract, not the endpoint's generic 500.
    database = fast_busy_database
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(database, source)
    body = {
        "preview_id": "no-such-preview",
        "improved_data": source,
        "mode": "overwrite",
    }

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        async with database._session() as writer:
            await writer.execute(text("BEGIN IMMEDIATE"))
            blocked = await client.post(
                f"/api/v1/resumes/{resume_id}/fine-tune/confirm", json=body
            )
        assert blocked.status_code == 503, blocked.text
        assert blocked.headers["retry-after"] == "1"
        assert blocked.json() == {
            "detail": "Database is busy. Please retry shortly."
        }
        # No lease row could be created under the lock, so nothing is held.
        assert len(await _fine_tune_rows(database)) == 0

        # Lock released: the unchanged request now reaches normal preview
        # validation (400 for the unknown preview), proving 503 was contention.
        retried = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm", json=body
        )

    assert retried.status_code == 400, retried.text


async def test_confirm_with_tampered_payload_returns_400(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        tampered = copy.deepcopy(preview["improved_data"])
        tampered["summary"] = "Totally different content than what was previewed."
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": tampered,
                "mode": "overwrite",
            },
        )

    assert response.status_code == 400
    stored = await isolated_db.get_resume(resume_id)
    assert stored is not None and stored["processed_data"]["summary"] == source["summary"]


async def test_confirm_with_active_lease_returns_409_retry_after(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        improved = preview["improved_data"]
        # Another confirmation holds an active (non-expired) lease.
        await isolated_db.claim_fine_tune_preview(
            preview_id=preview["preview_id"],
            source_id=resume_id,
            payload_hash=hash_resume_data(improved),
            lease_seconds=60,
        )
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": improved,
                "mode": "overwrite",
            },
        )

    assert response.status_code == 409
    assert response.headers.get("retry-after") == "1"
    stored = await isolated_db.get_resume(resume_id)
    assert stored is not None and stored["processed_data"]["summary"] == source["summary"]


async def test_failed_claim_release_keeps_primary_error_and_logs(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    """A failing lease release must not replace the endpoint's own error.

    Without the try/except guard, the release exception escapes the ``finally``
    and Starlette answers with a generic ``Internal Server Error`` instead of
    the endpoint's intended generic detail.
    """
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        body = {
            "preview_id": preview["preview_id"],
            "improved_data": preview["improved_data"],
            "mode": "overwrite",
        }
        with (
            patch.object(
                isolated_db,
                "complete_fine_tune_preview",
                AsyncMock(side_effect=RuntimeError("synthetic commit failure")),
            ),
            patch.object(
                isolated_db,
                "release_fine_tune_preview_claim",
                AsyncMock(side_effect=RuntimeError("synthetic release failure")),
            ) as release_mock,
            patch("app.routers.fine_tune.logger") as logger_mock,
        ):
            response = await client.post(
                f"/api/v1/resumes/{resume_id}/fine-tune/confirm", json=body
            )

    assert response.status_code == 500
    assert "Failed to apply fine-tuned resume. Please try again." in response.text
    assert "Internal Server Error" not in response.text
    release_mock.assert_awaited_once()
    logger_mock.exception.assert_called_once()


async def test_cancelled_confirm_still_releases_lease_under_shield(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    """Cancelling the request task while the lease release is in flight must
    not abort the release itself: ``asyncio.shield`` lets the inner DB write
    finish, otherwise the lease stays locked until its TTL expires."""
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )

    request = FineTuneConfirmRequest(
        preview_id=preview["preview_id"],
        improved_data=preview["improved_data"],
        mode="overwrite",
    )

    real_release = isolated_db.release_fine_tune_preview_claim
    release_started = asyncio.Event()
    release_gate = asyncio.Event()
    release_completed = asyncio.Event()

    async def gated_release(claim: Any) -> None:
        release_started.set()
        await release_gate.wait()
        await real_release(claim)
        release_completed.set()

    with (
        patch.object(
            isolated_db,
            "complete_fine_tune_preview",
            AsyncMock(side_effect=RuntimeError("synthetic commit failure")),
        ),
        patch.object(
            isolated_db,
            "release_fine_tune_preview_claim",
            AsyncMock(side_effect=gated_release),
        ),
    ):
        task = asyncio.create_task(fine_tune_confirm(resume_id, request))
        # Park the endpoint inside the finally-block release, then cancel it.
        await asyncio.wait_for(release_started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Unblock the shielded inner release and wait for its real DB write.
        release_gate.set()
        await asyncio.wait_for(release_completed.wait(), timeout=2)

    rows = await _fine_tune_rows(isolated_db)
    assert len(rows) == 1
    assert rows[0].claim_token is None


async def test_completed_confirm_is_idempotent(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        body = {
            "preview_id": preview["preview_id"],
            "improved_data": preview["improved_data"],
            "mode": "copy",
        }
        first = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm", json=body
        )
        second = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm", json=body
        )

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["resume_id"] == second.json()["resume_id"]
    assert second.json()["mode"] == "copy"

    async with isolated_db._session() as session:
        resume_count = await session.scalar(select(func.count()).select_from(Resume))
    assert resume_count == 2  # source + one copy, not a second copy


# --- cleanup ---------------------------------------------------------------


async def test_delete_resume_cleans_fine_tune_previews(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        preview = await _preview(
            client, resume_id, copy.deepcopy(source), patch_complete_json
        )
        confirmed = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
            },
        )
        child_id = confirmed.json()["resume_id"]

    # Deleting the confirmed copy strips cached content but keeps the marker...
    assert await isolated_db.delete_resume(child_id) is True
    rows = await _fine_tune_rows(isolated_db)
    assert len(rows) == 1
    assert rows[0].result_resume_id == child_id
    assert rows[0].response_data is None

    # ...deleting the source removes the rows entirely.
    assert await isolated_db.delete_resume(resume_id) is True
    assert await _fine_tune_rows(isolated_db) == []


async def test_reset_database_clears_fine_tune_previews(
    isolated_db: Any,
    sample_resume: dict[str, Any],
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(sample_resume)
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        await _preview(client, resume_id, copy.deepcopy(source), patch_complete_json)

    assert len(await _fine_tune_rows(isolated_db)) == 1
    await isolated_db.reset_database()
    assert await _fine_tune_rows(isolated_db) == []


async def test_relocation_survives_preview_and_confirm_replay(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    """All-scope relocation into additional must round-trip the confirm
    replay finalizer exactly, or the claim is rejected with a 400."""
    source = _canonical(
        {
            "personalInfo": {"name": "Li Si"},
            "summary": "",
            "workExperience": [],
            "education": [
                {
                    "id": 1,
                    "institution": "TJU",
                    "degree": "BSc",
                    "years": "2017 - 2021",
                    "description": (
                        "专业：计算机科学与技术\n"
                        "奖项：国家励志奖学金、校二等奖\n"
                        "证书：PMP项目管理证书"
                    ),
                }
            ],
            "personalProjects": [],
            "additional": {
                "technicalSkills": [],
                "languages": [],
                "certificationsTraining": [],
                "awards": [],
            },
            "customSections": {},
        }
    )
    # No original markdown: the structured education text itself is the evidence.
    resume_id = await _seed_resume(
        isolated_db, source, original_markdown=None, title="Li Si Resume"
    )
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = "专业：计算机科学与技术"
    candidate["additional"]["awards"] = ["国家励志奖学金", "校二等奖"]
    candidate["additional"]["certificationsTraining"] = ["PMP项目管理证书"]

    async with _client() as client:
        preview = await _preview(client, resume_id, candidate, patch_complete_json)
        improved = preview["improved_data"]
        assert "国家励志奖学金" in improved["additional"]["awards"]
        assert "校二等奖" in improved["additional"]["awards"]
        assert improved["additional"]["certificationsTraining"] == [
            "PMP项目管理证书"
        ]
        education_text = improved["education"][0]["description"]
        assert "奖项" not in education_text
        assert "证书" not in education_text

        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": improved,
                "mode": "copy",
            },
        )

    assert response.status_code == 200, response.text
    child_id = response.json()["resume_id"]
    child = await isolated_db.get_resume(child_id)
    assert child is not None
    assert "国家励志奖学金" in child["processed_data"]["additional"]["awards"]
    assert "奖项" not in child["processed_data"]["education"][0]["description"]


async def test_work_misfile_heals_in_preview_and_survives_overwrite_replay(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    """Deterministic healing of list-description misfiles must appear in the
    preview and the confirm replay must reproduce it byte-for-byte."""
    source = _canonical(
        {
            "personalInfo": {"name": "Wang Wu"},
            "summary": "",
            "workExperience": [
                {
                    "id": 1,
                    "title": "工程师",
                    "company": "Acme",
                    "years": "2020 - 2024",
                    "description": [
                        "负责支付系统开发",
                        "奖项：国家励志奖学金",
                        "证书：PMP项目管理证书",
                        "语言：英语六级",
                    ],
                    "descriptionStyles": ["bullet", "bullet", "bullet", "bullet"],
                }
            ],
            "education": [],
            "personalProjects": [],
            "additional": {
                "technicalSkills": [],
                "languages": [],
                "certificationsTraining": [],
                "awards": [],
            },
            "customSections": {},
        }
    )
    resume_id = await _seed_resume(
        isolated_db, source, original_markdown="# Wang Wu upload"
    )
    # The model receives the healed canonical source and echoes it.
    candidate = _canonical_source({"processed_data": source})

    async with _client() as client:
        preview = await _preview(client, resume_id, candidate, patch_complete_json)
        improved = preview["improved_data"]
        assert improved["additional"]["awards"] == ["国家励志奖学金"]
        assert improved["additional"]["certificationsTraining"] == [
            "PMP项目管理证书"
        ]
        assert improved["additional"]["languages"] == ["英语六级"]
        assert improved["workExperience"][0]["description"] == ["负责支付系统开发"]

        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": improved,
                "mode": "overwrite",
            },
        )

    assert response.status_code == 200, response.text
    master = await isolated_db.get_resume(resume_id)
    assert master is not None
    assert master["processed_data"]["additional"]["awards"] == ["国家励志奖学金"]
    assert master["processed_data"]["workExperience"][0]["description"] == [
        "负责支付系统开发"
    ]
    assert master["original_markdown"] == "# Wang Wu upload"


async def test_module_scope_emits_relocation_hint_for_unlabeled_prose(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    # Label-shaped misfiles are healed deterministically before fine-tuning;
    # the hint survives for the long tail the rules cannot touch: an
    # unlabeled certificate mention trapped inside a work description.
    source = _canonical(
        {
            "personalInfo": {"name": "Li Si"},
            "summary": "",
            "workExperience": [
                {
                    "id": 1,
                    "title": "QA",
                    "company": "Beta",
                    "years": "2021",
                    "description": ["持有 PMP 证书的轮岗经历"],
                    "descriptionStyles": ["bullet"],
                }
            ],
            "education": [],
            "personalProjects": [],
            "additional": {
                "technicalSkills": [],
                "languages": [],
                "certificationsTraining": [],
                "awards": [],
            },
            "customSections": {},
        }
    )
    resume_id = await _seed_resume(isolated_db, source, original_markdown=None)
    # The hint is derived from the source regardless of what the model returns.
    patch_complete_json.return_value = copy.deepcopy(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["work_0"]}},
        )

    assert response.status_code == 200
    assert any(
        warning.startswith("SCOPE_RELOCATION_HINT")
        for warning in response.json()["warnings"]
    )


# --- custom-section per-block scope (custom_<key>) -------------------------


def _custom_scoped_resume() -> dict[str, Any]:
    """Two itemList custom blocks let the tests separate grounding-finalizer
    approval (appended rows survive in BOTH blocks) from scope freezing (only
    the targeted block may reach the result)."""
    return {
        "personalInfo": {"name": "Wang Wu"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {
            "publications": {
                "sectionType": "itemList",
                "items": [
                    {
                        "id": 1,
                        "title": "某核心期刊论文",
                        "years": "2019",
                        "description": ["提出一种新架构"],
                        "descriptionStyles": ["bullet"],
                    }
                ],
            },
            "talks": {
                "sectionType": "itemList",
                "items": [
                    {
                        "id": 1,
                        "title": "内部分享会",
                        "years": "2023",
                        "description": ["分享微服务治理实践"],
                        "descriptionStyles": ["bullet"],
                    }
                ],
            },
            "self_evaluation": {"sectionType": "text", "text": "踏实肯干"},
            # Builder-created keys are themselves custom_N: the token is the
            # double-prefixed custom_custom_1.
            "custom_1": {"sectionType": "stringList", "strings": ["阅读", "跑步"]},
        },
        "sectionMeta": [
            {
                "id": "publications",
                "key": "publications",
                "displayName": "Publications",
                "sectionType": "itemList",
                "isDefault": False,
                "isVisible": True,
                "order": 0,
            },
            {
                "id": "talks",
                "key": "talks",
                "displayName": "技术分享",
                "sectionType": "itemList",
                "isDefault": False,
                "isVisible": True,
                "order": 1,
            },
            {
                "id": "self_evaluation",
                "key": "self_evaluation",
                "displayName": "自我评价",
                "sectionType": "text",
                "isDefault": False,
                "isVisible": True,
                "order": 2,
            },
            {
                "id": "custom_1",
                "key": "custom_1",
                "displayName": "兴趣爱好",
                "sectionType": "stringList",
                "isDefault": False,
                "isVisible": True,
                "order": 3,
            },
        ],
    }


def _custom_scoped_candidate(source: dict[str, Any]) -> dict[str, Any]:
    """Append a number-free qualitative row to BOTH itemList blocks (both rows
    survive the grounding finalizer as review claims) and edit the
    text/stringList blocks as well. Only publications is in scope."""
    candidate = copy.deepcopy(source)
    publications = candidate["customSections"]["publications"]["items"][0]
    publications["description"] = publications["description"] + [
        "相关成果在团队内部推广应用"
    ]
    publications["descriptionStyles"] = publications["descriptionStyles"] + [
        "bullet"
    ]
    talks = candidate["customSections"]["talks"]["items"][0]
    talks["description"] = talks["description"] + ["获得同事广泛好评"]
    talks["descriptionStyles"] = talks["descriptionStyles"] + ["bullet"]
    candidate["customSections"]["self_evaluation"]["text"] = "踏实肯干，责任心强"
    candidate["customSections"]["custom_1"]["strings"] = list(
        candidate["customSections"]["custom_1"]["strings"]
    ) + ["游泳"]
    return candidate


async def test_custom_block_scope_changes_only_targeted_block(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_custom_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = _custom_scoped_candidate(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["custom_publications"]}},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    custom = body["improved_data"]["customSections"]

    # The targeted block keeps the model's appended review claim...
    assert custom["publications"]["items"][0]["description"] == [
        "提出一种新架构",
        "相关成果在团队内部推广应用",
    ]
    # ...while every other custom block is frozen byte-for-byte at the source.
    # The talks row in particular WOULD survive an all-section grounding run,
    # so its absence proves the per-key overlay, not the finalizer, froze it.
    source_custom = _canonical_source({"processed_data": source})["customSections"]
    assert custom["talks"] == source_custom["talks"]
    assert custom["self_evaluation"] == source_custom["self_evaluation"]
    assert custom["custom_1"] == source_custom["custom_1"]
    assert "获得同事广泛好评" not in json.dumps(custom["talks"], ensure_ascii=False)
    assert "游泳" not in json.dumps(custom["custom_1"], ensure_ascii=False)
    assert body["scope"] == {"kind": "modules", "targets": ["custom_publications"]}


async def test_preview_reports_ignored_unknown_custom_block_token(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_custom_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = copy.deepcopy(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["custom_ghost"]}},
        )

    assert response.status_code == 200
    assert (
        "Ignored out-of-range target: custom_ghost"
        in response.json()["warnings"]
    )
    # Syntactically valid but absent from the resume: nothing is in scope, so
    # the result equals the canonical source exactly.
    assert response.json()["improved_data"] == _canonical_source(
        {"processed_data": source}
    )


async def test_preview_rejects_malformed_custom_block_token(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_custom_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={"scope": {"kind": "modules", "targets": ["custom_"]}},
        )

    assert response.status_code == 422
    patch_complete_json.assert_not_called()


async def test_custom_block_scope_survives_preview_and_copy_replay(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    """The per-key overlay must be reproduced byte-for-byte by the confirm
    replay, which reruns the same pure finalizer + scope functions."""
    source = _canonical(_custom_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    candidate = _custom_scoped_candidate(source)

    async with _client() as client:
        preview = await _preview(
            client,
            resume_id,
            candidate,
            patch_complete_json,
            scope={"kind": "modules", "targets": ["custom_publications"]},
        )
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
            },
        )

    assert response.status_code == 200, response.text
    child = await isolated_db.get_resume(response.json()["resume_id"])
    assert child is not None
    custom = child["processed_data"]["customSections"]
    assert custom["publications"]["items"][0]["description"] == [
        "提出一种新架构",
        "相关成果在团队内部推广应用",
    ]
    source_custom = _canonical_source({"processed_data": source})["customSections"]
    assert custom["talks"] == source_custom["talks"]
    assert custom["self_evaluation"] == source_custom["self_evaluation"]
    assert custom["custom_1"] == source_custom["custom_1"]


# --- label-region scope (project_N:<region>) -------------------------------


def _region_scoped_resume() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Hou Fuwen"},
        "summary": "",
        "workExperience": [],
        "education": [],
        "personalProjects": [
            {
                "id": 1,
                "name": "超鹿运动",
                "role": "后端开发",
                "years": "2023 - 2024",
                "description": [
                    "技术栈：",
                    "Java",
                    "Spring Boot",
                    "Redis",
                    "项目背景：",
                    "面向连锁健身场景的数字化平台。",
                    "项目职责：",
                    "负责核心模块的后端设计与开发。",
                    "统筹需求拆解与版本交付。",
                    "项目亮点：",
                    "订单重构方案落地，降低迁移风险。",
                    "核心接口响应耗时降低四成。",
                ],
                "descriptionStyles": [
                    "label",
                    "plain",
                    "plain",
                    "plain",
                    "label",
                    "plain",
                    "label",
                    "bullet",
                    "bullet",
                    "label",
                    "bullet",
                    "bullet",
                ],
            }
        ],
        "additional": {
            "technicalSkills": [],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


_STAR_1 = (
    "S：旧订单系统耦合严重迁移风险高；T：主导订单重构方案设计；"
    "A：制定灰度切换与回滚策略；R：重构方案平稳落地，显著降低迁移风险。"
)
_STAR_2 = (
    "S：核心接口响应耗时偏高；T：负责接口性能优化；"
    "A：引入缓存并改造慢查询；R：核心接口响应耗时降低四成。"
)


def _region_scoped_candidate(
    source: dict[str, Any], *, extra_rows: bool = False
) -> dict[str, Any]:
    """Rewrite highlights AND touch the background (out of scope); with
    extra_rows the model also appends two highlight rows."""
    candidate = copy.deepcopy(source)
    entry = candidate["personalProjects"][0]
    entry["description"][5] = "模型改写了项目背景但应当被冻结。"
    entry["description"][10] = _STAR_1
    entry["description"][11] = _STAR_2
    if extra_rows:
        entry["description"] = list(entry["description"]) + [
            "追加的亮点行甲。",
            "追加的亮点行乙。",
        ]
        entry["descriptionStyles"] = list(entry["descriptionStyles"]) + [
            "bullet",
            "bullet",
        ]
    return candidate


async def test_region_scope_changes_only_label_region_rows(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_region_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = _region_scoped_candidate(source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={
                "scope": {"kind": "modules", "targets": ["project_0:highlights"]}
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    entry = body["improved_data"]["personalProjects"][0]
    source_entry = _canonical_source({"processed_data": source})[
        "personalProjects"
    ][0]

    # STAR rows are bullets: hygiene strips their trailing periods.
    assert entry["description"][10] == _STAR_1[:-1]
    assert entry["description"][11] == _STAR_2[:-1]
    # Label row and every other region are byte-identical to the source.
    assert entry["description"][:10] == source_entry["description"][:10]
    assert entry["description"][9] == "项目亮点："
    assert entry["descriptionStyles"] == source_entry["descriptionStyles"]
    assert "应当被冻结" not in json.dumps(body["improved_data"], ensure_ascii=False)
    assert not [w for w in body["warnings"] if w.startswith("REGION_APPEND_DROPPED")]
    assert body["scope"] == {
        "kind": "modules",
        "targets": ["project_0:highlights"],
    }


async def test_region_scope_survives_preview_and_copy_replay(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_region_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    candidate = _region_scoped_candidate(source)

    async with _client() as client:
        preview = await _preview(
            client,
            resume_id,
            candidate,
            patch_complete_json,
            scope={"kind": "modules", "targets": ["project_0:highlights"]},
        )
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
            },
        )

    assert response.status_code == 200, response.text
    child = await isolated_db.get_resume(response.json()["resume_id"])
    assert child is not None
    entry = child["processed_data"]["personalProjects"][0]
    source_entry = _canonical_source({"processed_data": source})[
        "personalProjects"
    ][0]
    assert entry["description"][10] == _STAR_1[:-1]
    assert entry["description"][11] == _STAR_2[:-1]
    assert entry["description"][:10] == source_entry["description"][:10]
    assert entry["descriptionStyles"] == source_entry["descriptionStyles"]


async def test_region_style_reformat_survives_preview_and_copy_replay(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    # Explicit presentation request: texts are copied byte-for-byte and only
    # descriptionStyles move (background plain -> bullet, highlights bullets
    # -> plain). The confirm replay must re-finalize with the same opt-in or
    # it 400s with "no longer satisfies preservation rules".
    source = _canonical(_region_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    candidate = copy.deepcopy(source)
    styles = candidate["personalProjects"][0]["descriptionStyles"]
    styles[5] = "bullet"
    styles[10] = "plain"
    styles[11] = "plain"

    async with _client() as client:
        preview = await _preview(
            client,
            resume_id,
            candidate,
            patch_complete_json,
            scope={
                "kind": "modules",
                "targets": ["project_0:background", "project_0:highlights"],
            },
        )
        preview_entry = preview["improved_data"]["personalProjects"][0]
        # Endings follow the FINAL row style: bullet rows 7/8 were healed from
        # the source and the background row flipped to bullet loses its period
        # (5); the highlight rows flipped to plain keep their prose periods
        # (10/11). Only styles move there — the candidate text is verbatim.
        assert preview_entry["description"] == [
            "技术栈：",
            "Java",
            "Spring Boot",
            "Redis",
            "项目背景：",
            "面向连锁健身场景的数字化平台",
            "项目职责：",
            "负责核心模块的后端设计与开发",
            "统筹需求拆解与版本交付",
            "项目亮点：",
            "订单重构方案落地，降低迁移风险。",
            "核心接口响应耗时降低四成。",
        ]
        assert preview_entry["descriptionStyles"][5] == "bullet"
        assert preview_entry["descriptionStyles"][10:12] == ["plain", "plain"]

        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/confirm",
            json={
                "preview_id": preview["preview_id"],
                "improved_data": preview["improved_data"],
                "mode": "copy",
            },
        )

    assert response.status_code == 200, response.text
    child = await isolated_db.get_resume(response.json()["resume_id"])
    assert child is not None
    entry = child["processed_data"]["personalProjects"][0]
    assert entry["descriptionStyles"][5] == "bullet"
    assert entry["descriptionStyles"][10:12] == ["plain", "plain"]
    # Rows outside both regions keep their source styles.
    assert entry["descriptionStyles"][:5] == ["label", "plain", "plain", "plain", "label"]
    assert entry["descriptionStyles"][6:10] == [
        "label",
        "bullet",
        "bullet",
        "label",
    ]


async def test_region_scope_warns_and_drops_extra_rows(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_region_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)
    patch_complete_json.return_value = _region_scoped_candidate(
        source, extra_rows=True
    )

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={
                "scope": {"kind": "modules", "targets": ["project_0:highlights"]}
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert any(
        w.startswith("REGION_APPEND_DROPPED") for w in body["warnings"]
    ), body["warnings"]
    entry = body["improved_data"]["personalProjects"][0]
    assert len(entry["description"]) == 12
    assert "追加的亮点行甲。" not in entry["description"]
    assert "追加的亮点行乙。" not in entry["description"]


async def test_preview_rejects_malformed_region_token(
    isolated_db: Any,
    patch_complete_json: AsyncMock,
) -> None:
    source = _canonical(_region_scoped_resume())
    resume_id = await _seed_resume(isolated_db, source)

    async with _client() as client:
        response = await client.post(
            f"/api/v1/resumes/{resume_id}/fine-tune/preview",
            json={
                "scope": {"kind": "modules", "targets": ["project_0:bogus"]}
            },
        )

    assert response.status_code == 422
    patch_complete_json.assert_not_called()
