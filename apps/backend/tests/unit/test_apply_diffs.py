"""Unit tests for apply_diffs() — path resolution, verification gates, and actions."""

import copy
import pytest

from app.schemas.models import ResumeChange
from app.services.improver import apply_diffs


class TestApplyDiffsReplace:
    """Tests for the 'replace' action."""

    def test_replace_summary(self, sample_resume):
        changes = [
            ResumeChange(
                path="summary",
                action="replace",
                original=sample_resume["summary"],
                value="Updated summary text.",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert result["summary"] == "Updated summary text."

    def test_replace_description_bullet(self, sample_resume):
        original_bullet = sample_resume["workExperience"][0]["description"][1]
        changes = [
            ResumeChange(
                path="workExperience[0].description[1]",
                action="replace",
                original=original_bullet,
                value="Architected microservices migration serving 100K users",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert result["workExperience"][0]["description"][1] == changes[0].value

    def test_replace_project_description_bullet(self, sample_resume):
        original_bullet = sample_resume["personalProjects"][0]["description"][0]
        changes = [
            ResumeChange(
                path="personalProjects[0].description[0]",
                action="replace",
                original=original_bullet,
                value="Python CLI tool generating API clients from OpenAPI specs",
                reason="Added Python keyword",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert result["personalProjects"][0]["description"][0] == changes[0].value

    def test_replace_case_insensitive_original_match(self, sample_resume):
        original_bullet = sample_resume["workExperience"][0]["description"][0]
        changes = [
            ResumeChange(
                path="workExperience[0].description[0]",
                action="replace",
                original=original_bullet.upper(),  # Case difference
                value="New text",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1


class TestApplyDiffsAppend:
    """Tests for the 'append' action."""

    def test_append_bullet_to_experience(self, sample_resume):
        original_count = len(sample_resume["workExperience"][0]["description"])
        changes = [
            ResumeChange(
                path="workExperience[0].description",
                action="append",
                original=None,
                value="Implemented CI/CD pipelines with GitHub Actions",
                reason="Added CI/CD keyword",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(result["workExperience"][0]["description"]) == original_count + 1
        assert result["workExperience"][0]["description"][-1] == changes[0].value

    def test_append_bullet_to_project(self, sample_resume):
        original_count = len(sample_resume["personalProjects"][0]["description"])
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="append",
                original=None,
                value="Published to PyPI with 10K+ monthly downloads",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(result["personalProjects"][0]["description"]) == original_count + 1


class TestApplyDiffsAddSkill:
    """Tests for adding verified skills to the technical skills list."""

    def test_add_skill_to_technical_skills(self, sample_resume):
        sentence = (
            "Familiar with Kubernetes container orchestration for declarative "
            "deployment and scaling"
        )
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value=sentence,
                reason="JD-required skill approved by verifier",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert sentence in result["additional"]["technicalSkills"]

    def test_add_skill_rejects_bare_name_and_name_prefix(self, sample_resume):
        # New entries must open with a proficiency word; neither a bare stack
        # name nor a "Name: detail" label is an accepted sentence form.
        for value in ("Kubernetes", "Kubernetes：容器编排与声明式部署"):
            changes = [
                ResumeChange(
                    path="additional.technicalSkills",
                    action="add_skill",
                    original=None,
                    value=value,
                    reason="missing proficiency positioning",
                )
            ]
            result, applied, rejected = apply_diffs(
                sample_resume,
                changes,
                allowed_skill_targets=[{"skill": "Kubernetes"}],
            )
            assert len(applied) == 0, value
            assert len(rejected) == 1, value
            assert value not in result["additional"]["technicalSkills"]

    def test_add_skill_rejects_sentence_stacking_more_than_two_techs(
        self, sample_resume
    ):
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value="熟悉 Kafka、Redis、MySQL 的典型用法与高可用运维方案",
                reason="one sentence centers on three technologies",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[
                {"skill": "Kafka"},
                {"skill": "Redis"},
                {"skill": "MySQL"},
            ],
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_add_skill_rejects_unverified_skill(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value="BananaDB",
                reason="Unsupported skill should not be appended",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "BananaDB" not in result["additional"]["technicalSkills"]

    def test_add_skill_rejects_duplicate_case_insensitive(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value="python",
                reason="Duplicate skill should not be appended",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Python"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"].count("Python") == 1

    def test_add_skill_rejects_technology_inside_category_row(self):
        # The resume groups skills in a category line; Kafka is already listed
        # there, so a standalone Kafka entry would duplicate it.
        resume = {
            "additional": {
                "technicalSkills": ["后端：Java、Kafka、Redis", "Python"]
            }
        }
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value="Kafka：高吞吐分布式消息队列，用于服务间异步解耦与流量削峰",
                reason="Kafka already exists inside the category row",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"] == [
            "后端：Java、Kafka、Redis",
            "Python",
        ]

    def test_add_skill_rejects_when_elaborated_entry_exists(self):
        # An existing "Name: detail" entry already covers the technology.
        resume = {"additional": {"technicalSkills": ["Kafka：分布式消息队列与异步解耦"]}}
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value="Kafka",
                reason="bare duplicate of the elaborated entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"] == [
            "Kafka：分布式消息队列与异步解耦"
        ]

    def test_add_skill_allows_homograph_substring(self):
        # "JavaScript" must not count as already listing "Java".
        resume = {"additional": {"technicalSkills": ["JavaScript", "React"]}}
        sentence = "熟练运用 Java 进行 JVM 后端开发与并发编程，熟悉 Spring 生态"
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="add_skill",
                original=None,
                value=sentence,
                reason="Java is a distinct technology from JavaScript",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Java"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert sentence in result["additional"]["technicalSkills"]

    def test_add_skill_rejects_non_skill_path(self, sample_resume):
        changes = [
            ResumeChange(
                path="summary",
                action="add_skill",
                original=None,
                value="Kubernetes",
                reason="Skill additions are only allowed in technical skills",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "Kubernetes" not in result["additional"]["technicalSkills"]


class TestApplyDiffsReorder:
    """Tests for the 'reorder' action."""

    def test_reorder_skills(self, sample_resume):
        original_skills = sample_resume["additional"]["technicalSkills"]
        reordered = list(reversed(original_skills))
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=reordered,
                reason="Prioritized relevant skills",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert result["additional"]["technicalSkills"] == reordered

    def test_reorder_with_unverified_items_drops_them_keeps_originals(self, sample_resume):
        """Issue #736: a reorder mixing in new items is salvaged, not dropped —
        new items without a verified target are removed, originals preserved."""
        original = sample_resume["additional"]["technicalSkills"]
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Python", "Kubernetes", "Go"],  # Kubernetes/Go new, no verified targets
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1 and len(rejected) == 0
        assert "Kubernetes" not in skills and "Go" not in skills
        assert set(skills) == set(original)
        assert skills[0] == "Python"

    def test_reorder_case_insensitive_matching(self, sample_resume):
        original_skills = sample_resume["additional"]["technicalSkills"]
        reordered = [s.lower() for s in reversed(original_skills)]
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=reordered,
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1

    def test_reorder_accepts_list_original_and_applies(self, sample_resume):
        # The live LLM ignores the prompt's `original: null` for reorder and sends
        # the current skills LIST as `original`. The schema must accept that — a
        # `str | None`-only `original` dropped the whole change at parse time with a
        # `string_type` error ("Skipping malformed change") — and a pure reorder
        # (same items, new order) must still apply.
        original_skills = sample_resume["additional"]["technicalSkills"]
        reordered = list(reversed(original_skills))
        change = ResumeChange(
            path="additional.technicalSkills",
            action="reorder",
            original=original_skills,  # a LIST, exactly as the LLM sends it
            value=reordered,
            reason="prioritize JD-relevant skills",
        )
        assert change.original == original_skills
        result, applied, rejected = apply_diffs(sample_resume, [change])
        assert len(applied) == 1
        assert result["additional"]["technicalSkills"] == reordered

    def test_list_original_rejected_for_non_reorder_actions(self):
        # A list `original` is valid ONLY for reorder. For a text action like
        # replace it would bypass the original-match gate and crash the
        # invented-metrics check, so the schema rejects it at construction.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path="summary",
                action="replace",
                original=["a", "b"],  # list original on a text action — invalid
                value="new summary",
                reason="test",
            )


class TestApplyDiffsBlockedPaths:
    """Tests for blocked path rejection."""

    @pytest.mark.parametrize("path,original_val", [
        ("personalInfo.name", "Jane Doe"),
        ("personalInfo.email", "jane@example.com"),
    ])
    def test_reject_personal_info(self, sample_resume, path, original_val):
        changes = [
            ResumeChange(path=path, action="replace", original=original_val, value="X", reason="test")
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1
        assert len(applied) == 0

    def test_reject_date_change(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[0].years",
                action="replace",
                original="Jan 2021 - Present",
                value="Jan 2019 - Present",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_company_change(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[0].company",
                action="replace",
                original="Acme Corp",
                value="Google",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_education_change(self, sample_resume):
        changes = [
            ResumeChange(
                path="education[0].degree",
                action="replace",
                original="B.S. Computer Science",
                value="M.S. Computer Science",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_custom_sections(self, sample_resume):
        changes = [
            ResumeChange(
                path="customSections.volunteer",
                action="replace",
                original=None,
                value="Volunteer work",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_project_role(self, sample_resume):
        changes = [
            ResumeChange(
                path="personalProjects[0].role",
                action="replace",
                original="Creator & Maintainer",
                value="CTO",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_location_change(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[0].location",
                action="replace",
                original="San Francisco, CA",
                value="Remote",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1


class TestApplyDiffsVerificationGates:
    """Tests for path resolution and original text verification."""

    def test_reject_out_of_bounds_index(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[99].description[0]",
                action="replace",
                original="Nonexistent",
                value="New",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_original_text_mismatch(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[0].description[0]",
                action="replace",
                original="This text does not exist anywhere in the resume",
                value="New text",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reject_unknown_action_at_schema_level(self, sample_resume):
        """Pydantic Literal type prevents invalid actions before apply_diffs sees them."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path="summary",
                action="delete",  # type: ignore[arg-type]
                original=sample_resume["summary"],
                value="",
                reason="test",
            )

    def test_reject_nonexistent_path(self, sample_resume):
        changes = [
            ResumeChange(
                path="nonexistent.field",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1


class TestApplyDiffsIntegrity:
    """Tests for data integrity and multi-change scenarios."""

    def test_does_not_mutate_original(self, sample_resume):
        original_copy = copy.deepcopy(sample_resume)
        changes = [
            ResumeChange(
                path="summary",
                action="replace",
                original=sample_resume["summary"],
                value="Changed",
                reason="test",
            )
        ]
        result, _, _ = apply_diffs(sample_resume, changes)
        assert sample_resume == original_copy
        assert result["summary"] == "Changed"

    def test_multiple_changes_partial_rejection(self, sample_resume):
        changes = [
            ResumeChange(
                path="summary",
                action="replace",
                original=sample_resume["summary"],
                value="New summary",
                reason="good",
            ),
            ResumeChange(
                path="personalInfo.name",
                action="replace",
                original="Jane Doe",
                value="Bad",
                reason="blocked",
            ),
            ResumeChange(
                path="workExperience[0].description[0]",
                action="replace",
                original=sample_resume["workExperience"][0]["description"][0],
                value="Updated bullet",
                reason="good",
            ),
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 2
        assert len(rejected) == 1
        assert result["summary"] == "New summary"
        assert result["personalInfo"]["name"] == "Jane Doe"  # Unchanged

    def test_empty_changes_list(self, sample_resume):
        result, applied, rejected = apply_diffs(sample_resume, [])
        assert len(applied) == 0
        assert len(rejected) == 0
        assert result == sample_resume

    def test_all_changes_applied(self, sample_resume, sample_changes):
        result, applied, rejected = apply_diffs(sample_resume, sample_changes)
        assert len(rejected) == 0
        assert len(applied) == len(sample_changes)


class TestApplyDiffsEdgeCases:
    """Edge cases: hostile inputs, malformed paths, boundary conditions."""

    def test_append_to_non_list_rejected(self, sample_resume):
        """Append to a string field (summary) should be rejected."""
        changes = [
            ResumeChange(
                path="summary",
                action="append",
                original=None,
                value="Extra text",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1
        assert len(applied) == 0

    def test_reorder_non_list_rejected(self, sample_resume):
        """Reorder on a string field should be rejected."""
        changes = [
            ResumeChange(
                path="summary",
                action="reorder",
                original=None,
                value=["a", "b"],
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reorder_with_non_list_value_rejected(self, sample_resume):
        """Reorder where value is a string instead of list should be rejected."""
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value="Python, Docker",  # type: ignore[arg-type]
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_reorder_with_duplicates_is_deduped_and_preserves_originals(self, sample_resume):
        """Issue #736: a reorder with a duplicate and missing items is salvaged —
        the duplicate is collapsed and every original is preserved (no loss)."""
        original = sample_resume["additional"]["technicalSkills"]
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Python", "Python", "Docker", "AWS", "PostgreSQL"],  # Python duplicated, Redis/FastAPI missing
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1
        assert skills.count("Python") == 1          # duplicate collapsed
        assert set(skills) == set(original)          # nothing lost

    def test_empty_path_rejected(self, sample_resume):
        """Empty path string should be rejected."""
        changes = [
            ResumeChange(
                path="",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_deeply_nested_invalid_path_rejected(self, sample_resume):
        """Path with too many segments that don't resolve."""
        changes = [
            ResumeChange(
                path="workExperience[0].description[0].nested.deep",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_negative_index_rejected(self, sample_resume):
        """Negative array index should not resolve."""
        changes = [
            ResumeChange(
                path="workExperience[-1].description[0]",
                action="replace",
                original="x",
                value="y",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(rejected) == 1

    def test_second_experience_entry(self, sample_resume):
        """Changes to the second work experience entry should work."""
        original_bullet = sample_resume["workExperience"][1]["description"][0]
        changes = [
            ResumeChange(
                path="workExperience[1].description[0]",
                action="replace",
                original=original_bullet,
                value="Updated payment system description",
                reason="test",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert result["workExperience"][1]["description"][0] == "Updated payment system description"
        # First entry unchanged
        assert result["workExperience"][0]["description"][0] == sample_resume["workExperience"][0]["description"][0]


class TestApplyDiffsNewPaths:
    """Newly allowed paths for issue #805 (broader diff scope, casing preserved)."""

    def test_replace_education_description(self, sample_resume):
        """Education description (a single string) should be replaceable."""
        changes = [
            ResumeChange(
                path="education[0].description",
                action="replace",
                original=sample_resume["education"][0]["description"],
                value="Graduated with honors; focus on distributed systems and APIs",
                reason="surface relevant coursework",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert result["education"][0]["description"] == changes[0].value

    def test_reject_education_description_list_index(self, sample_resume):
        """Education description is a scalar string, so the [j] bullet form is not allowed."""
        changes = [
            ResumeChange(
                path="education[0].description[0]",
                action="replace",
                original="Graduated with honors, Dean's List",
                value="anything",
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_reorder_languages(self, sample_resume):
        """Languages list should be reorderable (same items, new order)."""
        original = sample_resume["additional"]["languages"]
        changes = [
            ResumeChange(
                path="additional.languages",
                action="reorder",
                original=None,
                value=list(reversed(original)),
                reason="prioritize Spanish for this role",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert result["additional"]["languages"] == list(reversed(original))

    def test_reorder_awards(self, sample_resume):
        """Awards list should be reorderable."""
        original = sample_resume["additional"]["awards"]
        changes = [
            ResumeChange(
                path="additional.awards",
                action="reorder",
                original=None,
                value=list(original),
                reason="no change needed",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0
        assert result["additional"]["awards"] == original

    def test_reorder_certifications(self, sample_resume):
        """Certifications list should be reorderable."""
        original = sample_resume["additional"]["certificationsTraining"]
        changes = [
            ResumeChange(
                path="additional.certificationsTraining",
                action="reorder",
                original=None,
                value=list(original),
                reason="no change needed",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1
        assert len(rejected) == 0

    @pytest.mark.parametrize(
        "path,original,value",
        [
            ("education[0].degree", "B.S. Computer Science", "M.S. Computer Science"),
            ("education[0].institution", "MIT", "Stanford"),
            ("education[0].years", "2014 - 2018", "2014 - 2020"),
        ],
    )
    def test_reject_blocked_education_fields(self, sample_resume, path, original, value):
        """Degree/institution/years stay blocked even though description is now allowed."""
        changes = [
            ResumeChange(
                path=path,
                action="replace",
                original=original,
                value=value,
                reason="test",
            )
        ]
        _result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1


class TestReorderSalvage:
    """Issue #736: a reorder whose items don't exactly match the original must be
    SALVAGED, not dropped wholesale — reorder existing items, never lose an
    original, and (skills only) add new items that pass the verified gate."""

    def test_reorder_with_verified_new_skill_is_salvaged(self, sample_resume):
        original = sample_resume["additional"]["technicalSkills"]  # 6 items
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["FastAPI", "Python", "Docker", "AWS", "PostgreSQL", "Redis", "Kubernetes"],
                reason="surface JD skills; Kubernetes is JD-required",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1 and len(rejected) == 0
        assert "Kubernetes" in skills                      # verified new skill added
        assert set(original).issubset(set(skills))         # no original lost
        assert skills[0] == "FastAPI"                       # LLM order honored

    def test_reorder_with_unverified_new_skill_drops_only_that_skill(self, sample_resume):
        original = sample_resume["additional"]["technicalSkills"]
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Redis", "Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "Rust"],
                reason="Rust is not in the verified targets",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1                            # salvaged, not rejected
        assert "Rust" not in skills                         # unverified addition dropped
        assert set(original).issubset(set(skills))          # originals preserved
        assert skills[0] == "Redis"

    def test_reorder_omitting_original_skill_preserves_it(self, sample_resume):
        original = sample_resume["additional"]["technicalSkills"]
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Redis", "Python"],  # omits 4 originals
                reason="prioritize two skills",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1
        assert set(skills) == set(original)                 # nothing lost
        assert skills[:2] == ["Redis", "Python"]            # requested order first

    def test_reorder_languages_with_new_item_drops_it(self, sample_resume):
        original = sample_resume["additional"]["languages"]
        changes = [
            ResumeChange(
                path="additional.languages",
                action="reorder",
                original=None,
                value=["Spanish (Conversational)", "English (Native)", "French (Fluent)"],
                reason="no verified-target gate for languages — must not fabricate",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        langs = result["additional"]["languages"]
        assert len(applied) == 1
        assert "French (Fluent)" not in langs               # no fabrication
        assert set(langs) == set(original)

    def test_pure_permutation_still_applies(self, sample_resume):
        """Regression: an exact permutation keeps working unchanged."""
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Redis", "PostgreSQL", "AWS", "Docker", "FastAPI", "Python"],
                reason="pure reorder",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 1 and len(rejected) == 0
        assert result["additional"]["technicalSkills"] == [
            "Redis", "PostgreSQL", "AWS", "Docker", "FastAPI", "Python"
        ]

    def test_salvage_places_verified_new_skill_in_requested_position(self, sample_resume):
        """PR #830 review (Copilot): a verified new skill the model puts near the
        top of the reorder must land there, not be appended last."""
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Kubernetes", "Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "Redis"],
                reason="prioritize Kubernetes (JD-required, verified)",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        skills = result["additional"]["technicalSkills"]
        assert skills[0] == "Kubernetes"  # requested position honored, not appended last
        assert set(sample_resume["additional"]["technicalSkills"]).issubset(set(skills))

    def test_salvage_preserves_case_duplicate_originals(self, sample_resume):
        """PR #830 review (kilo): case-duplicate originals must not be lost."""
        resume = {"additional": {"technicalSkills": ["python", "Python", "Docker"]}}
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Docker", "python", "Go"],  # Go new+unverified, both pythons are originals
                reason="test dup handling",
            )
        ]
        result, applied, rejected = apply_diffs(resume, changes)
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1
        # Both case-variants of the original survive; the unverified new item is dropped.
        assert sorted(skills) == sorted(["python", "Python", "Docker"])
        assert "Go" not in skills


    def test_salvage_drops_skill_already_inside_category_row(self):
        """Reorder salvage must not re-add a tech embedded in a group row."""
        resume = {
            "additional": {"technicalSkills": ["后端：Java、Kafka", "Python"]}
        }
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="reorder",
                original=None,
                value=["Python", "Kafka"],
                reason="model tried to surface Kafka as its own entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume,
            changes,
            allowed_skill_targets=[{"skill": "Kafka"}, {"skill": "Python"}],
        )
        skills = result["additional"]["technicalSkills"]
        assert len(applied) == 1
        assert "Kafka" not in skills  # not duplicated as a standalone entry
        assert "后端：Java、Kafka" in skills
        assert skills[0] == "Python"  # the genuinely repositioned original keeps priority


def _resume_with_project_regions() -> dict:
    """A CJK project whose description already has 职责/技术栈/亮点 label regions.

    The narrative rows already demonstrate Redis (distributed lock + hot-key
    cache) and Kafka (async order-event notification): tech-stack rows and
    highlights for those technologies are project-evidenced, not planted.
    """
    return {
        "personalProjects": [
            {
                "id": 1,
                "name": "订单中台",
                "role": "核心开发",
                "years": "2022 - 2023",
                "description": [
                    "项目职责：",
                    "负责订单核心链路的设计与开发",
                    "基于 Redis 分布式锁处理订单履约状态的并发更新，并缓存热点订单数据",
                    "通过 Kafka 异步通知订单履约事件，解耦下游通知环节",
                    "技术栈：",
                    "Python",
                    "FastAPI",
                    "项目亮点：",
                    "支撑日常订单履约全流程",
                ],
                "descriptionStyles": [
                    "label",
                    "bullet",
                    "bullet",
                    "bullet",
                    "label",
                    "plain",
                    "plain",
                    "label",
                    "bullet",
                ],
            }
        ],
        "additional": {"technicalSkills": ["Python", "FastAPI"]},
    }


class TestResumeChangeAnchorSchema:
    """The anchor field exists solely for project insert_row actions."""

    def test_insert_row_requires_anchor(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                original=None,
                value="Kafka",
                reason="missing anchor must fail parse",
            )

    def test_anchor_rejected_for_other_actions(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path="personalProjects[0].description",
                action="append",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="anchor is insert_row-only",
            )

    def test_anchor_values_are_limited(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="duties",  # type: ignore[arg-type]
                original=None,
                value="text",
                reason="only tech_stack/highlight are valid anchors",
            )

    def test_valid_insert_row_change_constructs(self):
        change = ResumeChange(
            path="personalProjects[0].description",
            action="insert_row",
            anchor="tech_stack",
            original=None,
            value="Kafka",
            reason="ok",
        )
        assert change.anchor == "tech_stack"


class TestApplyDiffsElaborateSkill:
    """elaborate_skill turns a bare skill list entry into a <=2-line detail."""

    def test_elaborate_bare_skill(self, sample_resume):
        # Redis sits at index 5 of the fixture skills list.
        elaboration = "Redis：分布式缓存与会话存储，负责热点数据读写、过期策略与高可用方案设计"
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value=elaboration,
                reason="expand a JD-core bare stack entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        skills = result["additional"]["technicalSkills"]
        assert skills[5] == elaboration
        assert skills.count("Redis") == 0  # bare name replaced, not duplicated

    def test_elaborate_skill_must_be_verified(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="Redis：分布式缓存设计、热点 key 治理与过期策略管理",
                reason="Redis is not in the verified targets",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Kubernetes"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_value_must_start_with_current_name(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="MongoDB：文档数据库的建模与副本集运维",
                reason="does not extend the Redis entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}, {"skill": "MongoDB"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_rejects_category_row(self, sample_resume):
        # A category/group row ("后端：Java、Go") must never be expanded in place.
        sample_resume["additional"]["technicalSkills"][5] = "后端开发：Java、Go"
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="后端开发：Java、Go 微服务与消息中间件治理",
                reason="category rows are not single-technology entries",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Java"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_elaborate_skill_rejects_new_digits(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="Redis：5 年生产环境分布式缓存设计与高可用治理经验",
                reason="new year count is an invented numeric claim",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_rejects_overlong_detail(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="Redis：" + "缓存治理" * 30,
                reason="well beyond the two-line budget",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_elaborate_skill_rejects_duplicate_elaboration(self, sample_resume):
        skills = sample_resume["additional"]["technicalSkills"]
        skills.append("Redis：高可用缓存与热点 key 治理")  # a second Redis entry exists
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="Redis：分布式缓存与会话存储设计",
                reason="an elaboration of Redis already exists elsewhere",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_bare_skill_with_proficiency_sentence(self, sample_resume):
        # The new style: rewrite the bare entry as a proficiency-first sentence
        # that names the bare technology mid-line instead of a "Name:" prefix.
        elaboration = "熟练掌握 Redis 核心数据结构，以及缓存与分布式锁的典型用法"
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value=elaboration,
                reason="JD-core entry rewritten in the resume's sentence style",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        skills = result["additional"]["technicalSkills"]
        assert skills[5] == elaboration
        assert skills.count("Redis") == 0

    def test_elaborate_skill_sentence_must_name_current_entry(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="熟练掌握 MongoDB 文档建模与副本集运维的典型用法",
                reason="sentence is about MongoDB, not the Redis entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}, {"skill": "MongoDB"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_rejects_existing_marker_sentence_duplicate(
        self, sample_resume
    ):
        skills = sample_resume["additional"]["technicalSkills"]
        skills.append("熟练掌握 Redis 缓存与过期策略的典型用法")
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="Redis：分布式缓存与会话存储设计",
                reason="a proficiency sentence about Redis already exists",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_rejects_sentence_naming_three_techs(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills[5]",
                action="elaborate_skill",
                original=None,
                value="熟悉 Redis、Kafka、MySQL 的典型用法与高可用运维方案",
                reason="one sentence stacks three technologies",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[
                {"skill": "Redis"},
                {"skill": "Kafka"},
                {"skill": "MySQL"},
            ],
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["additional"]["technicalSkills"][5] == "Redis"

    def test_elaborate_skill_requires_indexed_path(self, sample_resume):
        changes = [
            ResumeChange(
                path="additional.technicalSkills",
                action="elaborate_skill",
                original=None,
                value="Redis：分布式缓存设计",
                reason="the collection path cannot identify an entry",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume,
            changes,
            allowed_skill_targets=[{"skill": "Redis"}],
        )
        assert len(applied) == 0
        assert len(rejected) == 1


class TestApplyDiffsInsertRow:
    """insert_row feeds JD-core tech into project 技术栈/项目亮点 sub-modules."""

    def test_insert_tech_stack_row_into_existing_region(self):
        resume = _resume_with_project_regions()
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Redis",
                reason="JD core tech must surface in the project stack",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Redis"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        rows = result["personalProjects"][0]["description"]
        styles = result["personalProjects"][0]["descriptionStyles"]
        assert rows == [
            "项目职责：",
            "负责订单核心链路的设计与开发",
            "基于 Redis 分布式锁处理订单履约状态的并发更新，并缓存热点订单数据",
            "通过 Kafka 异步通知订单履约事件，解耦下游通知环节",
            "技术栈：",
            "Python",
            "FastAPI",
            "Redis",
            "项目亮点：",
            "支撑日常订单履约全流程",
        ]
        assert styles == [
            "label",
            "bullet",
            "bullet",
            "bullet",
            "label",
            "plain",
            "plain",
            "plain",
            "label",
            "bullet",
        ]

    def test_insert_highlight_row_into_existing_region(self):
        resume = _resume_with_project_regions()
        highlight = "基于 Redis 缓存热点订单数据，降低数据库读压力并支撑峰值流量"
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value=highlight,
                reason="concrete business-scenario application of the tech",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Redis"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        entry = result["personalProjects"][0]
        assert entry["description"][-1] == highlight
        assert entry["description"][-2] == "支撑日常订单履约全流程"
        assert entry["descriptionStyles"][-1] == "bullet"

    def test_insert_tech_stack_creates_english_label_region_when_missing(
        self, sample_resume
    ):
        # The fixture project has no labels/styles and English content; its
        # narrative already demonstrates OpenAPI, so the stack row is evidenced.
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="OpenAPI",
                reason="create the Tech Stack sub-module",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "OpenAPI"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        entry = result["personalProjects"][0]
        assert entry["description"][:2] == ["Tech Stack:", "OpenAPI"]
        assert entry["descriptionStyles"][:2] == ["label", "plain"]
        assert len(entry["descriptionStyles"]) == len(entry["description"])

    def test_insert_highlight_appends_english_label_region_when_missing(
        self, sample_resume
    ):
        # Grounded in the project's own vocabulary ("API clients", "specs").
        highlight = (
            "Automated API client generation from OpenAPI specs so consumers "
            "regenerate typed clients without hand-written glue code"
        )
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value=highlight,
                reason="create the Project Highlights sub-module at the end",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "OpenAPI"}]
        )
        assert len(applied) == 1
        entry = result["personalProjects"][0]
        assert entry["description"][-2:] == ["Project Highlights:", highlight]
        assert entry["descriptionStyles"][-2:] == ["label", "bullet"]
        assert len(entry["descriptionStyles"]) == len(entry["description"])

    def test_insert_into_cjk_project_creates_chinese_labels(self):
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "开发",
                    "years": "2022 - Present",
                    "description": ["基于 Redis 缓存重构订单核心链路并落地"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Redis",
                reason="CJK project gets a canonical Chinese label",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Redis"}]
        )
        assert len(applied) == 1
        assert result["personalProjects"][0]["description"] == [
            "技术栈：",
            "Redis",
            "基于 Redis 缓存重构订单核心链路并落地",
        ]
        assert result["personalProjects"][0]["descriptionStyles"] == [
            "label",
            "plain",
            "bullet",
        ]

    def test_insert_tech_stack_rejects_unverified_technology(self):
        resume = _resume_with_project_regions()
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Redis",
                reason="Redis is not a verified target",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kubernetes"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "Redis" not in result["personalProjects"][0]["description"]

    def test_insert_tech_stack_rejects_multi_tech_punctuation_and_digits(self):
        resume = _resume_with_project_regions()
        for value in ("Redis, Kafka", "Redis：缓存", "Redis 6"):
            changes = [
                ResumeChange(
                    path="personalProjects[0].description",
                    action="insert_row",
                    anchor="tech_stack",
                    original=None,
                    value=value,
                    reason="stack rows are bare single names only",
                )
            ]
            result, applied, rejected = apply_diffs(
                resume,
                changes,
                allowed_skill_targets=[
                    {"skill": "Redis"},
                    {"skill": "Kafka"},
                ],
            )
            assert len(applied) == 0, value
            assert len(rejected) == 1, value

    def test_insert_highlight_rejects_without_verified_tech_mention(self):
        resume = _resume_with_project_regions()
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="优化了订单处理链路的吞吐与稳定性表现",
                reason="names no verified technology",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_highlight_rejects_numeric_claims(self):
        resume = _resume_with_project_regions()
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="引入 Kafka 处理日均十万级订单事件并承担削峰",
                reason="digit-free Chinese check",
            )
        ]
        # Sanity: a digit-free grounded highlight applies.
        ok_result, applied, _ = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 1

        resume = _resume_with_project_regions()
        changes[0] = ResumeChange(
            path="personalProjects[0].description",
            action="insert_row",
            anchor="highlight",
            original=None,
            value="引入 Kafka 处理日均 10 万订单事件并承担削峰",
            reason="contains an invented scale figure",
        )
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert ok_result is not result

    def test_insert_row_rejects_non_project_paths(self, sample_resume):
        changes = [
            ResumeChange(
                path="workExperience[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Redis",
                reason="insert_row is project-only",
            )
        ]
        result, applied, rejected = apply_diffs(
            sample_resume, changes, allowed_skill_targets=[{"skill": "Redis"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_tech_stack_rejects_duplicate_row(self):
        resume = _resume_with_project_regions()  # region already lists Python
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Python",
                reason="already present in the stack region",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Python"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_tech_stack_rejects_tech_inside_combined_row(self):
        # The stack region already lists Kafka inside a multi-tech row.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "技术栈：",
                        "Python、Kafka、Redis",
                        "项目亮点：",
                        "支撑日常订单履约全流程",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="already listed in a combined stack row",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert result["personalProjects"][0]["description"] == [
            "技术栈：",
            "Python、Kafka、Redis",
            "项目亮点：",
            "支撑日常订单履约全流程",
        ]

    def test_insert_tech_stack_rejects_qualified_variant(self):
        # A parenthetical qualified row ("Kafka（消息队列）") already lists it.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "技术栈：",
                        "Kafka（消息队列）",
                        "项目亮点：",
                        "支撑日常订单履约全流程",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="already listed with a qualifier",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_tech_stack_allows_tech_only_in_highlight_region(self):
        # Dedupe is region-scoped: the tech appears in 项目亮点 prose, not in
        # any stack region, so the stack row is still needed and is allowed.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "项目亮点：",
                        "基于 Kafka 解耦下单与履约链路，促销高峰承担削峰",
                    ],
                    "descriptionStyles": ["label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="stack region does not list it yet",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert "Kafka" in result["personalProjects"][0]["description"]

    def test_insert_tech_stack_second_batch_duplicate_is_rejected(self):
        # Two identical stack inserts in one diff batch: after the first
        # creates the region, the second must be caught as a duplicate.
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="first insert creates the stack region",
            ),
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="duplicate of the first",
            ),
        ]
        result, applied, rejected = apply_diffs(
            _resume_with_project_regions(),
            changes,
            allowed_skill_targets=[{"skill": "Kafka"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 1
        rows = result["personalProjects"][0]["description"]
        assert rows.count("Kafka") == 1

    def test_insert_tech_stack_same_tech_allowed_in_other_project(self):
        # Dedup is per-project: each project's stack lists the tech at most once.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "开发",
                    "years": "2022",
                    "description": [
                        "技术栈：",
                        "Kafka",
                        "项目亮点：",
                        "订单事件异步解耦",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet"],
                },
                {
                    "id": 2,
                    "name": "埋点平台",
                    "role": "开发",
                    "years": "2023",
                    "description": [
                        "技术栈：",
                        "Flink",
                        "项目亮点：",
                        "基于 Kafka 采集埋点日志，交由 Flink 实时计算指标",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet"],
                },
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="already present here, rejected",
            ),
            ResumeChange(
                path="personalProjects[1].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="missing in this project, allowed",
            ),
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 1
        second_rows = result["personalProjects"][1]["description"]
        assert second_rows == [
            "技术栈：",
            "Flink",
            "Kafka",
            "项目亮点：",
            "基于 Kafka 采集埋点日志，交由 Flink 实时计算指标",
        ]

    def test_insert_highlight_rejects_same_scenario_paraphrase(self):
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "技术栈：",
                        "Kafka",
                        "项目亮点：",
                        "基于 Kafka 构建订单事件异步流水线，解耦下单与下游履约环节",
                    ],
                    "descriptionStyles": ["label", "plain", "label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="基于 Kafka 搭建订单事件异步消息流水线，解耦下单与履约环节",
                reason="near-paraphrase of the existing Kafka scenario",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_highlight_allows_same_tech_different_scenario(self):
        # The second scenario (埋点日志 -> 数仓看板) is grounded by the project's
        # own duty-row vocabulary, not invented for the technology.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "技术栈：",
                        "Kafka",
                        "项目职责：",
                        "负责客户端埋点上报链路与运营看板的数据准备工作",
                        "项目亮点：",
                        "基于 Kafka 构建订单事件异步流水线，解耦下单与下游履约环节",
                    ],
                    "descriptionStyles": [
                        "label",
                        "plain",
                        "label",
                        "bullet",
                        "label",
                        "bullet",
                    ],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="基于 Kafka 采集客户端埋点日志并实时写入数仓，支撑运营指标看板分析",
                reason="a genuinely different business scenario for the same tech",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0

    def test_insert_highlight_batch_paraphrase_second_rejected(self):
        # First highlight creates the region; the paraphrase in the same batch
        # must be rejected as a repeated tech scenario.
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="基于 Kafka 构建订单事件异步流水线，解耦下单与下游履约环节",
                reason="first scenario",
            ),
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="基于 Kafka 搭建订单事件异步消息流水线，解耦下单与履约环节",
                reason="same scenario, paraphrased",
            ),
        ]
        result, applied, rejected = apply_diffs(
            _resume_with_project_regions(),
            changes,
            allowed_skill_targets=[{"skill": "Kafka"}],
        )
        assert len(applied) == 1
        assert len(rejected) == 1

    def test_insert_row_without_any_targets_is_rejected(self, sample_resume):
        # Legacy diff flow passes no verified targets: no fabrication channel opens.
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="no allow-list at all",
            )
        ]
        result, applied, rejected = apply_diffs(sample_resume, changes)
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_tech_stack_rejects_tech_not_evidenced_in_project(self):
        # Kafka is verified globally but THIS project's text never uses it;
        # a stack row would plant the technology into the project.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "巡检平台",
                    "role": "开发",
                    "years": "2023",
                    "description": [
                        "项目职责：",
                        "负责巡检任务的编排与异常工单的自动分派",
                    ],
                    "descriptionStyles": ["label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": ["Kafka"]},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="global skills list is not project evidence",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1
        assert "技术栈：" not in result["personalProjects"][0]["description"]

    def test_insert_tech_stack_rejects_tech_evidenced_only_in_other_project(self):
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "巡检平台",
                    "role": "开发",
                    "years": "2023",
                    "description": ["负责巡检任务的编排与异常工单的自动分派"],
                },
                {
                    "id": 2,
                    "name": "订单中台",
                    "role": "开发",
                    "years": "2022",
                    "description": ["通过 Kafka 异步通知订单履约事件"],
                },
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="tech_stack",
                original=None,
                value="Kafka",
                reason="evidence lives in the OTHER project only",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_highlight_rejects_generic_capability_filler(self):
        # The project does use Kafka, but the bullet is market-standard filler:
        # its content words （高效/性能/稳定/通信） do not reuse the project's own
        # scenario vocabulary （订单/事件/履约/通知）.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "项目职责：",
                        "基于 Kafka 完成订单履约事件的异步流转与下游通知解耦",
                    ],
                    "descriptionStyles": ["label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="通过 Kafka 实现服务间高效异步通信，提升系统性能与稳定性",
                reason="generic filler any Kafka project could carry",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_highlight_rejects_tech_evidenced_only_in_other_project(self):
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "巡检平台",
                    "role": "开发",
                    "years": "2023",
                    "description": ["负责巡检任务的编排与异常工单的自动分派"],
                },
                {
                    "id": 2,
                    "name": "订单中台",
                    "role": "开发",
                    "years": "2022",
                    "description": ["基于 Kafka 完成订单履约事件的异步流转"],
                },
            ],
            "additional": {"technicalSkills": []},
        }
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value="基于 Kafka 完成巡检告警事件的异步流转与通知",
                reason="Kafka is demonstrated only by the other project",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 0
        assert len(rejected) == 1

    def test_insert_highlight_allows_grounded_new_scenario(self):
        # A second Kafka bullet reusing THIS project's own vocabulary
        # （履约/事件/通知） while describing a distinct mechanism.
        resume = {
            "personalProjects": [
                {
                    "id": 1,
                    "name": "订单中台",
                    "role": "核心开发",
                    "years": "2022 - 2023",
                    "description": [
                        "项目职责：",
                        "基于 Kafka 完成订单履约事件的异步流转与下游通知解耦",
                    ],
                    "descriptionStyles": ["label", "bullet"],
                }
            ],
            "additional": {"technicalSkills": []},
        }
        highlight = "基于 Kafka 对履约事件做失败重试与死信补偿，避免通知环节丢单"
        changes = [
            ResumeChange(
                path="personalProjects[0].description",
                action="insert_row",
                anchor="highlight",
                original=None,
                value=highlight,
                reason="reuses the project's own order-event/notification vocabulary",
            )
        ]
        result, applied, rejected = apply_diffs(
            resume, changes, allowed_skill_targets=[{"skill": "Kafka"}]
        )
        assert len(applied) == 1
        assert len(rejected) == 0
        assert result["personalProjects"][0]["description"][-1] == highlight
