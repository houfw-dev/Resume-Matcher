"""JD tailoring from an eligible non-master source resume.

Before this feature the tailor flow was effectively master-only (the frontend
hardcoded the master id). The backend itself accepts any resume id, so these
tests pin the new explicit contract:

- eligibility: only master/standalone resumes (``parent_id`` NULL) that are
  ``ready`` and carry processed data may be used as a tailoring source —
  already-tailored resumes are rejected so no grandchild chains can form;
- lineage: tailoring from a standalone resume produces a child whose
  ``parent_id``, improvement relation and tracker card all point at that
  standalone source, while the global master is untouched;
- refinement baseline: keyword injection / alignment use the SELECTED source,
  not the global master.
"""

import contextlib
import copy
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import Database
from app.main import app
from app.schemas.models import ResumeData
from app.schemas.refinement import RefinementResult


def _new_client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_resume(
    database: Database,
    sample: dict[str, Any],
    *,
    is_master: bool = False,
    parent_id: str | None = None,
    processing_status: str = "ready",
    with_data: bool = True,
) -> dict[str, Any]:
    """Create a resume row with precisely controlled lineage/state."""
    data = (
        ResumeData.model_validate(copy.deepcopy(sample)).model_dump()
        if with_data
        else None
    )
    content = json.dumps(data) if data else "# Markdown-only resume"
    if is_master:
        return await database.create_resume_atomic_master(
            content=content,
            content_type="json" if data else "md",
            processed_data=data,
            processing_status=processing_status,
        )
    return await database.create_resume(
        content=content,
        content_type="json" if data else "md",
        is_master=False,
        parent_id=parent_id,
        processed_data=data,
        processing_status=processing_status,
    )


def _tailor_patches(
    improved: dict[str, Any], refine_mock: AsyncMock | None = None
) -> list[Any]:
    """The standard LLM-boundary mock stack used by pipeline e2e tests."""
    if refine_mock is None:
        refine_mock = AsyncMock(
            side_effect=RuntimeError("refinement disabled for test")
        )
    return [
        patch("app.routers.resumes._load_config", return_value={}),
        patch(
            "app.routers.resumes.extract_job_keywords",
            new_callable=AsyncMock,
            return_value={
                "keywords": ["Python", "FastAPI"],
                "required_skills": [],
                "company": "Acme Corp",
                "role": "Senior Backend Engineer",
            },
        ),
        patch(
            "app.routers.resumes.generate_skill_target_plan",
            new_callable=AsyncMock,
            return_value={"targets": []},
        ),
        patch(
            "app.routers.resumes.verify_skill_target_plan",
            return_value={"accepted": [], "rejected": []},
        ),
        patch(
            "app.routers.resumes.generate_resume_diffs",
            new_callable=AsyncMock,
            # apply_diffs is mocked too, so the diff payload only needs .changes
            return_value=SimpleNamespace(changes=[]),
        ),
        patch(
            "app.routers.resumes.apply_diffs",
            return_value=(copy.deepcopy(improved), [], []),
        ),
        patch("app.routers.resumes.verify_diff_result", return_value=[]),
        patch("app.routers.resumes.refine_resume", new=refine_mock),
    ]


class TestTailorFromStandaloneSource:
    async def test_standalone_resume_tailors_end_to_end(
        self, isolated_db: Database, sample_resume: dict[str, Any]
    ) -> None:
        # A master exists simultaneously, proving the source is selected by id
        # rather than silently falling back to the master.
        master = await _make_resume(isolated_db, sample_resume, is_master=True)
        standalone_sample = copy.deepcopy(sample_resume)
        standalone_sample["personalInfo"] = {
            **standalone_sample["personalInfo"],
            "name": "Standalone Person",
        }
        standalone = await _make_resume(isolated_db, standalone_sample)
        job = await isolated_db.create_job("Senior Backend Engineer at Acme Corp")
        improved = ResumeData.model_validate(
            copy.deepcopy(standalone_sample)
        ).model_dump()

        with contextlib.ExitStack() as stack:
            for cm in _tailor_patches(improved):
                stack.enter_context(cm)
            async with _new_client() as client:
                preview = await client.post(
                    "/api/v1/resumes/improve/preview",
                    json={
                        "resume_id": standalone["resume_id"],
                        "job_id": job["job_id"],
                    },
                )
                assert preview.status_code == 200, preview.text
                preview_data = preview.json()["data"]

                confirm = await client.post(
                    "/api/v1/resumes/improve/confirm",
                    json={
                        "resume_id": standalone["resume_id"],
                        "job_id": job["job_id"],
                        "preview_id": preview_data["preview_id"],
                        "improved_data": preview_data["resume_preview"],
                        "improvements": preview_data["improvements"],
                    },
                )
                assert confirm.status_code == 200, confirm.text
                tailored_id = confirm.json()["data"]["resume_id"]

        tailored = await isolated_db.get_resume(tailored_id)
        assert tailored is not None
        assert tailored["parent_id"] == standalone["resume_id"]
        assert tailored["is_master"] is False
        # The source itself is not promoted or mutated.
        stored_source = await isolated_db.get_resume(standalone["resume_id"])
        assert stored_source is not None and stored_source["parent_id"] is None
        stored_master = await isolated_db.get_resume(master["resume_id"])
        assert stored_master is not None and stored_master["is_master"] is True

        relation = await isolated_db.get_improvement_by_tailored_resume(tailored_id)
        assert relation is not None
        assert relation["job_id"] == job["job_id"]
        assert relation["original_resume_id"] == standalone["resume_id"]

        async with _new_client() as client:
            board = (await client.get("/api/v1/applications")).json()["columns"]
        applied = board["applied"]
        assert len(applied) == 1
        # The tracker card groups by the actual source, not the global master.
        assert applied[0]["resume_id"] == tailored_id
        assert applied[0]["master_resume_id"] == standalone["resume_id"]


