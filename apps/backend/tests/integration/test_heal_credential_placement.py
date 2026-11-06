"""Integration tests for the one-time credential-placement healer script."""

import copy
import json
from typing import Any

import pytest

from app.scripts.heal_credential_placement import heal


def _misfiled_structured() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Wang Wu"},
        "workExperience": [
            {
                "id": 1,
                "title": "工程师",
                "company": "Acme",
                "years": "2020 - 2024",
                "description": [
                    "负责支付系统开发",
                    "奖项：国家励志奖学金",
                    "语言：英语六级",
                ],
                "descriptionStyles": ["bullet", "bullet", "bullet"],
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


@pytest.mark.asyncio
async def test_dry_run_reports_heals_without_writing(isolated_db: Any) -> None:
    source = _misfiled_structured()
    await isolated_db.create_resume(
        content="# Wang Wu upload",
        content_type="md",
        processed_data=copy.deepcopy(source),
        processing_status="ready",
        original_markdown="# Wang Wu upload",
    )

    stats = await heal(isolated_db, dry_run=True)

    assert stats["scanned"] == 1
    assert stats["healed"] == 1
    assert stats["dry_run"] is True
    stored = (await isolated_db.list_resumes())[0]
    assert stored["processed_data"] == source
    assert stored["content"] == "# Wang Wu upload"


@pytest.mark.asyncio
async def test_apply_heals_md_and_json_rows_without_touching_md_content(
    isolated_db: Any,
) -> None:
    md_source = _misfiled_structured()
    md_row = await isolated_db.create_resume(
        content="# Wang Wu upload",
        content_type="md",
        processed_data=copy.deepcopy(md_source),
        processing_status="ready",
        original_markdown="# Wang Wu upload",
    )
    json_source = _misfiled_structured()
    json_row = await isolated_db.create_resume(
        content=json.dumps(json_source, indent=2),
        content_type="json",
        processed_data=copy.deepcopy(json_source),
        processing_status="ready",
    )
    await isolated_db.create_resume(
        content="pending upload",
        content_type="md",
        processed_data=None,
        processing_status="pending",
    )

    stats = await heal(isolated_db, dry_run=False)

    assert stats["scanned"] == 3
    assert stats["healed"] == 2
    assert stats["skipped_no_structured"] == 1

    md_stored = await isolated_db.get_resume(md_row["resume_id"])
    assert md_stored["content"] == "# Wang Wu upload"
    assert md_stored["original_markdown"] == "# Wang Wu upload"
    md_work = md_stored["processed_data"]["workExperience"][0]
    assert md_work["description"] == ["负责支付系统开发"]
    assert md_work["descriptionStyles"] == ["bullet"]
    assert md_stored["processed_data"]["additional"]["awards"] == ["国家励志奖学金"]
    assert md_stored["processed_data"]["additional"]["languages"] == ["英语六级"]

    json_stored = await isolated_db.get_resume(json_row["resume_id"])
    assert json_stored["content"] == json.dumps(
        json_stored["processed_data"], indent=2
    )
    assert json_stored["processed_data"]["additional"]["awards"] == ["国家励志奖学金"]


@pytest.mark.asyncio
async def test_heal_is_idempotent(isolated_db: Any) -> None:
    await isolated_db.create_resume(
        content="# Wang Wu upload",
        content_type="md",
        processed_data=_misfiled_structured(),
        processing_status="ready",
    )

    first = await heal(isolated_db, dry_run=False)
    second = await heal(isolated_db, dry_run=False)

    assert first["healed"] == 1
    assert second["healed"] == 0
    assert second["skipped_clean"] == 1
