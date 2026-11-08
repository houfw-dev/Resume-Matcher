"""Final AI-output preservation and grounding policy controls."""

import copy
from typing import Any
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from app.schemas.models import ResumeData
from app.services.parser import restore_dates_from_markdown
from app.services.refiner import refine_resume
from app.services.resume_preservation import (
    GROUNDING_REVIEW_CODE,
    approved_preview_project_rows,
    finalize_ai_resume,
    grounding_review_warnings,
    validate_confirmed_resume,
)
from app.schemas.refinement import RefinementConfig
from app.routers import resumes


def _source_resume() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "Ada Lovelace", "email": "ada@example.com"},
        "summary": "Backend engineer building Python services.",
        "workExperience": [
            {
                "id": 1,
                "title": "Engineer",
                "company": "Alpha",
                "years": "Jan 2020 - Mar 2021",
                "description": ["Built Python APIs", "Documented releases"],
                "descriptionStyles": ["plain", "bullet"],
            },
            {
                "id": 2,
                "title": "Lead",
                "company": "Beta",
                "years": "Apr 2020 - Dec 2021",
                "description": ["Led service migrations"],
                "descriptionStyles": ["bullet"],
            },
        ],
        "education": [
            {
                "id": 4,
                "institution": "Example University",
                "degree": "BSc",
                "years": "2016 - 2020",
                "description": "Computer science",
            }
        ],
        "personalProjects": [
            {
                "id": 7,
                "name": "Parser",
                "role": "Maintainer",
                "years": "May 2021 - Present",
                "description": ["Parsed documents"],
                "descriptionStyles": ["plain"],
            }
        ],
        "additional": {
            "technicalSkills": ["Python"],
            "languages": ["English"],
            "certificationsTraining": [],
            "awards": [],
        },
        "customSections": {
            "talks": {
                "sectionType": "itemList",
                "items": [
                    {
                        "id": 9,
                        "title": "Reliable systems",
                        "subtitle": "PyCon",
                        "years": "Jun 2023",
                        "description": ["Presented testing methods"],
                        "descriptionStyles": ["plain"],
                    }
                ],
            }
        },
    }


def test_final_writer_cannot_erase_populated_source_sections() -> None:
    source = _source_resume()
    partial = {
        "personalInfo": copy.deepcopy(source["personalInfo"]),
        "summary": "Python backend engineer.",
    }

    finalized = finalize_ai_resume(source, partial)

    assert finalized["summary"] == "Python backend engineer."
    for section in (
        "workExperience",
        "education",
        "personalProjects",
        "customSections",
    ):
        assert finalized[section] == source[section]


def test_reordered_entries_keep_their_identity_dates_and_styles() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"] = [
        {
            **copy.deepcopy(source["workExperience"][1]),
            "years": "2020 - 2021",
            "description": ["Led migrations of services"],
            "descriptionStyles": [],
        },
        {
            **copy.deepcopy(source["workExperience"][0]),
            "years": "2020 - 2021",
            "description": [
                "Built scalable Python APIs",
                "Documented release processes",
            ],
            "descriptionStyles": [],
        },
    ]

    finalized = finalize_ai_resume(source, candidate)

    assert [entry["id"] for entry in finalized["workExperience"]] == [2, 1]
    assert finalized["workExperience"][0]["years"] == "Apr 2020 - Dec 2021"
    assert finalized["workExperience"][0]["descriptionStyles"] == ["bullet"]
    assert finalized["workExperience"][1]["years"] == "Jan 2020 - Mar 2021"
    assert finalized["workExperience"][1]["descriptionStyles"] == ["plain", "bullet"]


def test_reordered_description_rows_remain_confirmable_with_bound_styles() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [
        "Documented release processes",
        "Built scalable Python APIs",
    ]
    candidate["workExperience"][0]["descriptionStyles"] = []

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["descriptionStyles"] == ["bullet", "plain"]
    assert validate_confirmed_resume(source, finalized) == []


def test_missing_model_id_falls_back_to_entry_identity() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate_entry = candidate["workExperience"][0]
    candidate_entry.pop("id")
    candidate_entry["years"] = "2020 - 2021"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["id"] == 1
    assert finalized["workExperience"][0]["years"] == "Jan 2020 - Mar 2021"


def test_format_only_education_date_rewrite_is_kept() -> None:
    # The user asked the model to render dates as yyyy.MM; the candidate keeps
    # the exact same date points in a different presentation. This is the
    # "2016 年 06 月 - 2020 年 09 月 -> 2016.06 - 2020.09" report.
    source = _source_resume()
    source["education"] = [
        {
            "id": 4,
            "institution": "Example University",
            "degree": "BSc",
            "years": "2016 年 06 月 - 2020 年 09 月",
            "description": "Computer science",
        }
    ]
    candidate = copy.deepcopy(source)
    candidate["education"][0]["years"] = "2016.06 - 2020.09"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["education"][0]["years"] == "2016.06 - 2020.09"
    assert validate_confirmed_resume(source, finalized) == []


def test_format_only_date_rewrite_works_across_sections_and_present_marker() -> None:
    source = _source_resume()
    source["workExperience"][0]["years"] = "2021 年 09 月 - 2026 年 07 月"
    source["personalProjects"][0]["years"] = "2025 年 01 月 - 至今"
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["years"] = "2021.09 - 2026.07"
    candidate["personalProjects"][0]["years"] = "2025.01 - Present"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["years"] == "2021.09 - 2026.07"
    assert finalized["personalProjects"][0]["years"] == "2025.01 - Present"
    assert validate_confirmed_resume(source, finalized) == []


def test_english_to_numeric_date_format_change_is_kept() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["years"] = "2020.01 - 2021.03"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["years"] == "2020.01 - 2021.03"
    assert validate_confirmed_resume(source, finalized) == []


def test_real_date_change_is_still_reverted_and_flagged() -> None:
    source = _source_resume()
    source["education"][0]["years"] = "2016.06 - 2020.09"
    candidate = copy.deepcopy(source)
    candidate["education"][0]["years"] = "2017.09 - 2021.06"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["education"][0]["years"] == "2016.06 - 2020.09"
    assert "education.identity" in validate_confirmed_resume(source, candidate)


def test_month_precision_loss_in_date_rewrite_is_reverted() -> None:
    source = _source_resume()
    source["education"][0]["years"] = "2016.06 - 2020.09"
    candidate = copy.deepcopy(source)
    candidate["education"][0]["years"] = "2016 - 2020"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["education"][0]["years"] == "2016.06 - 2020.09"
    assert "education.identity" in validate_confirmed_resume(source, candidate)


