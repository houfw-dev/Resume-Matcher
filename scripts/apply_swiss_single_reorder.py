"""One-time scaffold: apply the swiss-single section reorder for one resume.

Run (backend must be up on :8000, and the resume's Builder tab closed):

    cd apps/backend
    uv run python ../../scripts/apply_swiss_single_reorder.py

It GETs the full ResumeData, writes a timestamped backup, sets the seven
sectionMeta rows (Chinese display names), adds an empty text custom section
``自我评价``, then PATCHes the whole object back. Nothing else is mutated.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:8000/api/v1"
RESUME_ID = "302a8c6e-1279-4a9b-b41f-8a9de5209c54"

# order -> (id=key, displayName, sectionType, isDefault)
SECTION_ROWS: list[tuple[str, str, str, bool]] = [
    ("personalInfo", "基本信息", "personalInfo", True),
    ("education", "教育背景", "itemList", True),
    ("summary", "个人优势", "text", True),
    ("additional", "专业技能", "stringList", True),
    ("workExperience", "工作经历", "itemList", True),
    ("personalProjects", "项目经验", "itemList", True),
]


def build_section_meta(custom_id: str) -> list[dict[str, Any]]:
    """Return the seven ordered sectionMeta rows."""
    rows: list[dict[str, Any]] = [
        {
            "id": key,
            "key": key,
            "displayName": name,
            "sectionType": section_type,
            "isDefault": is_default,
            "isVisible": True,
            "order": order,
        }
        for order, (key, name, section_type, is_default) in enumerate(SECTION_ROWS)
    ]
    rows.append(
        {
            "id": custom_id,
            "key": custom_id,
            "displayName": "自我评价",
            "sectionType": "text",
            "isDefault": False,
            "isVisible": True,
            "order": len(rows),
        }
    )
    return rows


def next_custom_id(custom_sections: dict[str, Any]) -> str:
    """Return the next unused ``custom_N`` id."""
    max_n = 0
    for key in list(custom_sections.keys()):
        if key.startswith("custom_"):
            try:
                max_n = max(max_n, int(key.split("_", 1)[1]))
            except ValueError:
                continue
    return f"custom_{max_n + 1}"


def main() -> None:
    """Apply the scaffold over HTTP."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        response = client.get("/resumes", params={"resume_id": RESUME_ID})
        response.raise_for_status()
        wrapper = response.json()["data"]

        resume_data: dict[str, Any] = wrapper.get("processed_resume")
        if not resume_data:
            resume_data = json.loads(wrapper["raw_resume"]["content"])

        backup_dir = Path("/tmp/rm-resume-backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"{RESUME_ID}-{stamp}.json"
        backup_path.write_text(json.dumps(resume_data, ensure_ascii=False, indent=2))
        print(f"Backup written: {backup_path}")

        custom_sections = dict(resume_data.get("customSections") or {})
        custom_id = next_custom_id(custom_sections)
        custom_sections[custom_id] = {
            "sectionType": "text",
            "items": None,
            "strings": None,
            "text": "",
        }

        resume_data["sectionMeta"] = build_section_meta(custom_id)
        resume_data["customSections"] = custom_sections

        patch = client.patch(f"/resumes/{RESUME_ID}", json=resume_data)
        patch.raise_for_status()
        patched = patch.json()["data"].get("processed_resume") or {}
        names = [s.get("displayName") for s in patched.get("sectionMeta", [])]
        print("New section order:", " => ".join(names))

        verify = client.get("/resumes", params={"resume_id": RESUME_ID})
        verify.raise_for_status()
        verified = verify.json()["data"].get("processed_resume") or {}
        assert len(verified.get("sectionMeta", [])) == 7, "sectionMeta row count mismatch"
        assert custom_id in verified.get("customSections", {}), "self-evaluation section missing"
        print("Verified: 7 sections,", custom_id, "present.")


if __name__ == "__main__":
    main()
