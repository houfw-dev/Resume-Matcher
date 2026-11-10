"""Integration tests for resume CRUD endpoints."""

from typing import Any

import json
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai_limits import MAX_JOB_CHARACTERS
from app.database import ResumeNotFoundError
from app.main import app
from app.schemas import InterviewPrepData


SAMPLE_INTERVIEW_PREP = {
    "role_fit_analysis": ["Backend API experience maps to the role."],
    "resume_questions": [
        {
            "question": "How did you design the FastAPI service on your resume?",
            "focus_area": "Backend architecture",
            "suggested_answer_points": ["Discuss the documented API work only."],
        }
    ],
    "project_follow_ups": [
        {
            "question": "What tradeoffs did you make in the resume matcher project?",
            "focus_area": "Project implementation",
            "suggested_answer_points": ["Explain real project choices from the resume."],
        }
    ],
    "skill_gaps": [
        {
            "skill": "Kubernetes",
            "why_it_matters": "The job description mentions production deployment.",
            "preparation_suggestion": "Review core concepts without claiming production use.",
        }
    ],
    "talking_points": ["Connect API work to the job's backend requirements."],
}


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def mock_resume_record(sample_resume):
    """A resume DB record with all fields."""
    return {
        "resume_id": "res-123",
        "content": "# Jane Doe\nSenior Backend Engineer",
        "content_type": "md",
        "filename": "resume.pdf",
        "is_master": True,
        "parent_id": None,
        "processed_data": sample_resume,
        "processing_status": "ready",
        "cover_letter": None,
        "outreach_message": None,
        "interview_prep": None,
        "title": None,
        "original_markdown": "# Jane Doe\nSenior Backend Engineer",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


class TestGetResume:
    """GET /api/v1/resumes?resume_id=..."""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_fetch_existing_resume(self, mock_db, client, mock_resume_record):
        mock_db.get_resume.return_value = mock_resume_record
        async with client:
            resp = await client.get("/api/v1/resumes", params={"resume_id": "res-123"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["resume_id"] == "res-123"
        assert data["processed_resume"] is not None
        assert data["processed_resume"]["summary"] != ""
        assert data["interview_prep"] is None

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_invalid_interview_prep_does_not_break_fetch(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "interview_prep": "{not-json",
        }
        async with client:
            resp = await client.get("/api/v1/resumes", params={"resume_id": "res-123"})
        assert resp.status_code == 200
        assert resp.json()["data"]["interview_prep"] is None

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_fetch_nonexistent_returns_404(self, mock_db, client):
        mock_db.get_resume.return_value = None
        async with client:
            resp = await client.get("/api/v1/resumes", params={"resume_id": "nonexistent"})
        assert resp.status_code == 404


class TestListResumes:
    """GET /api/v1/resumes/list"""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_list_excludes_master_by_default(self, mock_db, client):
        mock_db.list_resumes.return_value = [
            {"resume_id": "master", "is_master": True, "created_at": "2026-01-01", "updated_at": "2026-01-01"},
            {"resume_id": "tailored-1", "is_master": False, "created_at": "2026-01-02", "updated_at": "2026-01-02"},
        ]
        async with client:
            resp = await client.get("/api/v1/resumes/list")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["resume_id"] == "tailored-1"

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_list_includes_master_when_requested(self, mock_db, client):
        mock_db.list_resumes.return_value = [
            {"resume_id": "master", "is_master": True, "created_at": "2026-01-01", "updated_at": "2026-01-01"},
            {"resume_id": "tailored-1", "is_master": False, "created_at": "2026-01-02", "updated_at": "2026-01-02"},
        ]
        async with client:
            resp = await client.get("/api/v1/resumes/list", params={"include_master": True})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2


class TestDeleteResume:
    """DELETE /api/v1/resumes/{resume_id}"""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_delete_existing_resume(self, mock_db, client):
        mock_db.delete_resume.return_value = True
        async with client:
            resp = await client.delete("/api/v1/resumes/res-123")
        assert resp.status_code == 200

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_delete_nonexistent_returns_404(self, mock_db, client):
        mock_db.delete_resume.return_value = False
        async with client:
            resp = await client.delete("/api/v1/resumes/nonexistent")
        assert resp.status_code == 404


class TestUpdateTitle:
    """PATCH /api/v1/resumes/{resume_id}/title"""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_update_title(self, mock_db, client, mock_resume_record):
        mock_db.get_resume.return_value = mock_resume_record
        mock_db.update_resume.return_value = {**mock_resume_record, "title": "New Title"}
        async with client:
            resp = await client.patch("/api/v1/resumes/res-123/title", json={"title": "New Title"})
        assert resp.status_code == 200

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_update_title_nonexistent_returns_404(self, mock_db, client):
        mock_db.get_resume.return_value = None
        async with client:
            resp = await client.patch("/api/v1/resumes/nonexistent/title", json={"title": "X"})
        assert resp.status_code == 404


class TestUpdateCoverLetter:
    """PATCH /api/v1/resumes/{resume_id}/cover-letter"""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_update_cover_letter(self, mock_db, client, mock_resume_record):
        mock_db.get_resume.return_value = mock_resume_record
        mock_db.update_resume.return_value = {**mock_resume_record, "cover_letter": "Dear hiring manager..."}
        async with client:
            resp = await client.patch("/api/v1/resumes/res-123/cover-letter", json={"content": "Dear hiring manager..."})
        assert resp.status_code == 200


class TestUpdateOutreachMessage:
    """PATCH /api/v1/resumes/{resume_id}/outreach-message"""

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_update_outreach(self, mock_db, client, mock_resume_record):
        mock_db.get_resume.return_value = mock_resume_record
        mock_db.update_resume.return_value = {**mock_resume_record, "outreach_message": "Hi, I saw your posting..."}
        async with client:
            resp = await client.patch("/api/v1/resumes/res-123/outreach-message", json={"content": "Hi, I saw your posting..."})
        assert resp.status_code == 200


class TestGenerateCoverLetterFromResume:
    """POST /api/v1/resumes/{resume_id}/cover-letter/generate"""

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_master_resume_without_jd(
        self,
        mock_db: AsyncMock,
        mock_generate: AsyncMock,
        _mock_language: MagicMock,
        client: AsyncClient,
        mock_resume_record: dict,
        sample_resume: dict,
    ) -> None:
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "Dear team..."

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/cover-letter/generate", json={}
            )

        assert resp.status_code == 200
        assert resp.json()["content"] == "Dear team..."
        # Master resume (no parent_id) and empty JD are both accepted.
        mock_generate.assert_awaited_once_with(sample_resume, "", "en")
        mock_db.update_resume.assert_awaited_once_with(
            "res-123", {"cover_letter": "Dear team..."}
        )

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_with_jd_passes_jd_to_service(
        self,
        mock_db: AsyncMock,
        mock_generate: AsyncMock,
        _mock_language: MagicMock,
        client: AsyncClient,
        mock_resume_record: dict,
        sample_resume: dict,
    ) -> None:
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "Tailored letter"

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/cover-letter/generate",
                json={"job_description": "Need FastAPI and ETL"},
            )

        assert resp.status_code == 200
        mock_generate.assert_awaited_once_with(
            sample_resume, "Need FastAPI and ETL", "en"
        )

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_missing_resume_returns_404(
        self, mock_db: AsyncMock, client: AsyncClient
    ) -> None:
        mock_db.get_resume.return_value = None

        async with client:
            resp = await client.post(
                "/api/v1/resumes/nonexistent/cover-letter/generate", json={}
            )

        assert resp.status_code == 404

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_missing_processed_data_returns_400(
        self,
        mock_db: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict,
    ) -> None:
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processed_data": None,
        }

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/cover-letter/generate", json={}
            )

        assert resp.status_code == 400
        assert "processed data" in resp.json()["detail"]

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_oversized_jd_returns_422(
        self,
        mock_db: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict,
    ) -> None:
        mock_db.get_resume.return_value = mock_resume_record

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/cover-letter/generate",
                json={"job_description": "x" * (MAX_JOB_CHARACTERS + 1)},
            )

        assert resp.status_code == 422
        # Request validation fails before the handler runs.
        mock_db.update_resume.assert_not_called()

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_generation_failure_returns_500(
        self,
        mock_db: AsyncMock,
        mock_generate: AsyncMock,
        _mock_language: MagicMock,
        client: AsyncClient,
        mock_resume_record: dict,
    ) -> None:
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.side_effect = RuntimeError("llm down")

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/cover-letter/generate", json={}
            )

        assert resp.status_code == 500
        assert "Failed to generate cover letter" in resp.json()["detail"]
        mock_db.update_resume.assert_not_called()