def test_invented_month_precision_in_date_rewrite_is_reverted() -> None:
    source = _source_resume()
    source["education"][0]["years"] = "2016 - 2020"
    candidate = copy.deepcopy(source)
    candidate["education"][0]["years"] = "2016.06 - 2020.09"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["education"][0]["years"] == "2016 - 2020"
    assert "education.identity" in validate_confirmed_resume(source, candidate)


def test_present_marker_mismatch_in_date_rewrite_is_reverted() -> None:
    source = _source_resume()
    source["workExperience"][0]["years"] = "2021.09 - 至今"
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["years"] = "2021.09 - 2026.07"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["years"] == "2021.09 - 至今"
    assert "workExperience.identity" in validate_confirmed_resume(source, candidate)


def test_style_edit_plain_to_bullet_honoured_only_when_enabled() -> None:
    # Explicit "render these paragraphs as an ordered list" request: the
    # candidate keeps the texts byte-for-byte and only flips plain -> bullet.
    source = _source_resume()
    source["workExperience"][0]["descriptionStyles"] = ["plain", "plain"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["descriptionStyles"] = ["bullet", "bullet"]

    enabled = finalize_ai_resume(source, candidate, allow_style_edits=True)
    assert enabled["workExperience"][0]["description"] == source["workExperience"][0][
        "description"
    ]
    assert enabled["workExperience"][0]["descriptionStyles"] == ["bullet", "bullet"]

    # Every other flow (improve, parse repair, refine) stays byte-identical.
    default = finalize_ai_resume(source, candidate)
    assert default["workExperience"][0]["descriptionStyles"] == ["plain", "plain"]


def test_style_edit_bullet_to_plain_also_honoured() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][1]["descriptionStyles"] = ["plain"]

    finalized = finalize_ai_resume(source, candidate, allow_style_edits=True)
    assert finalized["workExperience"][1]["descriptionStyles"] == ["plain"]


def test_style_edit_never_accepts_label_from_candidate() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["descriptionStyles"] = ["label", "label"]

    finalized = finalize_ai_resume(source, candidate, allow_style_edits=True)
    assert finalized["workExperience"][0]["descriptionStyles"] == ["plain", "bullet"]


def test_style_edit_ignored_when_candidate_arrays_are_misaligned() -> None:
    source = _source_resume()
    source["workExperience"][0]["descriptionStyles"] = ["plain", "plain"]

    # One raw row contains an embedded newline: after normalization it becomes
    # two rows, so row/style indices no longer line up one-to-one.
    split_candidate = copy.deepcopy(source)
    split_candidate["workExperience"][0]["description"] = [
        "Built Python APIs\nwith care",
        "Documented releases",
    ]
    split_candidate["workExperience"][0]["descriptionStyles"] = ["bullet", "bullet"]
    split_final = finalize_ai_resume(
        source, split_candidate, allow_style_edits=True
    )
    assert split_final["workExperience"][0]["descriptionStyles"] == ["plain", "plain"]

    # Styles array missing / wrong length entirely.
    no_styles = copy.deepcopy(source)
    no_styles["workExperience"][0]["descriptionStyles"] = ["bullet"]
    no_styles_final = finalize_ai_resume(
        source, no_styles, allow_style_edits=True
    )
    assert no_styles_final["workExperience"][0]["descriptionStyles"] == [
        "plain",
        "plain",
    ]


def test_style_edit_skipped_on_rows_whose_text_was_restored() -> None:
    source = _source_resume()
    source["workExperience"][0]["descriptionStyles"] = ["plain", "plain"]
    candidate = copy.deepcopy(source)
    # Novel, ungrounded metric forces the source row text to be restored; the
    # style flip on that row must be reverted with it.
    candidate["workExperience"][0]["description"] = [
        "Built Python APIs serving 9000 requests",
        "Documented releases",
    ]
    candidate["workExperience"][0]["descriptionStyles"] = ["bullet", "bullet"]

    finalized = finalize_ai_resume(source, candidate, allow_style_edits=True)
    assert finalized["workExperience"][0]["description"][0] == "Built Python APIs"
    assert finalized["workExperience"][0]["descriptionStyles"] == ["plain", "bullet"]


def test_style_edit_threads_into_custom_section_items() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["customSections"]["talks"]["items"][0]["descriptionStyles"] = ["bullet"]

    finalized = finalize_ai_resume(source, candidate, allow_style_edits=True)
    assert finalized["customSections"]["talks"]["items"][0]["descriptionStyles"] == [
        "bullet"
    ]
    assert finalize_ai_resume(source, candidate)["customSections"]["talks"]["items"][
        0
    ]["descriptionStyles"] == ["plain"]


async def test_real_refiner_final_writer_restores_partial_sections() -> None:
    source = _source_resume()
    master = copy.deepcopy(source)
    master["additional"]["technicalSkills"].append("Kubernetes")
    partial = {
        "personalInfo": copy.deepcopy(source["personalInfo"]),
        "summary": "Kubernetes backend engineer.",
    }

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=partial,
    ):
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )

    assert result.refined_data["summary"] == "Kubernetes backend engineer."
    for section in (
        "workExperience",
        "education",
        "personalProjects",
        "customSections",
    ):
        assert result.refined_data[section] == source[section]


async def test_real_refiner_binds_styles_to_reordered_entry_identity() -> None:
    source = _source_resume()
    master = copy.deepcopy(source)
    master["additional"]["technicalSkills"].append("Kubernetes")
    candidate = copy.deepcopy(source)
    candidate["summary"] = "Kubernetes backend engineer."
    candidate["workExperience"] = [
        {
            **copy.deepcopy(source["workExperience"][1]),
            "description": ["Led migrations of services"],
            "descriptionStyles": [],
        },
        {
            **copy.deepcopy(source["workExperience"][0]),
            "description": ["Built scalable Python APIs", "Documented releases"],
            "descriptionStyles": [],
        },
    ]

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=candidate,
    ):
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={
                "required_skills": ["Kubernetes"],
                "preferred_skills": [],
                "keywords": [],
            },
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=True,
            ),
        )

    assert [entry["id"] for entry in result.refined_data["workExperience"]] == [
        2,
        1,
    ]
    assert result.refined_data["workExperience"][0]["descriptionStyles"] == ["bullet"]
    assert result.refined_data["workExperience"][1]["descriptionStyles"] == [
        "plain",
        "bullet",
    ]


async def test_restored_unsafe_writer_attempt_is_not_counted_as_applied() -> None:
    source = _source_resume()
    master = copy.deepcopy(source)
    master["additional"]["technicalSkills"].append("Kubernetes")
    partial = {
        "personalInfo": copy.deepcopy(source["personalInfo"]),
        "summary": source["summary"],
    }

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=partial,
    ) as writer:
        result = await refine_resume(
            initial_tailored=source,
            master_resume=master,
            job_description="Backend role requiring Kubernetes",
            job_keywords={"required_skills": ["Kubernetes"]},
            config=RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=False,
            ),
        )

    assert writer.await_count == 1
    assert result.passes_attempted == 1
    assert result.passes_completed == 0
    assert result.refined_data == source


