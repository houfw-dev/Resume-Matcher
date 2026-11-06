"""Integration tests for the one-time resume formatting healer script."""

import copy
import json
from typing import Any

import pytest

from app.scripts.heal_resume_formatting import heal


def _formatting_dirty_structured() -> dict[str, Any]:
    return {
        "personalInfo": {"name": " 李四 "},
        "summary": " 五年 java 经验。\n\n",
        "workExperience": [
            {
                "id": 1,
                "title": "java 工程师",
                "company": " Acme ",
                "years": "Jan 2020 - Dec 2023",
                # Blank row carries its OWN style out of alignment; first point
                # is a bullet with a trailing period; the last is plain prose.
                "description": ["负责 spring boot 开发。", " ", "使用 mysql。"],
                "descriptionStyles": ["bullet", "bullet", "plain"],
            }
        ],
        "education": [],
        "personalProjects": [],
        "additional": {
            "technicalSkills": ["java", "mysql"],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {},
    }


def _assert_canonical_format(processed: dict[str, Any]) -> None:
    work = processed["workExperience"][0]
    assert work["years"] == "2020.01~2023.12"
    assert work["title"] == "Java 工程师"
    assert work["company"] == "Acme"
    # Blank row/style dropped in lockstep; bullet ending stripped, plain kept.
    assert work["description"] == ["负责 Spring Boot 开发", "使用 MySQL。"]
    assert work["descriptionStyles"] == ["bullet", "plain"]
    assert processed["additional"]["technicalSkills"] == ["Java", "MySQL"]
    assert processed["summary"] == "五年 Java 经验"


@pytest.mark.asyncio
async def test_dry_run_reports_heals_without_writing(isolated_db: Any) -> None:
    source = _formatting_dirty_structured()
    await isolated_db.create_resume(
        content="# Li Si upload",
        content_type="md",
        processed_data=copy.deepcopy(source),
        processing_status="ready",
        original_markdown="# Li Si upload",
    )

    stats = await heal(isolated_db, dry_run=True)

    assert stats["scanned"] == 1
    assert stats["healed"] == 1
    assert stats["dry_run"] is True
    stored = (await isolated_db.list_resumes())[0]
    assert stored["processed_data"] == source
    assert stored["content"] == "# Li Si upload"


@pytest.mark.asyncio
async def test_apply_heals_md_and_json_rows_without_touching_md_content(
    isolated_db: Any,
) -> None:
    md_row = await isolated_db.create_resume(
        content="# Li Si upload",
        content_type="md",
        processed_data=_formatting_dirty_structured(),
        processing_status="ready",
        original_markdown="# Li Si upload",
    )
    json_row = await isolated_db.create_resume(
        content=json.dumps(_formatting_dirty_structured(), indent=2),
        content_type="json",
        processed_data=_formatting_dirty_structured(),
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
    # Markdown upload text stays byte-identical grounding evidence.
    assert md_stored["content"] == "# Li Si upload"
    assert md_stored["original_markdown"] == "# Li Si upload"
    _assert_canonical_format(md_stored["processed_data"])

    json_stored = await isolated_db.get_resume(json_row["resume_id"])
    _assert_canonical_format(json_stored["processed_data"])
    assert json_stored["content"] == json.dumps(
        json_stored["processed_data"], indent=2
    )


@pytest.mark.asyncio
async def test_heal_is_idempotent(isolated_db: Any) -> None:
    await isolated_db.create_resume(
        content="# Li Si upload",
        content_type="md",
        processed_data=_formatting_dirty_structured(),
        processing_status="ready",
    )

    first = await heal(isolated_db, dry_run=False)
    second = await heal(isolated_db, dry_run=False)

    assert first["healed"] == 1
    assert second["healed"] == 0
    assert second["skipped_clean"] == 1