class TestGenerateInterviewPrep:
    """POST /api/v1/resumes/{resume_id}/generate-interview-prep"""

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_interview_prep", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_success_saves_structured_json(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record, sample_resume
    ):
        tailored = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": sample_resume,
        }
        mock_db.get_resume.return_value = tailored
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}
        mock_generate.return_value = InterviewPrepData.model_validate(SAMPLE_INTERVIEW_PREP)

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-interview-prep")

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Interview preparation generated successfully"
        assert data["interview_prep"]["role_fit_analysis"] == SAMPLE_INTERVIEW_PREP[
            "role_fit_analysis"
        ]
        mock_generate.assert_awaited_once_with(sample_resume, "Need FastAPI", "en")
        update_payload = mock_db.update_resume.await_args.args[1]
        saved_payload = json.loads(update_payload["interview_prep"])
        assert saved_payload == SAMPLE_INTERVIEW_PREP

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_interview_prep", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_standalone_resume_generates_without_job_context(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        # Standalone (non-tailored) resumes generate resume-only preparation via
        # the service's no-JD prompt branch; no improvement lookup happens.
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = InterviewPrepData.model_validate(SAMPLE_INTERVIEW_PREP)

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-interview-prep")

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_db.get_job.assert_not_called()
        mock_generate.assert_awaited_once_with(mock_resume_record["processed_data"], "", "en")
        update_payload = mock_db.update_resume.await_args.args[1]
        assert json.loads(update_payload["interview_prep"]) == SAMPLE_INTERVIEW_PREP

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_interview_prep", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_targets_standalone_generation(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        # A JD pasted in the request body drives role-targeted preparation for
        # a standalone resume, with no improvement/job lookup.
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = InterviewPrepData.model_validate(SAMPLE_INTERVIEW_PREP)

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-interview-prep",
                json={"job_description": "  Need Kubernetes and FastAPI  "},
            )

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_db.get_job.assert_not_called()
        # Whitespace is trimmed before the JD reaches the service.
        mock_generate.assert_awaited_once_with(
            mock_resume_record["processed_data"], "Need Kubernetes and FastAPI", "en"
        )

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_oversized_returns_422(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-interview-prep",
                json={"job_description": "x" * (MAX_JOB_CHARACTERS + 1)},
            )

        assert resp.status_code == 422
        # Request validation fails before the handler runs.
        mock_db.update_resume.assert_not_called()

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_rejects_missing_improvement_context(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {**mock_resume_record, "parent_id": "master-1"}
        mock_db.get_improvement_by_tailored_resume.return_value = None

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-interview-prep")

        assert resp.status_code == 400
        assert "No job context" in resp.json()["detail"]

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_rejects_missing_processed_data(self, mock_db, client, mock_resume_record):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": None,
        }
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-interview-prep")

        assert resp.status_code == 400
        assert "processed data" in resp.json()["detail"]

    @patch("app.routers.resumes.generate_interview_prep", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_generation_failure_returns_500(
        self, mock_db, mock_generate, client, mock_resume_record, sample_resume
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": sample_resume,
        }
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}
        mock_generate.side_effect = RuntimeError("llm failed")

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-interview-prep")

        assert resp.status_code == 500
        assert "Failed to generate interview preparation" in resp.json()["detail"]