def test_confirm_validation_allows_reorder_but_rejects_loss_and_identity_drift() -> (
    None
):
    source = _source_resume()
    reordered = copy.deepcopy(source)
    reordered["workExperience"].reverse()
    assert validate_confirmed_resume(source, reordered) == []

    missing = copy.deepcopy(source)
    missing["workExperience"] = []
    assert "workExperience.entries" in validate_confirmed_resume(source, missing)

    mutated = copy.deepcopy(source)
    mutated["workExperience"][0]["company"] = "Moon Base"
    assert "workExperience.identity" in validate_confirmed_resume(source, mutated)

    custom_mutated = copy.deepcopy(source)
    custom_mutated["customSections"]["talks"]["items"][0]["years"] = "2024"
    assert "customSections.talks.identity" in validate_confirmed_resume(
        source, custom_mutated
    )


def test_confirm_accepts_schema_defaults_absent_from_legacy_source() -> None:
    source = _source_resume()
    source["workExperience"][0].pop("id")
    source["workExperience"][0].pop("descriptionStyles")
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["id"] = 0
    candidate["workExperience"][0]["descriptionStyles"] = ["bullet", "bullet"]

    assert validate_confirmed_resume(source, candidate) == []


def test_verified_jd_skill_addition_remains_while_original_lists_are_preserved() -> (
    None
):
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["additional"]["technicalSkills"] = ["Kubernetes"]

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["additional"]["technicalSkills"] == ["Kubernetes", "Python"]
    assert validate_confirmed_resume(source, finalized) == []


def test_new_metrics_require_source_evidence_but_legitimate_rephrasing_remains() -> (
    None
):
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [
        "Built scalable Python APIs",
        "Managed 800 people",
    ]

    finalized = finalize_ai_resume(source, candidate)

    assert (
        finalized["workExperience"][0]["description"][0] == "Built scalable Python APIs"
    )
    assert finalized["workExperience"][0]["description"][1] == "Documented releases"


def test_equivalent_metric_notation_remains_editable() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"][
        0
    ] = "Handled 50K requests with 40% fewer errors"
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][
        0
    ] = "Handled 50 thousand requests with 40 percent fewer errors"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["description"][0] == (
        "Handled 50 thousand requests with 40 percent fewer errors"
    )


def test_metric_multiplicity_and_glued_units_are_grounded() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"][0] = "Reduced latency by 10%"
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][0] = (
        "Reduced 10% latency and added another 10% improvement"
    )
    candidate["workExperience"][0]["description"][1] = "Reduced latency by 5ms"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["description"] == [
        "Reduced latency by 10%",
        "Documented releases",
    ]


def test_versions_years_and_equivalent_scaled_counts_are_not_novel_metrics() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"][0] = "Served 1,000,000 users"
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][0] = (
        "Served 1 million users with Python 3.9 in 2021"
    )

    finalized = finalize_ai_resume(source, candidate)

    assert "1 million" in finalized["workExperience"][0]["description"][0]


@pytest.mark.parametrize(
    ("source_row", "candidate_row"),
    [
        ("Migrated 150 servers", "Migrated 2000 servers"),
        ("Managed systems in 150 stores", "Managed systems in 2000 stores"),
    ],
    ids=["plain-count", "count-after-preposition"],
)
def test_count_in_year_range_is_not_mistaken_for_a_date(
    source_row: str,
    candidate_row: str,
) -> None:
    source = _source_resume()
    source["workExperience"][0]["description"][0] = source_row
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][0] = candidate_row

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["description"][0] == source_row


@pytest.mark.parametrize(
    ("source_row", "candidate_row"),
    [
        (
            "Reduced deployment time",
            "Reduced deployment time by automating release pipelines across EMEA",
        ),
        (
            "Built auth for five services and integrated SSO",
            "Built auth for services",
        ),
    ],
    ids=["unsupported-expansion", "unsupported-truncation"],
)
def test_subset_rewrite_is_restored_or_flagged_for_review(
    source_row: str,
    candidate_row: str,
) -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = [source_row]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [candidate_row]

    strict = finalize_ai_resume(source, candidate, allow_review_claims=False)
    preview = finalize_ai_resume(source, candidate, allow_review_claims=True)

    assert strict["workExperience"][0]["description"] == [source_row]
    assert grounding_review_warnings(source, preview) == [
        f"{GROUNDING_REVIEW_CODE}: Review workExperience[0].description[0] against the source resume."
    ]


def test_moderate_grounded_expansion_remains_editable_without_warning() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = ["Built Python APIs"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["Built scalable Python APIs"]

    finalized = finalize_ai_resume(source, candidate, allow_review_claims=False)

    assert finalized["workExperience"][0]["description"] == [
        "Built scalable Python APIs"
    ]
    assert grounding_review_warnings(source, finalized) == []


def test_restorable_reordered_metric_consumes_its_matched_source_row() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = [
        "Led team of 5 engineers",
        "Built REST API",
        "Reduced costs by 10%",
    ]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"] * 3
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [
        "Reduced costs by 15%",
        "Built REST API",
        "Led team of 5 engineers",
    ]

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["description"] == [
        "Reduced costs by 10%",
        "Built REST API",
        "Led team of 5 engineers",
    ]


def test_candidate_rows_are_normalized_before_the_confirmation_contract() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [
        "Built Python APIs\nDeployed to AWS",
        "•",
    ]

    finalized = finalize_ai_resume(source, candidate)
    round_tripped = ResumeData.model_validate(finalized).model_dump(mode="json")

    assert len(round_tripped["workExperience"][0]["description"]) == 2
    assert validate_confirmed_resume(source, round_tripped) == []


def test_verified_append_can_survive_finalization() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"].append(
        "Added a grounded verified improvement"
    )

    finalized = finalize_ai_resume(source, candidate, allow_appended_rows=True)

    assert finalized["workExperience"][0]["description"][-1] == (
        "Added a grounded verified improvement"
    )


def test_ungrounded_preview_append_receives_review_warning() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"].append(
        "Spearheaded an industry consortium on resume parsing"
    )

    finalized = finalize_ai_resume(source, candidate, allow_appended_rows=True)

    assert finalized["workExperience"][0]["description"][-1] == (
        "Spearheaded an industry consortium on resume parsing"
    )
    assert grounding_review_warnings(source, finalized) == [
        f"{GROUNDING_REVIEW_CODE}: Review workExperience[0].description[2] against the source resume."
    ]