class TestTailorSourceEligibility:
    @pytest.mark.parametrize(
        "path",
        [
            "/resumes/improve/preview",
            "/resumes/improve",
            "/resumes/improve/confirm",
        ],
    )
    async def test_tailored_resume_rejected_as_source_on_all_entries(
        self,
        isolated_db: Database,
        sample_resume: dict[str, Any],
        path: str,
    ) -> None:
        master = await _make_resume(isolated_db, sample_resume, is_master=True)
        child = await _make_resume(
            isolated_db, sample_resume, parent_id=master["resume_id"]
        )
        job = await isolated_db.create_job("Python engineer")
        body = {
            "resume_id": child["resume_id"],
            "job_id": job["job_id"],
            "preview_id": "nonexistent-preview",
            "improved_data": ResumeData.model_validate(
                copy.deepcopy(sample_resume)
            ).model_dump(),
            "improvements": [],
        }

        async with _new_client() as client:
            response = await client.post(f"/api/v1{path}", json=body)

        assert response.status_code == 400, response.text
        assert "tailoring source" in response.json()["detail"]

    async def test_processing_resume_rejected_as_source(
        self, isolated_db: Database, sample_resume: dict[str, Any]
    ) -> None:
        pending = await _make_resume(
            isolated_db, sample_resume, processing_status="processing"
        )
        job = await isolated_db.create_job("Python engineer")

        async with _new_client() as client:
            response = await client.post(
                "/api/v1/resumes/improve/preview",
                json={"resume_id": pending["resume_id"], "job_id": job["job_id"]},
            )

        assert response.status_code == 400, response.text
        assert "not ready" in response.json()["detail"]

    async def test_resume_without_processed_data_rejected_as_source(
        self, isolated_db: Database, sample_resume: dict[str, Any]
    ) -> None:
        markdown_only = await _make_resume(
            isolated_db, sample_resume, with_data=False
        )
        job = await isolated_db.create_job("Python engineer")

        async with _new_client() as client:
            response = await client.post(
                "/api/v1/resumes/improve/preview",
                json={
                    "resume_id": markdown_only["resume_id"],
                    "job_id": job["job_id"],
                },
            )

        assert response.status_code == 400, response.text
        assert "processed data" in response.json()["detail"]


class TestRefinementBaseline:
    async def test_refinement_aligns_to_selected_source_not_global_master(
        self, isolated_db: Database, sample_resume: dict[str, Any]
    ) -> None:
        master_sample = copy.deepcopy(sample_resume)
        master_sample["personalInfo"] = {
            **master_sample["personalInfo"],
            "name": "Master Person",
        }
        await _make_resume(isolated_db, master_sample, is_master=True)

        standalone_sample = copy.deepcopy(sample_resume)
        standalone_sample["personalInfo"] = {
            **standalone_sample["personalInfo"],
            "name": "Standalone Person",
        }
        standalone = await _make_resume(isolated_db, standalone_sample)
        job = await isolated_db.create_job("Senior Backend Engineer at Acme Corp")
        improved = ResumeData.model_validate(
            copy.deepcopy(standalone_sample)
        ).model_dump()

        refine_mock = AsyncMock(
            side_effect=lambda initial_tailored, **_kwargs: RefinementResult(
                refined_data=initial_tailored
            )
        )

        with contextlib.ExitStack() as stack:
            for cm in _tailor_patches(improved, refine_mock=refine_mock):
                stack.enter_context(cm)
            async with _new_client() as client:
                response = await client.post(
                    "/api/v1/resumes/improve/preview",
                    json={
                        "resume_id": standalone["resume_id"],
                        "job_id": job["job_id"],
                    },
                )

        assert response.status_code == 200, response.text
        assert refine_mock.await_count == 1
        baseline = refine_mock.await_args.kwargs["master_resume"]
        assert baseline["personalInfo"]["name"] == "Standalone Person"
        assert baseline["personalInfo"]["name"] != "Master Person"