class TestOnDemandCoverLetter:
    """POST /api/v1/resumes/{resume_id}/generate-cover-letter"""

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_standalone_resume_uses_empty_job_description(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "Resume-only cover letter"

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-cover-letter")

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_generate.assert_awaited_once_with(
            mock_resume_record["processed_data"], "", "en"
        )
        mock_db.update_resume.assert_awaited_once_with(
            "res-123", {"cover_letter": "Resume-only cover letter"}
        )

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_targets_standalone_generation(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        # A JD pasted in the request body produces a role-targeted letter for
        # a standalone resume, with no improvement/job lookup.
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "JD-targeted cover letter"

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-cover-letter",
                json={"job_description": "Need Kubernetes and FastAPI"},
            )

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_db.get_job.assert_not_called()
        mock_generate.assert_awaited_once_with(
            mock_resume_record["processed_data"], "Need Kubernetes and FastAPI", "en"
        )
        mock_db.update_resume.assert_awaited_once_with(
            "res-123", {"cover_letter": "JD-targeted cover letter"}
        )

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_takes_precedence_over_stored_job(
        self,
        mock_db,
        mock_generate,
        _mock_language,
        client,
        mock_resume_record,
        sample_resume,
    ):
        # Even a tailored resume uses the pasted JD when one is supplied.
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": sample_resume,
        }
        mock_generate.return_value = "Ad-hoc targeted letter"

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-cover-letter",
                json={"job_description": "Fresh role requirements"},
            )

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_generate.assert_awaited_once_with(sample_resume, "Fresh role requirements", "en")

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_tailored_resume_uses_stored_job(
        self,
        mock_db,
        mock_generate,
        _mock_language,
        client,
        mock_resume_record,
        sample_resume,
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": sample_resume,
        }
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}
        mock_generate.return_value = "Tailored cover letter"

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-cover-letter")

        assert resp.status_code == 200
        mock_generate.assert_awaited_once_with(sample_resume, "Need FastAPI", "en")

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_missing_processed_data_returns_400(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processed_data": None,
        }

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-cover-letter")

        assert resp.status_code == 400
        assert "processed data" in resp.json()["detail"]

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_tailored_without_improvement_returns_400(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
        }
        mock_db.get_improvement_by_tailored_resume.return_value = None

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-cover-letter")

        assert resp.status_code == 400
        assert "No job context" in resp.json()["detail"]

    @patch("app.routers.resumes.generate_cover_letter", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_generation_failure_returns_500(
        self, mock_db, mock_generate, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.side_effect = RuntimeError("llm failed")

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-cover-letter")

        assert resp.status_code == 500
        assert "Failed to generate cover letter" in resp.json()["detail"]


class TestOnDemandOutreach:
    """POST /api/v1/resumes/{resume_id}/generate-outreach"""

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_outreach_message", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_standalone_resume_uses_empty_job_description(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "Resume-only outreach"

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-outreach")

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_generate.assert_awaited_once_with(
            mock_resume_record["processed_data"], "", "en"
        )
        mock_db.update_resume.assert_awaited_once_with(
            "res-123", {"outreach_message": "Resume-only outreach"}
        )

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_outreach_message", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_targets_standalone_generation(
        self, mock_db, mock_generate, _mock_language, client, mock_resume_record
    ):
        # A JD pasted in the request body produces a role-targeted message for
        # a standalone resume, with no improvement/job lookup.
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.return_value = "JD-targeted outreach"

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-outreach",
                json={"job_description": "Need Kubernetes and FastAPI"},
            )

        assert resp.status_code == 200
        mock_db.get_improvement_by_tailored_resume.assert_not_called()
        mock_db.get_job.assert_not_called()
        mock_generate.assert_awaited_once_with(
            mock_resume_record["processed_data"], "Need Kubernetes and FastAPI", "en"
        )
        mock_db.update_resume.assert_awaited_once_with(
            "res-123", {"outreach_message": "JD-targeted outreach"}
        )

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_ad_hoc_jd_oversized_returns_422(
        self, mock_db, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record

        async with client:
            resp = await client.post(
                "/api/v1/resumes/res-123/generate-outreach",
                json={"job_description": "x" * (MAX_JOB_CHARACTERS + 1)},
            )

        assert resp.status_code == 422
        # Request validation fails before the handler runs.
        mock_db.update_resume.assert_not_called()

    @patch("app.routers.resumes.get_content_language", return_value="en")
    @patch("app.routers.resumes.generate_outreach_message", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_tailored_resume_uses_stored_job(
        self,
        mock_db,
        mock_generate,
        _mock_language,
        client,
        mock_resume_record,
        sample_resume,
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
            "processed_data": sample_resume,
        }
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}
        mock_generate.return_value = "Tailored outreach"

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-outreach")

        assert resp.status_code == 200
        mock_generate.assert_awaited_once_with(sample_resume, "Need FastAPI", "en")

    @patch("app.routers.resumes.generate_outreach_message", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_generation_failure_returns_500(
        self, mock_db, mock_generate, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record
        mock_generate.side_effect = RuntimeError("llm failed")

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/generate-outreach")

        assert resp.status_code == 500
        assert "Failed to generate outreach message" in resp.json()["detail"]


class TestContentPdfExports:
    """GET /api/v1/resumes/{resume_id}/{kind}/pdf"""

    @pytest.mark.parametrize(
        "path,selector,field,value",
        [
            (
                "/api/v1/resumes/res-123/interview-prep/pdf",
                ".interview-prep-print",
                "interview_prep",
                json.dumps(SAMPLE_INTERVIEW_PREP),
            ),
            (
                "/api/v1/resumes/res-123/cover-letter/pdf",
                ".cover-letter-print",
                "cover_letter",
                "Dear team, ...",
            ),
            (
                "/api/v1/resumes/res-123/outreach/pdf",
                ".outreach-print",
                "outreach_message",
                "Hello recruiter, ...",
            ),
        ],
    )
    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_pdf_renders_stored_content(
        self,
        mock_db,
        mock_render,
        client,
        mock_resume_record,
        path,
        selector,
        field,
        value,
    ):
        mock_db.get_resume.return_value = {**mock_resume_record, field: value}
        mock_render.return_value = b"%PDF-1.4 synthetic"

        async with client:
            resp = await client.get(path)

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        url = mock_render.await_args.args[0]
        assert "pageSize=A4" in url
        assert mock_render.await_args.kwargs["selector"] == selector

    @pytest.mark.parametrize(
        "path,field",
        [
            ("/api/v1/resumes/res-123/interview-prep/pdf", "interview_prep"),
            ("/api/v1/resumes/res-123/cover-letter/pdf", "cover_letter"),
            ("/api/v1/resumes/res-123/outreach/pdf", "outreach_message"),
        ],
    )
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_missing_content_returns_404(
        self, mock_db, client, mock_resume_record, path, field
    ):
        mock_db.get_resume.return_value = {**mock_resume_record, field: None}

        async with client:
            resp = await client.get(path)

        assert resp.status_code == 404

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_jd_match_requires_tailored_resume(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = mock_resume_record

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/jd-match/pdf")

        assert resp.status_code == 404
        assert "JD matching" in resp.json()["detail"]
        mock_render.assert_not_called()

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_jd_match_pdf_renders_for_tailored_resume(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "parent_id": "master-1",
        }
        mock_db.get_improvement_by_tailored_resume.return_value = {"job_id": "job-1"}
        mock_db.get_job.return_value = {"job_id": "job-1", "content": "Need FastAPI"}
        mock_render.return_value = b"%PDF-1.4 synthetic"

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/jd-match/pdf")

        assert resp.status_code == 200
        url = mock_render.await_args.args[0]
        assert "/print/jd-match/res-123" in url
        assert mock_render.await_args.kwargs["selector"] == ".jd-match-print"

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_render_failure_returns_503(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        from app.pdf import PDFRenderError

        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "interview_prep": json.dumps(SAMPLE_INTERVIEW_PREP),
        }
        mock_render.side_effect = PDFRenderError("browser failed")

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/interview-prep/pdf")

        assert resp.status_code == 503
        assert "browser failed" in resp.json()["detail"]

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_unknown_resume_returns_404(self, mock_db, client):
        mock_db.get_resume.return_value = None

        async with client:
            resp = await client.get("/api/v1/resumes/missing/interview-prep/pdf")

        assert resp.status_code == 404

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_resume_pdf_rejects_processing_record_without_rendering(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        """A still-processing record fails fast (409) instead of a blank PDF or a 60s render timeout."""
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processing_status": "processing",
        }

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/pdf")

        assert resp.status_code == 409
        assert "still being processed" in resp.json()["detail"]
        mock_render.assert_not_called()

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_resume_pdf_rejects_failed_record_without_rendering(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processing_status": "failed",
        }

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/pdf")

        assert resp.status_code == 409
        mock_render.assert_not_called()

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_resume_pdf_rejects_ready_record_without_renderable_data(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        """Ready but markdown-only (no structured data) cannot render — 422, never a blank shell."""
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processed_data": None,
            "content_type": "md",
            "content": "# Markdown only",
        }

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/pdf")

        assert resp.status_code == 422
        assert "not available for export" in resp.json()["detail"]
        mock_render.assert_not_called()

    @patch("app.routers.resumes.render_resume_pdf", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_resume_pdf_renders_ready_record(
        self, mock_db, mock_render, client, mock_resume_record
    ):
        """The readiness gate must not block the normal ready-with-data export path."""
        mock_db.get_resume.return_value = mock_resume_record
        mock_render.return_value = b"%PDF-1.4 synthetic"

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/pdf")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        mock_render.assert_awaited_once()

    @patch("app.routers.resumes.build_resume_docx", new_callable=MagicMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_resume_docx_rejects_processing_record(
        self, mock_db, mock_build, client, mock_resume_record
    ):
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processing_status": "processing",
        }

        async with client:
            resp = await client.get("/api/v1/resumes/res-123/docx")

        assert resp.status_code == 409
        assert "still being processed" in resp.json()["detail"]
        mock_build.assert_not_called()


class TestRetryProcessing:
    """POST /api/v1/resumes/{resume_id}/retry-processing"""

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_successful(
        self,
        mock_db: AsyncMock,
        mock_parse: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict[str, Any],
        sample_resume: dict[str, Any],
    ) -> None:
        failed_record = {**mock_resume_record, "processing_status": "failed"}
        mock_db.get_resume.return_value = failed_record
        mock_db.claim_resume_processing.return_value = "token-1"
        mock_db.finish_resume_processing.return_value = "committed"
        mock_parse.return_value = sample_resume
        async with client:
            resp = await client.post("/api/v1/resumes/res-123/retry-processing")
        assert resp.status_code == 200
        data = resp.json()
        assert data["processing_status"] == "ready"

    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_not_failed_returns_400(
        self, mock_db: AsyncMock, client: AsyncClient, mock_resume_record: dict[str, Any]
    ) -> None:
        # processing_status is "ready", not "failed"
        mock_db.get_resume.return_value = mock_resume_record
        async with client:
            resp = await client.post("/api/v1/resumes/res-123/retry-processing")
        assert resp.status_code == 400

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_empty_legacy_ready_resume(
        self,
        mock_db: AsyncMock,
        mock_parse: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict[str, Any],
        sample_resume: dict[str, Any],
    ) -> None:
        empty_ready_record = {
            **mock_resume_record,
            "processing_status": "ready",
            "processed_data": {},
        }
        mock_db.get_resume.return_value = empty_ready_record
        mock_db.claim_resume_processing.return_value = "token-1"
        mock_db.finish_resume_processing.return_value = "committed"
        mock_parse.return_value = sample_resume
        async with client:
            resp = await client.post("/api/v1/resumes/res-123/retry-processing")
        assert resp.status_code == 200
        mock_parse.assert_awaited_once_with(empty_ready_record["content"])

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_legacy_ready_resume_with_schema_defaults(
        self,
        mock_db: AsyncMock,
        mock_parse: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict[str, Any],
        sample_resume: dict[str, Any],
    ) -> None:
        legacy_default_record = {
            **mock_resume_record,
            "processing_status": "ready",
            "processed_data": {
                "workExperience": [
                    {
                        "id": 0,
                        "title": "",
                        "company": "",
                        "description": [],
                        "descriptionStyles": [],
                    }
                ],
                "customSections": {
                    "empty": {
                        "sectionType": "itemList",
                        "items": [{"id": 0, "title": "", "description": []}],
                    }
                },
            },
        }
        mock_db.get_resume.return_value = legacy_default_record
        mock_db.claim_resume_processing.return_value = "token-1"
        mock_db.finish_resume_processing.return_value = "committed"
        mock_parse.return_value = sample_resume

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/retry-processing")

        assert resp.status_code == 200
        assert resp.json()["processing_status"] == "ready"
        mock_parse.assert_awaited_once_with(legacy_default_record["content"])
        mock_db.finish_resume_processing.assert_awaited_once_with(
            "res-123",
            "token-1",
            processing_status="ready",
            processed_data=sample_resume,
        )

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_returns_404_when_resume_deleted_mid_retry(
        self,
        mock_db: AsyncMock,
        mock_parse: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict[str, Any],
    ) -> None:
        """A compare-and-set miss for a deleted retry target yields 404."""
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processing_status": "failed",
        }
        mock_db.claim_resume_processing.return_value = "token-1"
        mock_parse.side_effect = RuntimeError("llm exploded")
        mock_db.finish_resume_processing.return_value = "missing"

        async with client:
            resp = await client.post("/api/v1/resumes/res-123/retry-processing")

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Resume was deleted during retry."

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.db", new_callable=AsyncMock)
    async def test_retry_does_not_swallow_unrelated_value_errors(
        self,
        mock_db: AsyncMock,
        mock_parse: AsyncMock,
        client: AsyncClient,
        mock_resume_record: dict[str, Any],
    ) -> None:
        """Only ResumeNotFoundError becomes a 404; other ValueErrors propagate."""
        mock_db.get_resume.return_value = {
            **mock_resume_record,
            "processing_status": "failed",
        }
        mock_db.claim_resume_processing.return_value = "token-1"
        mock_parse.side_effect = RuntimeError("llm exploded")
        mock_db.finish_resume_processing.side_effect = ValueError("Resume not found: res-123")

        with pytest.raises(ValueError, match="Resume not found"):
            async with client:
                await client.post("/api/v1/resumes/res-123/retry-processing")


class TestResumeNotFoundError:
    """app.database.ResumeNotFoundError backward compatibility."""

    def test_is_a_value_error(self):
        """Subclassing ValueError keeps every pre-existing handler working."""
        assert issubclass(ResumeNotFoundError, ValueError)

        caught = False
        try:
            raise ResumeNotFoundError("res-123")
        except ValueError as exc:
            caught = True
            assert isinstance(exc, ResumeNotFoundError)
        assert caught

    def test_carries_the_resume_id(self):
        error = ResumeNotFoundError("res-123")
        assert error.resume_id == "res-123"
        assert "res-123" in str(error)

    async def test_real_update_resume_raises_the_typed_error(self, tmp_path):
        """The real Database.update_resume raises the typed error, not bare ValueError."""
        from app.database import Database

        database = Database(db_path=tmp_path / "typed_error.db")
        try:
            with pytest.raises(ResumeNotFoundError):
                await database.update_resume("does-not-exist", {"title": "X"})
        finally:
            await database.close()


class TestUploadResume:
    """POST /api/v1/resumes/upload"""

    @patch("app.routers.resumes.parse_resume_to_json", new_callable=AsyncMock)
    @patch("app.routers.resumes.parse_document", new_callable=AsyncMock)
    @patch("app.routers.resumes.db")
    async def test_upload_empty_extracted_text_returns_422(
        self, mock_db, mock_parse_document, mock_parse_resume_to_json, client
    ):
        mock_parse_document.return_value = "   "

        async with client:
            resp = await client.post(
                "/api/v1/resumes/upload",
                files={"file": ("resume.pdf", b"fake pdf bytes", "application/pdf")},
            )

        assert resp.status_code == 422
        assert "Could not extract text from the uploaded file" in resp.json()["detail"]
        mock_db.create_resume_atomic_master.assert_not_called()
        mock_parse_resume_to_json.assert_not_called()