def test_direct_flow_drops_unreviewed_ungrounded_append() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"].append(
        "Commanded unrelated lunar expeditions"
    )

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
    )

    assert finalized["workExperience"][0]["description"] == source["workExperience"][0][
        "description"
    ]


def test_education_without_source_narrative_rejects_candidate_narrative() -> None:
    source = _source_resume()
    source["education"][0]["description"] = None
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = "Invented honors"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["education"][0]["description"] is None


def test_blank_education_narrative_restores_source() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = " "

    assert finalize_ai_resume(source, candidate)["education"][0]["description"] == (
        "Computer science"
    )


def test_confirm_rejects_extra_non_skill_credentials() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["additional"]["languages"].append("Klingon")

    assert "additional.languages" in validate_confirmed_resume(source, candidate)


def test_duplicate_entry_identity_uses_description_to_keep_both_rewrites() -> None:
    source = _source_resume()
    duplicate = copy.deepcopy(source["workExperience"][0])
    duplicate["id"] = 3
    duplicate["description"] = ["Maintained data pipelines"]
    duplicate["descriptionStyles"] = ["bullet"]
    source["workExperience"].append(duplicate)
    candidate = copy.deepcopy(source)
    for entry in candidate["workExperience"]:
        entry.pop("id", None)
    candidate["workExperience"][0]["description"] = ["Built reliable Python APIs"]
    candidate["workExperience"][2]["description"] = ["Maintained ETL pipelines"]

    finalized = finalize_ai_resume(source, candidate)

    assert len(finalized["workExperience"]) == 3
    assert {entry["id"] for entry in finalized["workExperience"]} == {1, 2, 3}


def test_confirm_accepts_reordered_entries_with_duplicate_field_identity() -> None:
    source = _source_resume()
    first = source["workExperience"][0]
    first.pop("id")
    duplicate = copy.deepcopy(first)
    duplicate["years"] = "Apr 2021 - Dec 2023"
    duplicate["description"] = ["Maintained data pipelines"]
    duplicate["descriptionStyles"] = ["plain"]
    source["workExperience"] = [first, duplicate]
    candidate = copy.deepcopy(source)
    candidate["workExperience"].reverse()

    finalized = finalize_ai_resume(source, candidate)

    assert [entry["years"] for entry in finalized["workExperience"]] == [
        "Apr 2021 - Dec 2023",
        "Jan 2020 - Mar 2021",
    ]
    assert validate_confirmed_resume(source, finalized) == []


async def test_refiner_rolls_back_malformed_nested_writer_output() -> None:
    source = _source_resume()
    master = copy.deepcopy(source)
    master["additional"]["technicalSkills"].append("Kubernetes")
    malformed = copy.deepcopy(source)
    malformed["additional"]["languages"] = None

    with patch(
        "app.services.refiner.complete_json",
        new_callable=AsyncMock,
        return_value=malformed,
    ):
        result = await refine_resume(
            source,
            master,
            "Kubernetes role",
            {"required_skills": ["Kubernetes"]},
            RefinementConfig(
                enable_keyword_injection=True,
                enable_ai_phrase_removal=False,
                enable_master_alignment_check=False,
            ),
        )

    assert result.refined_data == source


def test_ats_score_uses_post_preservation_resume_match() -> None:
    ats_payload = {
        "overall_score": 25.0,
        "sub_scores": {
            "keyword_match": 25.0,
            "experience_alignment": 0.0,
            "skills_coverage": 0.0,
            "education_fit": 0.0,
            "format_quality": 0.0,
        },
        "missing_keywords": [],
        "injectable_keywords": [],
        "recommendations": [],
    }
    with (
        patch("app.routers.resumes.calculate_keyword_match", return_value=25.0),
        patch("app.routers.resumes.compute_ats_score", return_value=ats_payload) as score,
    ):
        resumes._build_ats_score(
            {"summary": "Finalized"},
            {"keywords": ["Python"]},
            SimpleNamespace(
                final_match_percentage=99.0,
                keyword_analysis=None,
            ),
            True,
        )

    assert score.call_args.kwargs["keyword_match_percentage"] == 25.0


def test_weakly_grounded_narrative_gets_stable_review_warning() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][0] = "Owned moon missions"

    warnings = grounding_review_warnings(source, candidate)

    assert warnings == [
        f"{GROUNDING_REVIEW_CODE}: Review workExperience[0].description[0] against the source resume."
    ]


def test_metric_present_only_in_extra_evidence_survives_without_warning() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = ["Managed the support team"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["Managed a team of 800 people"]

    without_evidence = finalize_ai_resume(source, candidate)
    assert without_evidence["workExperience"][0]["description"] == [
        "Managed the support team"
    ]

    evidence = "Work history: managed a team of 800 people across two regions."
    with_evidence = finalize_ai_resume(source, candidate, extra_evidence=evidence)

    assert with_evidence["workExperience"][0]["description"] == [
        "Managed a team of 800 people"
    ]
    assert grounding_review_warnings(source, with_evidence, extra_evidence=evidence) == []


def test_metric_absent_from_both_source_and_evidence_is_still_reverted() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = ["Managed the support team"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["Managed 900 people"]
    evidence = "Earlier notes mention managing teams but never a headcount."

    finalized = finalize_ai_resume(source, candidate, extra_evidence=evidence)

    assert finalized["workExperience"][0]["description"] == [
        "Managed the support team"
    ]


def test_extra_evidence_grounds_strict_flow_appended_row() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = ["Ran daily operations"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"].append(
        "Shipped weekly releases to 800 stores"
    )
    evidence = "Also shipped weekly releases to 800 stores nationwide."

    dropped = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
    )
    restored = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
        extra_evidence=evidence,
    )

    assert dropped["workExperience"][0]["description"] == ["Ran daily operations"]
    assert restored["workExperience"][0]["description"] == [
        "Ran daily operations",
        "Shipped weekly releases to 800 stores",
    ]


