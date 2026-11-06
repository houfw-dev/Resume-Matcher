"""Idempotent one-time healer for misfiled award/cert/language items.

Older stored resumes predate the deterministic credential-placement rules:
their ``processed_data`` may still carry 奖项/证书/语言 labels trapped inside
education strings or work/project list descriptions. Reads already heal
in-memory via :func:`normalize_resume_data`, but the stored bytes stay dirty,
so AI paths that read ``processed_data`` directly (fine-tune canonical source,
and later improve/enrichment) worked on the unhealed shape.

This script rewrites stored ``processed_data`` with the current governance
chain. Safe to run repeatedly: a second run heals nothing.

- ``content_type == "json"`` rows get ``content`` re-synced to the healed JSON
  (mirroring the PATCH write path).
- ``content_type == "md"`` rows keep their original ``content`` and
  ``original_markdown`` untouched — the upload text is grounding evidence and
  part of the resume fingerprint.

Standalone runs (defaults to dry-run):

    uv run python -m app.scripts.heal_credential_placement
    uv run python -m app.scripts.heal_credential_placement --apply
"""

import argparse
import asyncio
import copy
import json
import logging
from typing import Any

from app.database import Database, db
from app.schemas.models import normalize_resume_data

logger = logging.getLogger(__name__)


async def heal(
    database: Database | None = None, *, dry_run: bool = True
) -> dict[str, Any]:
    """Normalize every stored resume's structured data in place.

    Returns a stats dict: ``scanned / healed / skipped_clean /
    skipped_no_structured``. With ``dry_run=True`` no row is written.
    """
    database = database or db
    stats: dict[str, Any] = {
        "scanned": 0,
        "healed": 0,
        "skipped_clean": 0,
        "skipped_no_structured": 0,
        "dry_run": dry_run,
    }

    resumes = await database.list_resumes()
    for resume in resumes:
        stats["scanned"] += 1
        resume_id = resume.get("resume_id")
        processed = resume.get("processed_data")
        if not isinstance(processed, dict):
            stats["skipped_no_structured"] += 1
            continue

        before = copy.deepcopy(processed)
        healed_data = normalize_resume_data(copy.deepcopy(processed))
        if before == healed_data:
            stats["skipped_clean"] += 1
            continue

        if dry_run:
            stats["healed"] += 1
            logger.info("[dry-run] would heal resume %s", resume_id)
            continue

        # Mirror PATCH: JSON content re-syncs with the structured payload;
        # markdown upload rows keep content/original_markdown byte-identical.
        updates: dict[str, Any] = {
            "processed_data": healed_data,
            "processing_status": "ready",
        }
        if resume.get("content_type") == "json":
            updates["content"] = json.dumps(healed_data, indent=2)

        await database.update_resume(resume_id, updates)
        stats["healed"] += 1
        logger.info("Healed resume %s", resume_id)

    logger.info("Credential placement heal complete: %s", stats)
    return stats


def main() -> None:
    """Console entry point for a manual run (dry-run by default)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write healed rows; without this flag the run is a dry-run.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(heal(dry_run=not args.apply))
    print(result)


if __name__ == "__main__":
    main()
