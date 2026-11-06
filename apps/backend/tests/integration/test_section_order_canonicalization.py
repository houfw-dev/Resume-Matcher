"""End-to-end section-order governance through PATCH and GET.

Guards the two enforcement points:

* PATCH /resumes/{id} canonicalizes BEFORE storage (backstop for direct API
  clients that do not run the web builder normalization);
* GET /resumes canonicalizes the RESPONSE only — legacy scrambled meta in
  storage is rendered canonically but never rewritten by a read.
"""

import copy

from httpx import ASGITransport, AsyncClient

from app.main import app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _scrambled_payload() -> dict:
    # Deliberately out of order, with a renamed default, an empty optional
    # custom block and a filled unknown custom block.
    return {
        "personalInfo": {"name": "李四", "title": "后端工程师"},
        "summary": "一段有内容的个人优势总结。",
        "education": [
            {"id": 1, "institution": "甲大学", "degree": "统招本科", "years": "2016.09 - 2020.06"}
        ],
        "workExperience": [
            {"id": 1, "company": "戊公司", "title": "开发工程师", "years": "2020.07 至今"}
        ],
        "personalProjects": [{"id": 1, "name": "项目甲", "role": "后端开发"}],
        "additional": {"technicalSkills": ["Java", "MySQL"]},
        "customSections": {
            "custom_hobby": {"sectionType": "text", "text": "长期参与开源社区活动。"},
            "custom_empty": {"sectionType": "text", "text": ""},
        },
        "sectionMeta": [
            {"id": "workExperience", "key": "workExperience", "displayName": "Experience",
             "sectionType": "itemList", "isDefault": True, "isVisible": True, "order": 0},
            {"id": "personalProjects", "key": "personalProjects", "displayName": "Projects",
             "sectionType": "itemList", "isDefault": True, "isVisible": True, "order": 1},
            {"id": "custom_hobby", "key": "custom_hobby", "displayName": "志愿者",
             "sectionType": "text", "isDefault": False, "isVisible": True, "order": 2},
            {"id": "personalInfo", "key": "personalInfo", "displayName": "Personal Info",
             "sectionType": "personalInfo", "isDefault": True, "isVisible": True, "order": 3},
            {"id": "education", "key": "education", "displayName": "Education",
             "sectionType": "itemList", "isDefault": True, "isVisible": True, "order": 4},
            {"id": "custom_empty", "key": "custom_empty", "displayName": "兴趣爱好",
             "sectionType": "text", "isDefault": False, "isVisible": True, "order": 5},
            {"id": "summary", "key": "summary", "displayName": "我的故事",
             "sectionType": "text", "isDefault": True, "isVisible": True, "order": 6},
            {"id": "additional", "key": "additional", "displayName": "Skills & Awards",
             "sectionType": "stringList", "isDefault": True, "isVisible": True, "order": 7},
        ],
    }


EXPECTED_FORMAL_KEYS = [
    "personalInfo",
    "education",
    "summary",
    "additional",
    "workExperience",
    "personalProjects",
    "custom_hobby",
    "custom_empty",
]


async def test_patch_canonicalizes_meta_before_storage(isolated_db: object) -> None:
    created = await isolated_db.create_resume(
        content="{}", content_type="json", processed_data={}
    )
    resume_id = created["resume_id"]

    async with _client() as client:
        resp = await client.patch(f"/api/v1/resumes/{resume_id}", json=_scrambled_payload())
        assert resp.status_code == 200
        response_meta = resp.json()["data"]["processed_resume"]["sectionMeta"]

    # Response: dense formal-branch order.
    assert [m["key"] for m in response_meta] == EXPECTED_FORMAL_KEYS
    assert [m["order"] for m in response_meta] == list(range(len(EXPECTED_FORMAL_KEYS)))
    by_key = {m["key"]: m for m in response_meta}
    assert by_key["summary"]["displayName"] == "Summary"  # renamed default reset
    assert by_key["custom_hobby"]["displayName"] == "志愿者"  # custom name kept
    assert by_key["custom_hobby"]["isVisible"] is True
    assert by_key["custom_empty"]["isVisible"] is False  # empty optional hidden

    # Same canonical shape is persisted.
    stored = await isolated_db.get_resume(resume_id)
    stored_meta = stored["processed_data"]["sectionMeta"]
    assert [m["key"] for m in stored_meta] == EXPECTED_FORMAL_KEYS
    assert [m["order"] for m in stored_meta] == list(range(len(EXPECTED_FORMAL_KEYS)))
    # Empty block is preserved (hidden, not deleted); its content stays blank.
    stored_empty = stored["processed_data"]["customSections"]["custom_empty"]
    assert stored_empty["sectionType"] == "text"
    assert not stored_empty["text"]
    assert stored["processed_data"]["customSections"]["custom_hobby"]["text"] == (
        "长期参与开源社区活动。"
    )


async def test_get_normalizes_response_without_writing_storage(isolated_db: object) -> None:
    created = await isolated_db.create_resume(
        content="{}", content_type="json", processed_data={}
    )
    resume_id = created["resume_id"]

    # Simulate legacy dirty data sitting in storage: other-branch degree,
    # scrambled order, renamed default.
    legacy = _scrambled_payload()
    legacy["education"] = [
        {"id": 1, "institution": "乙大专", "degree": "大专", "years": "2013.09 - 2016.06"}
    ]
    await isolated_db.update_resume(resume_id, {"processed_data": copy.deepcopy(legacy)})

    async with _client() as client:
        first = await client.get("/api/v1/resumes", params={"resume_id": resume_id})
        second = await client.get("/api/v1/resumes", params={"resume_id": resume_id})

    assert first.status_code == 200 and second.status_code == 200
    first_meta = first.json()["data"]["processed_resume"]["sectionMeta"]
    second_meta = second.json()["data"]["processed_resume"]["sectionMeta"]
    # Other-branch order: education sits right before the end; reads are stable.
    expected_other = [
        "personalInfo",
        "summary",
        "additional",
        "workExperience",
        "personalProjects",
        "custom_hobby",
        "custom_empty",
        "education",
    ]
    assert [m["key"] for m in first_meta] == expected_other
    assert first_meta == second_meta

    # The GETs did not rewrite storage: the legacy scrambled meta is intact.
    stored = await isolated_db.get_resume(resume_id)
    assert stored["processed_data"]["sectionMeta"] == legacy["sectionMeta"]