def test_extra_evidence_token_coverage_controls_review_warnings() -> None:
    source = _source_resume()
    source["workExperience"][0]["description"] = ["Ran platform operations"]
    source["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["Owned moon missions"]
    evidence_without_grounding = "Experience mentions orbital satellites and rockets."
    evidence_with_grounding = "Previously owned moon missions for the agency."

    partially = finalize_ai_resume(
        source, candidate, extra_evidence=evidence_without_grounding
    )
    fully = finalize_ai_resume(source, candidate, extra_evidence=evidence_with_grounding)

    assert grounding_review_warnings(
        source, partially, extra_evidence=evidence_without_grounding
    ) == [
        f"{GROUNDING_REVIEW_CODE}: Review workExperience[0].description[0] against the source resume."
    ]
    assert (
        grounding_review_warnings(source, fully, extra_evidence=evidence_with_grounding)
        == []
    )


def test_summary_metric_restored_from_evidence() -> None:
    source = _source_resume()
    source["summary"] = "Engineering manager with platform experience."
    candidate = copy.deepcopy(source)
    candidate["summary"] = "Engineering manager leading 800 engineers."
    evidence = "I currently lead 800 engineers across platform teams."

    finalized = finalize_ai_resume(source, candidate, extra_evidence=evidence)

    assert finalized["summary"] == "Engineering manager leading 800 engineers."


def test_blank_extra_evidence_matches_default_policy() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = [
        "Built scalable Python APIs",
        "Managed 800 people",
    ]

    assert finalize_ai_resume(source, candidate, extra_evidence="") == finalize_ai_resume(
        source, candidate
    )
    assert grounding_review_warnings(
        source, candidate, extra_evidence=None
    ) == grounding_review_warnings(source, candidate)


def test_custom_item_claims_use_the_same_grounding_policy() -> None:
    source = _source_resume()
    candidate = copy.deepcopy(source)
    candidate["customSections"]["talks"]["items"][0]["description"][
        0
    ] = "Commanded lunar expeditions"

    warnings = grounding_review_warnings(source, candidate)

    assert warnings == [
        f"{GROUNDING_REVIEW_CODE}: Review customSections.talks.items[0].description[0] against the source resume."
    ]


def test_date_restoration_matches_same_year_roles_by_context() -> None:
    parsed = {
        "workExperience": [
            {"title": "Engineer", "company": "Alpha", "years": "2020 - 2021"},
            {"title": "Lead", "company": "Beta", "years": "2020 - 2021"},
        ]
    }
    markdown = """## Experience
Engineer — Alpha | Jan 2020 - Mar 2021
Lead — Beta | Apr 2020 - Dec 2021
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "Jan 2020 - Mar 2021"
    assert result["workExperience"][1]["years"] == "Apr 2020 - Dec 2021"


def test_date_restoration_uses_nearby_identity_for_date_only_lines() -> None:
    parsed = {
        "workExperience": [
            {"title": "Engineer", "company": "Alpha", "years": "2020 - 2021"},
            {"title": "Lead", "company": "Beta", "years": "2020 - 2021"},
        ]
    }
    markdown = """Engineer — Alpha
Jan 2020 - Mar 2021
Lead — Beta
Apr 2020 - Dec 2021
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "Jan 2020 - Mar 2021"
    assert result["workExperience"][1]["years"] == "Apr 2020 - Dec 2021"


def test_date_restoration_preserves_ambiguous_collision() -> None:
    parsed = {"workExperience": [{"title": "Engineer", "years": "2020 - 2021"}]}
    markdown = "Jan 2020 - Mar 2021\nApr 2020 - Dec 2021"

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "2020 - 2021"


def test_date_restoration_handles_present_current_and_cross_section_context() -> None:
    parsed = {
        "workExperience": [
            {"company": "Alpha", "title": "Engineer", "years": "2021 - Present"}
        ],
        "personalProjects": [
            {"name": "Parser", "role": "Maintainer", "years": "2021 - Present"}
        ],
    }
    markdown = """Engineer — Alpha | Jan 2021 - Current
Parser — Maintainer | May 2021 - Present
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "Jan 2021 - Current"
    assert result["personalProjects"][0]["years"] == "May 2021 - Present"


def test_full_month_name_is_already_precise() -> None:
    parsed = {
        "workExperience": [
            {"company": "Alpha", "title": "Engineer", "years": "January 2020 - Current"}
        ]
    }

    result = restore_dates_from_markdown(parsed, "Alpha | Feb 2020 - Present")

    assert result["workExperience"][0]["years"] == "January 2020 - Current"


def test_single_occurrence_requires_matching_identity_across_sections() -> None:
    parsed = {
        "workExperience": [
            {
                "company": "Example University",
                "title": "Research Intern",
                "years": "2020 - 2021",
            }
        ],
        "education": [
            {
                "institution": "Example University",
                "degree": "BSc",
                "years": "2020 - 2021",
            }
        ],
    }
    markdown = "## Education\nExample University — BSc\nJan 2020 - Dec 2021"

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "2020 - 2021"
    assert result["education"][0]["years"] == "Jan 2020 - Dec 2021"


def test_single_year_range_and_wide_normalized_context_restore() -> None:
    parsed = {
        "workExperience": [
            {"company": "Alpha Labs", "title": "Engineer", "years": "2020"}
        ]
    }
    markdown = """Engineer  —  Alpha Labs
- Built APIs
- Shipped services
- Mentored peers
Jan 2020 - Dec 2020
"""

    result = restore_dates_from_markdown(parsed, markdown)

    assert result["workExperience"][0]["years"] == "Jan 2020 - Dec 2020"

# --- Fine-tune: award-level guards and cross-section relocation -----------


def _relocation_source() -> dict[str, Any]:
    return {
        "personalInfo": {"name": "A Student"},
        "summary": "",
        "workExperience": [
            {
                "id": 1,
                "title": "Intern",
                "company": "Acme",
                "years": "2020",
                "description": ["获校二等奖学金", "编写内部工具"],
                "descriptionStyles": ["bullet", "bullet"],
            }
        ],
        "education": [
            {
                "id": 2,
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


def test_rank_swap_in_description_row_is_reverted() -> None:
    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"][0] = "获校三等奖学金"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["workExperience"][0]["description"][0] == "获校二等奖学金"


def test_rank_swap_in_education_string_is_reverted() -> None:
    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = candidate["education"][0][
        "description"
    ].replace("校二等奖", "校三等奖")

    finalized = finalize_ai_resume(source, candidate)

    assert "校二等奖" in finalized["education"][0]["description"]
    assert "校三等奖" not in finalized["education"][0]["description"]


def test_rank_swap_in_summary_is_reverted() -> None:
    source = _relocation_source()
    source["summary"] = "获校二等奖学金的工程师。"
    candidate = copy.deepcopy(source)
    candidate["summary"] = "获校三等奖学金的工程师。"

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["summary"] == "获校二等奖学金的工程师。"


def test_deleting_a_rank_line_is_not_a_mutation() -> None:
    from app.services.resume_preservation import _rank_mutated

    assert _rank_mutated("获二等奖", "获三等奖") is True  # level changed
    assert _rank_mutated("无等级声明", "获三等奖") is True  # level invented
    assert _rank_mutated("获二等奖", "专业：计算机科学") is False  # line removed


def test_relocation_moves_education_awards_and_certificates_into_additional() -> None:
    from app.services.fine_tune import build_grounding_evidence

    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = "专业：计算机科学与技术"
    candidate["additional"]["awards"] = ["国家励志奖学金", "校二等奖"]
    candidate["additional"]["certificationsTraining"] = ["PMP项目管理证书"]

    evidence = build_grounding_evidence(source, "")
    finalized = finalize_ai_resume(
        source, candidate, extra_evidence=evidence, allow_relocation=True
    )

    awards = finalized["additional"]["awards"]
    certs = finalized["additional"]["certificationsTraining"]
    assert "国家励志奖学金" in awards and "校二等奖" in awards
    assert "PMP项目管理证书" in certs
    education_text = finalized["education"][0]["description"]
    assert "奖项" not in education_text and "证书" not in education_text
    assert "计算机科学与技术" in education_text


def test_relocation_without_flag_keeps_legacy_list_policy() -> None:
    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["additional"]["awards"] = ["国家励志奖学金"]

    finalized = finalize_ai_resume(source, candidate)

    assert finalized["additional"]["awards"] == []


def test_unevidenced_relocation_item_is_dropped_but_grounded_one_kept() -> None:
    from app.services.fine_tune import build_grounding_evidence

    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["education"][0]["description"] = "专业：计算机科学与技术"
    candidate["additional"]["awards"] = ["国家励志奖学金", "虚构的全球特等奖"]

    evidence = build_grounding_evidence(source, "")
    finalized = finalize_ai_resume(
        source, candidate, extra_evidence=evidence, allow_relocation=True
    )

    awards = finalized["additional"]["awards"]
    assert "国家励志奖学金" in awards
    assert "虚构的全球特等奖" not in awards


def test_relocated_work_description_row_is_dropped_from_original_entry() -> None:
    from app.services.fine_tune import build_grounding_evidence

    source = _relocation_source()
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["编写内部工具"]
    candidate["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate["additional"]["awards"] = ["获校二等奖学金"]

    evidence = build_grounding_evidence(source, "")
    finalized = finalize_ai_resume(
        source, candidate, extra_evidence=evidence, allow_relocation=True
    )

    descriptions = finalized["workExperience"][0]["description"]
    assert descriptions == ["编写内部工具"]
    assert finalized["workExperience"][0]["descriptionStyles"] == ["bullet"]
    assert "获校二等奖学金" in finalized["additional"]["awards"]


def test_partially_covered_row_is_kept_not_dropped() -> None:
    from app.services.fine_tune import build_grounding_evidence

    source = _relocation_source()
    source["workExperience"][0]["description"] = ["国家奖学金、PMP证书", "编写内部工具"]
    candidate = copy.deepcopy(source)
    candidate["workExperience"][0]["description"] = ["编写内部工具"]
    candidate["workExperience"][0]["descriptionStyles"] = ["bullet"]
    candidate["additional"]["awards"] = ["国家奖学金"]

    evidence = build_grounding_evidence(source, "")
    finalized = finalize_ai_resume(
        source, candidate, extra_evidence=evidence, allow_relocation=True
    )

    descriptions = finalized["workExperience"][0]["description"]
    assert "国家奖学金、PMP证书" in descriptions  # too little covered -> kept


def _labeled_project_source() -> dict[str, Any]:
    """A project shaped by the parser: label/body regions + bullet regions."""
    source = _source_resume()
    source["personalProjects"] = [
        {
            "id": 7,
            "name": "ChaoLu Fitness",
            "role": "Backend lead",
            "years": "2022 - 2026",
            "description": [
                "技术栈：",
                "Java",
                "Redis",
                "项目背景：",
                "A digital platform for chain gyms.",
                "项目职责：",
                "Owned backend design of core modules.",
                "项目亮点：",
                "Cut core API latency by 40 percent.",
            ],
            "descriptionStyles": [
                "label",
                "plain",
                "plain",
                "label",
                "plain",
                "label",
                "bullet",
                "label",
                "bullet",
            ],
        }
    ]
    return source


def test_label_styles_survive_row_rewrite() -> None:
    """Matched candidate rows keep their SOURCE row style, incl. labels."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    # Rewrite the two duty/highlight bullets; emit no styles at all.
    candidate["personalProjects"][0]["description"][6] = (
        "Owned backend design and delivery of core modules."
    )
    candidate["personalProjects"][0]["description"][8] = (
        "Cut core API latency by 40 percent under peak load."
    )
    candidate["personalProjects"][0]["descriptionStyles"] = []

    finalized = finalize_ai_resume(source, candidate, allow_appended_rows=True)
    project = finalized["personalProjects"][0]

    assert project["descriptionStyles"] == source["personalProjects"][0][
        "descriptionStyles"
    ]
    # The four sub-module headings are still labels, so region rendering
    # (bold head, restarted numbering, unnumbered body) stays intact.
    for label_index in (0, 3, 5, 7):
        assert project["descriptionStyles"][label_index] == "label"
    assert project["descriptionStyles"][1] == "plain"
    assert validate_confirmed_resume(source, finalized) == []


def test_label_styles_survive_unmatched_source_row_restore() -> None:
    """A source row the candidate dropped is restored with its label style."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    # Drop the 项目亮点 label + its bullet from the candidate output.
    candidate["personalProjects"][0]["description"] = source["personalProjects"][0][
        "description"
    ][:7]
    candidate["personalProjects"][0]["descriptionStyles"] = []

    finalized = finalize_ai_resume(source, candidate)
    project = finalized["personalProjects"][0]

    assert project["description"] == source["personalProjects"][0]["description"]
    assert project["descriptionStyles"] == source["personalProjects"][0][
        "descriptionStyles"
    ]
    assert validate_confirmed_resume(source, finalized) == []


def test_appended_rows_never_inherit_label_style() -> None:
    """Newly appended rows are bullets even when the region opens at a label."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    description = list(candidate["personalProjects"][0]["description"])
    description.append("Built a reusable import/export tool.")
    candidate["personalProjects"][0]["description"] = description
    candidate["personalProjects"][0]["descriptionStyles"] = []

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=True,
        allow_appended_rows=True,
    )
    styles = finalized["personalProjects"][0]["descriptionStyles"]

    assert len(styles) == 10  # append accepted
    assert styles[-1] == "bullet"
    # Pre-existing labels survive untouched alongside the append.
    assert styles.count("label") == 4


