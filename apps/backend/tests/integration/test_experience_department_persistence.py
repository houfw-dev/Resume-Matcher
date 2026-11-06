"""department must persist end-to-end through PATCH and GET.

The Pydantic Experience model defaults to ``extra="ignore"``: if
``department`` is not declared, a PATCH still returns 200 but the value is
silently dropped and reads back as None. These tests fail precisely in that
case, guarding against a silently discarded field.
"""

from httpx import ASGITransport, AsyncClient

from app.main import app


def _client() -> AsyncClient:
    """Return a fresh ASGI-in-process client."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_department_persists_through_patch_and_get(isolated_db: object) -> None:
    """A provided department is stored and read back."""
    created = await isolated_db.create_resume(
        content="{}", content_type="json", processed_data={"workExperience": []}
    )
    resume_id = created["resume_id"]
    payload = {
        "workExperience": [
            {
                "id": 1,
                "title": "Java 开发工程师",
                "company": "佰钧成科技有限公司",
                "department": "研发部",
                "years": "2025.06 - 2025.09",
                "description": [],
            }
        ]
    }

    async with _client() as client:
        patched = await client.patch(f"/api/v1/resumes/{resume_id}", json=payload)
        assert patched.status_code == 200
        work = patched.json()["data"]["processed_resume"]["workExperience"]
        assert work[0]["department"] == "研发部"

        fetched = await client.get(
            "/api/v1/resumes", params={"resume_id": resume_id}
        )
        assert fetched.status_code == 200
        read_work = fetched.json()["data"]["processed_resume"]["workExperience"]
        assert read_work[0]["department"] == "研发部"


async def test_department_defaults_to_none_when_absent(isolated_db: object) -> None:
    """Legacy payloads without department read back as None."""
    created = await isolated_db.create_resume(
        content="{}", content_type="json", processed_data={"workExperience": []}
    )
    resume_id = created["resume_id"]
    payload = {
        "workExperience": [
            {
                "id": 1,
                "title": "Java 开发工程师",
                "company": "佰钧成科技有限公司",
                "years": "2025.06 - 2025.09",
                "description": [],
            }
        ]
    }

    async with _client() as client:
        patched = await client.patch(f"/api/v1/resumes/{resume_id}", json=payload)
        assert patched.status_code == 200
        work = patched.json()["data"]["processed_resume"]["workExperience"]
        assert work[0]["department"] is None