# ---------------------------------------------------------------------------
# insert_row approval channel: JD-core tech in project 技术栈/项目亮点 regions
# ---------------------------------------------------------------------------


def _candidate_with_kafka_stack_row(source: dict[str, Any]) -> dict[str, Any]:
    """Candidate with a bare tech row inserted INSIDE the tech-stack region."""
    candidate = copy.deepcopy(source)
    project = candidate["personalProjects"][0]
    # Source region: [技术栈：, Java, Redis]; append "Kafka" at region end.
    project["description"] = [
        "技术栈：",
        "Java",
        "Redis",
        "Kafka",
        "项目背景：",
        "A digital platform for chain gyms.",
        "项目职责：",
        "Owned backend design of core modules.",
        "项目亮点：",
        "Cut core API latency by 40 percent.",
    ]
    project["descriptionStyles"] = [
        "label",
        "plain",
        "plain",
        "plain",
        "label",
        "plain",
        "label",
        "bullet",
        "label",
        "bullet",
    ]
    return candidate


def test_approved_tech_stack_row_survives_finalize_in_region() -> None:
    """A pre-approved stack row stays mid-list as a plain row, source rows intact."""
    source = _labeled_project_source()
    candidate = _candidate_with_kafka_stack_row(source)

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_appended_rows=True,
        approved_appended_rows={"kafka"},
    )
    project = finalized["personalProjects"][0]

    assert project["description"][:5] == [
        "技术栈：",
        "Java",
        "Redis",
        "Kafka",
        "项目背景：",
    ]
    assert project["descriptionStyles"][:5] == [
        "label",
        "plain",
        "plain",
        "plain",
        "label",
    ]
    # Every source row survives exactly once.
    for row in source["personalProjects"][0]["description"]:
        assert project["description"].count(row) == 1
    assert validate_confirmed_resume(
        source, finalized, allow_appended_rows=True, approved_project_rows={"kafka"}
    ) == []


def test_inserted_row_without_approval_loses_exemption() -> None:
    """With review claims off (legacy endpoint), an unapproved row is reverted."""
    source = _labeled_project_source()
    candidate = _candidate_with_kafka_stack_row(source)

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
    )
    rows = finalized["personalProjects"][0]["description"]
    styles = finalized["personalProjects"][0]["descriptionStyles"]

    assert "Kafka" not in rows
    # No invented content slips through: every emitted row is a source row,
    # and the four label headings keep their styles.
    assert set(rows) == set(source["personalProjects"][0]["description"])
    assert styles.count("label") == 4


def test_approved_highlight_row_survives_finalize_as_bullet() -> None:
    """A pre-approved highlight bullet stays at region end as a bullet."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    highlight = "Used Kafka to decouple order intake from downstream fulfillment"
    project = candidate["personalProjects"][0]
    project["description"] = [
        *project["description"],
        highlight,
    ]
    project["descriptionStyles"] = [
        *project["descriptionStyles"],
        "bullet",
    ]

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_appended_rows=True,
        approved_appended_rows={" ".join(highlight.split()).casefold()},
    )
    rows = finalized["personalProjects"][0]["description"]
    styles = finalized["personalProjects"][0]["descriptionStyles"]

    assert rows[-1] == highlight
    assert styles[-1] == "bullet"


def test_approved_auto_created_label_is_structural() -> None:
    """A label the diff flow auto-creates needs no explicit text approval."""
    source = _source_resume()  # style-less single-row project "Parser"
    candidate = copy.deepcopy(source)
    project = candidate["personalProjects"][0]
    project["description"] = ["Tech Stack:", "Kafka", "Parsed documents"]
    project["descriptionStyles"] = ["label", "plain", "bullet"]

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_appended_rows=True,
        approved_appended_rows={"kafka"},
    )
    rows = finalized["personalProjects"][0]["description"]

    assert rows == ["Tech Stack:", "Kafka", "Parsed documents"]


def test_approved_row_with_digit_loses_exemption() -> None:
    """A later rewrite that smuggles a number into an approved row is reverted."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    smuggled = "Kafka 集群承担日均 30 万订单事件异步解耦"
    project = candidate["personalProjects"][0]
    project["description"] = [
        *project["description"][:3],
        smuggled,
        *project["description"][3:],
    ]
    project["descriptionStyles"] = [
        *project["descriptionStyles"][:3],
        "plain",
        *project["descriptionStyles"][3:],
    ]

    finalized = finalize_ai_resume(
        source,
        candidate,
        allow_review_claims=False,
        allow_appended_rows=True,
        approved_appended_rows={"kafka"},
    )

    # The digit-bearing rewrite loses its approval and is reverted through the
    # ordinary novel-number gate, so the invented scale figure never survives.
    assert smuggled not in finalized["personalProjects"][0]["description"]
    assert all("30" not in row for row in finalized["personalProjects"][0]["description"])


def test_elaborated_skill_is_kept_and_bare_name_not_reappended() -> None:
    """elaborate_skill output survives finalize as one list entry."""
    source = {
        "personalInfo": {"name": "A"},
        "additional": {"technicalSkills": ["Python", "Redis"]},
    }
    elaboration = "Redis：分布式缓存与会话存储，负责热点数据读写与过期策略设计"
    candidate = {
        "personalInfo": {"name": "A"},
        "additional": {"technicalSkills": ["Python", elaboration]},
    }

    finalized = finalize_ai_resume(source, candidate)
    skills = finalized["additional"]["technicalSkills"]

    assert skills == ["Python", elaboration]
    assert skills.count("Redis") == 0


def test_proficiency_sentence_rewrite_kept_and_bare_name_not_reappended() -> None:
    """A marker-first rewrite of a bare skill covers the original entry."""
    source = {
        "personalInfo": {"name": "A"},
        "additional": {"technicalSkills": ["Python", "Redis"]},
    }
    rewrite = "熟练掌握 Redis 核心数据结构，以及缓存与分布式锁的典型用法"
    candidate = {
        "personalInfo": {"name": "A"},
        "additional": {"technicalSkills": ["Python", rewrite]},
    }

    finalized = finalize_ai_resume(source, candidate)
    skills = finalized["additional"]["technicalSkills"]

    assert skills == ["Python", rewrite]
    assert skills.count("Redis") == 0


def test_category_row_not_covered_by_single_tech_sentence() -> None:
    """Coverage is one-way for group rows: a Kafka sentence cannot drop the
    whole "后端：Java、Kafka" category entry."""
    from app.services.resume_preservation import skill_entry_covers

    assert not skill_entry_covers(
        "后端：Java、Kafka",
        "熟练掌握 Kafka 高吞吐事件流与异步解耦的典型用法",
    )


def test_homograph_not_covered_by_marker_sentence() -> None:
    """'Java' must not count as covered by a sentence that only names JavaScript."""
    from app.services.resume_preservation import skill_entry_covers

    assert not skill_entry_covers(
        "Java",
        "熟练运用 JavaScript 完成前端交互开发",
    )


def test_validate_confirmed_resume_rejects_inserted_rows_without_approval() -> None:
    """The strict contract still rejects mid-list rows when no preview binds them."""
    source = _labeled_project_source()
    candidate = _candidate_with_kafka_stack_row(source)

    assert "personalProjects.descriptions" in validate_confirmed_resume(
        source, candidate, allow_appended_rows=True
    )


def test_approved_preview_project_rows_helper_collects_extras() -> None:
    """Confirm re-derives approved rows from the hash-bound candidate."""
    source = _labeled_project_source()
    candidate = _candidate_with_kafka_stack_row(source)

    approved = approved_preview_project_rows(source, candidate)

    assert "kafka" in approved
    # Source rows and label rows already in the source are not re-approved.
    assert "java" not in approved
    assert "技术栈：" not in approved


def test_approved_preview_project_rows_helper_excludes_digits() -> None:
    """Digit-bearing extra rows keep going through the ordinary gates."""
    source = _labeled_project_source()
    candidate = copy.deepcopy(source)
    project = candidate["personalProjects"][0]
    project["description"] = [
        *project["description"],
        "引入 Kafka 承载日均 10 万订单事件并削峰",
    ]
    project["descriptionStyles"] = [*project["descriptionStyles"], "bullet"]

    approved = approved_preview_project_rows(source, candidate)

    assert not any("kafka" in row for row in approved)


def test_near_verbatim_source_row_stays_out_of_preview_approval_set() -> None:
    """A punctuation-only rewrite of a source row is a modification, not an insert.

    Regression: the refiner may rewrite an em-dash as commas inside a highlight
    bullet. Re-deriving the approval set at confirm used to treat the rewritten
    row as an inserted row (its normalized text no longer equals the source),
    so finalize kept the candidate without consuming the source slot and then
    force-restored the original as a duplicate — preview -> confirm was no
    longer idempotent and every confirmation failed with a 400.
    """
    from app.services.resume_preservation import _normalized

    source_row = (
        "全链路梯度降级：主模型故障切备用模型、图谱查询超时回退RAG"
        "——单点故障不影响核心问答可用性"
    )
    rewritten_row = (
        "全链路梯度降级：主模型故障切备用模型、图谱查询超时回退RAG, , "
        "单点故障不影响核心问答可用性"
    )
    inserted_row = "使用Redis缓存热点数据并通过连接池优化解决空闲连接超时问题"
    source = {
        "personalInfo": {"name": "A"},
        "personalProjects": [
            {
                "id": 7,
                "name": "RAG Platform",
                "role": "Backend",
                "years": "2024 - 2026",
                "description": [
                    "技术栈：",
                    "Redis",
                    "项目亮点：",
                    source_row,
                ],
                "descriptionStyles": ["label", "plain", "label", "bullet"],
            }
        ],
        "additional": {
            "technicalSkills": ["Redis"],
            "languages": [],
            "certificationsTraining": [],
            "awards": [],
        },
    }
    candidate = copy.deepcopy(source)
    project = candidate["personalProjects"][0]
    project["description"] = [
        "技术栈：",
        "Redis",
        "项目亮点：",
        rewritten_row,
        inserted_row,
    ]
    project["descriptionStyles"] = ["label", "plain", "label", "bullet", "bullet"]

    approved = approved_preview_project_rows(source, candidate)

    assert _normalized(rewritten_row) not in approved
    assert _normalized(inserted_row) in approved

    # The exact confirm seam: re-finalizing the hash-bound echo must reproduce
    # it byte-for-byte instead of restoring the original row as a duplicate.
    echo = ResumeData.model_validate(candidate).model_dump()
    finalized = finalize_ai_resume(
        source,
        echo,
        allow_appended_rows=True,
        approved_appended_rows=approved or None,
    )
    canonical = ResumeData.model_validate(finalized).model_dump()
    assert canonical == echo
    assert (
        validate_confirmed_resume(
            source,
            canonical,
            allow_appended_rows=True,
            approved_project_rows=approved,
        )
        == []
    )


def test_apply_finalize_confirm_closed_loop() -> None:
    """End-to-end deterministic seam: apply_diffs -> preview finalize -> confirm.

    The three-place skill loop (elaborated skill + tech-stack row + highlight
    bullet) must survive preview finalize, re-derive approval at confirm, and
    pass the strict source-contract validation without losing any source row.
    """
    from app.schemas.models import ResumeChange
    from app.services.improver import apply_diffs

    source = _labeled_project_source()
    # The project must already demonstrate Kafka in its own narrative rows;
    # the stack/highlight rows are promoted from that evidence, not planted.
    evidence_row = "基于 Kafka 完成订单中心履约事件总线的异步投递改造，覆盖下游仓储与物流通知环节"
    project0 = source["personalProjects"][0]
    label_index = project0["description"].index("项目亮点：")
    project0["description"].insert(label_index, evidence_row)
    project0["descriptionStyles"].insert(label_index, "bullet")
    source["additional"] = {
        "technicalSkills": ["Java", "Redis", "Kafka"],
        "languages": [],
        "certificationsTraining": [],
        "awards": [],
    }
    targets = [{"skill": "Kafka"}]
    changes = [
        ResumeChange(
            path="additional.technicalSkills[2]",
            action="elaborate_skill",
            original=None,
            value="Kafka：高吞吐分布式消息队列，负责订单事件异步解耦与高峰流量削峰",
            reason="JD core technology; expand the bare stack entry",
        ),
        ResumeChange(
            path="personalProjects[0].description",
            action="insert_row",
            anchor="tech_stack",
            original=None,
            value="Kafka",
            reason="surface the tech in the project tech-stack region",
        ),
        ResumeChange(
            path="personalProjects[0].description",
            action="insert_row",
            anchor="highlight",
            original=None,
            value="基于 Kafka 构建订单事件异步链路，解耦下单与下游履约环节",
            reason="show the concrete business-scenario application",
        ),
    ]

    tailored, applied, rejected = apply_diffs(source, changes, allowed_skill_targets=targets)
    assert len(applied) == 3 and len(rejected) == 0

    # Preview-time approval channel, exactly as the router builds it.
    preview_approved = {
        " ".join(change.value.split()).casefold()
        for change in applied
        if change.action == "insert_row" and isinstance(change.value, str)
    }
    finalized = finalize_ai_resume(
        source,
        tailored,
        allow_appended_rows=True,
        approved_appended_rows=preview_approved or None,
    )

    skills = finalized["additional"]["technicalSkills"]
    assert skills[2].startswith("Kafka：")
    assert skills.count("Kafka") == 0
    project = finalized["personalProjects"][0]
    assert "Kafka" in project["description"]  # tech-stack row
    assert project["descriptionStyles"][project["description"].index("Kafka")] == "plain"
    assert any("基于 Kafka" in row for row in project["description"])
    for row in source["personalProjects"][0]["description"]:
        assert project["description"].count(row) == 1

    # Confirm re-derives approval from the hash-bound payload; strict contract
    # validation must accept exactly the registered preview.
    confirm_approved = approved_preview_project_rows(source, finalized)
    assert "kafka" in confirm_approved
    assert (
        validate_confirmed_resume(
            source,
            finalized,
            allow_appended_rows=True,
            approved_project_rows=confirm_approved,
        )
        == []
    )
