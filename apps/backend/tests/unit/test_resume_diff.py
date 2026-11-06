from app.services.improver import calculate_resume_diff


def test_skill_add_remove_case_insensitive() -> None:
    original = {"additional": {"technicalSkills": ["Python", "React"]}}
    improved = {"additional": {"technicalSkills": ["python", "Go"]}}

    summary, changes = calculate_resume_diff(original, improved)

    added = [c for c in changes if c.field_type == "skill" and c.change_type == "added"]
    removed = [
        c for c in changes if c.field_type == "skill" and c.change_type == "removed"
    ]

    assert [c.new_value for c in added] == ["Go"]
    assert [c.original_value for c in removed] == ["React"]
    assert summary.skills_added == 1
    assert summary.skills_removed == 1
    assert summary.high_risk_changes == 1


def test_skill_elaboration_is_one_modified_change() -> None:
    # elaborate_skill turns a bare name into "Name: <=2-line detail"; the user
    # should see one modification, not a removed skill plus an added skill.
    original = {"additional": {"technicalSkills": ["Python", "Redis"]}}
    improved = {
        "additional": {
            "technicalSkills": [
                "Python",
                "Redis：分布式缓存与会话存储，负责热点数据读写、过期策略与高可用设计",
            ]
        }
    }

    summary, changes = calculate_resume_diff(original, improved)

    skill_changes = [c for c in changes if c.field_type == "skill"]
    assert len(skill_changes) == 1
    change = skill_changes[0]
    assert change.change_type == "modified"
    assert change.original_value == "Redis"
    assert change.new_value.startswith("Redis：")
    assert change.confidence == "high"
    assert summary.skills_added == 0
    assert summary.skills_removed == 0


def test_skill_prefix_without_boundary_is_not_elaboration() -> None:
    # "Redis" -> "RedisExporter" is a different technology, not an elaboration:
    # the pairing requires an elaboration boundary right after the bare name.
    original = {"additional": {"technicalSkills": ["Redis"]}}
    improved = {"additional": {"technicalSkills": ["RedisExporter observability tool"]}}

    _summary, changes = calculate_resume_diff(original, improved)

    types = {c.change_type for c in changes if c.field_type == "skill"}
    assert types == {"added", "removed"}


def test_skill_proficiency_sentence_rewrite_is_one_modified_change() -> None:
    # elaborate_skill may rewrite a bare entry as a proficiency-first sentence
    # ("Redis" -> "熟练掌握 Redis 核心数据结构……"); the reviewer should see one
    # modification, not a removed skill plus an added skill.
    new_sentence = "熟练掌握 Redis 核心数据结构，以及缓存与分布式锁的典型用法"
    original = {"additional": {"technicalSkills": ["Python", "Redis"]}}
    improved = {"additional": {"technicalSkills": ["Python", new_sentence]}}

    summary, changes = calculate_resume_diff(original, improved)

    skill_changes = [c for c in changes if c.field_type == "skill"]
    assert len(skill_changes) == 1
    change = skill_changes[0]
    assert change.change_type == "modified"
    assert change.original_value == "Redis"
    assert change.new_value == new_sentence
    assert summary.skills_added == 0
    assert summary.skills_removed == 0


def test_unrelated_new_sentence_is_not_paired_with_removed_skill() -> None:
    # The removed name must appear as a whole bounded term in the new sentence;
    # a sentence about a different technology stays a real remove + add.
    original = {"additional": {"technicalSkills": ["Java"]}}
    improved = {
        "additional": {"technicalSkills": ["熟练掌握 Kubernetes 容器编排与声明式部署"]}
    }

    summary, changes = calculate_resume_diff(original, improved)

    types = {c.change_type for c in changes if c.field_type == "skill"}
    assert types == {"added", "removed"}
    assert summary.skills_added == 1
    assert summary.skills_removed == 1


def test_skill_order_is_ignored() -> None:
    original = {"additional": {"technicalSkills": ["Go", "Python"]}}
    improved = {"additional": {"technicalSkills": ["Python", "Go"]}}

    summary, changes = calculate_resume_diff(original, improved)

    skill_changes = [c for c in changes if c.field_type == "skill"]
    assert skill_changes == []
    assert summary.skills_added == 0
    assert summary.skills_removed == 0


def test_description_modified_count_is_strict() -> None:
    original = {"workExperience": [{"description": ["Built APIs", "Led team"]}]}
    improved = {"workExperience": [{"description": ["Built APIs", "Led squad"]}]}

    summary, changes = calculate_resume_diff(original, improved)

    description_changes = [
        c for c in changes if c.field_type == "description" and c.change_type == "modified"
    ]
    assert len(description_changes) == 1
    assert summary.descriptions_modified == 1


def test_handles_malformed_lists_gracefully() -> None:
    original = {
        "additional": {"technicalSkills": ["Python", {"name": "Go"}, None, 123]},
        "workExperience": [{"description": "Not a list"}],
    }
    improved = {"additional": {"technicalSkills": ["Python"]}}

    summary, changes = calculate_resume_diff(original, improved)

    removed = [
        c for c in changes if c.field_type == "skill" and c.change_type == "removed"
    ]
    assert [c.original_value for c in removed] == ["Go"]
    assert summary.skills_removed == 1


def test_high_risk_skill_addition() -> None:
    original = {"additional": {"technicalSkills": []}}
    improved = {"additional": {"technicalSkills": ["Rust"]}}

    summary, changes = calculate_resume_diff(original, improved)

    assert summary.high_risk_changes == 1
    assert any(
        c.change_type == "added" and c.field_type == "skill" and c.confidence == "high"
        for c in changes
    )


# --- Certification diffs ---


def test_certification_added() -> None:
    original = {"additional": {"certificationsTraining": ["AWS SAA"]}}
    improved = {"additional": {"certificationsTraining": ["AWS SAA", "CKA"]}}

    summary, changes = calculate_resume_diff(original, improved)

    cert_added = [c for c in changes if c.field_type == "certification" and c.change_type == "added"]
    assert len(cert_added) == 1
    assert cert_added[0].new_value == "CKA"
    assert summary.certifications_added == 1


def test_certification_removed() -> None:
    original = {"additional": {"certificationsTraining": ["AWS SAA", "CKA"]}}
    improved = {"additional": {"certificationsTraining": ["AWS SAA"]}}

    summary, changes = calculate_resume_diff(original, improved)

    cert_removed = [c for c in changes if c.field_type == "certification" and c.change_type == "removed"]
    assert len(cert_removed) == 1
    assert cert_removed[0].original_value == "CKA"


# --- Summary diffs ---


def test_summary_modified() -> None:
    original = {"summary": "Original summary text."}
    improved = {"summary": "Improved summary text."}

    summary, changes = calculate_resume_diff(original, improved)

    summary_changes = [c for c in changes if c.field_type == "summary"]
    assert len(summary_changes) == 1
    assert summary_changes[0].change_type == "modified"


def test_summary_added() -> None:
    original = {"summary": ""}
    improved = {"summary": "New summary."}

    summary, changes = calculate_resume_diff(original, improved)

    summary_changes = [c for c in changes if c.field_type == "summary"]
    assert len(summary_changes) == 1
    assert summary_changes[0].change_type == "added"


def test_summary_removed() -> None:
    original = {"summary": "Has summary."}
    improved = {"summary": ""}

    summary, changes = calculate_resume_diff(original, improved)

    summary_changes = [c for c in changes if c.field_type == "summary"]
    assert len(summary_changes) == 1
    assert summary_changes[0].change_type == "removed"


def test_summary_unchanged() -> None:
    original = {"summary": "Same text."}
    improved = {"summary": "Same text."}

    summary, changes = calculate_resume_diff(original, improved)

    summary_changes = [c for c in changes if c.field_type == "summary"]
    assert len(summary_changes) == 0


# --- Entry-level add/remove/modify ---


def test_experience_entry_added() -> None:
    original = {"workExperience": [{"title": "Dev", "company": "A", "years": "2020", "description": []}]}
    improved = {
        "workExperience": [
            {"title": "Dev", "company": "A", "years": "2020", "description": []},
            {"title": "Senior", "company": "B", "years": "2022", "description": []},
        ]
    }

    summary, changes = calculate_resume_diff(original, improved)

    exp_added = [c for c in changes if c.field_type == "experience" and c.change_type == "added"]
    assert len(exp_added) == 1


def test_experience_entry_removed() -> None:
    original = {
        "workExperience": [
            {"title": "Dev", "company": "A", "years": "2020", "description": []},
            {"title": "Senior", "company": "B", "years": "2022", "description": []},
        ]
    }
    improved = {"workExperience": [{"title": "Dev", "company": "A", "years": "2020", "description": []}]}

    summary, changes = calculate_resume_diff(original, improved)

    exp_removed = [c for c in changes if c.field_type == "experience" and c.change_type == "removed"]
    assert len(exp_removed) == 1


def test_experience_entry_modified() -> None:
    original = {"workExperience": [{"title": "Dev", "company": "A", "location": "NY", "years": "2020", "description": []}]}
    improved = {"workExperience": [{"title": "Dev", "company": "A", "location": "Remote", "years": "2020", "description": []}]}

    summary, changes = calculate_resume_diff(original, improved)

    exp_modified = [c for c in changes if c.field_type == "experience" and c.change_type == "modified"]
    assert len(exp_modified) == 1


def test_project_entry_added() -> None:
    original = {"personalProjects": []}
    improved = {"personalProjects": [{"name": "Tool", "role": "Creator", "years": "2021", "description": []}]}

    summary, changes = calculate_resume_diff(original, improved)

    proj_added = [c for c in changes if c.field_type == "project" and c.change_type == "added"]
    assert len(proj_added) == 1


def test_education_entry_added() -> None:
    original = {"education": []}
    improved = {"education": [{"institution": "MIT", "degree": "BS", "years": "2020", "description": None}]}

    summary, changes = calculate_resume_diff(original, improved)

    edu_added = [c for c in changes if c.field_type == "education" and c.change_type == "added"]
    assert len(edu_added) == 1


def test_no_changes_returns_empty() -> None:
    original = {
        "summary": "Same.",
        "workExperience": [{"title": "Dev", "company": "A", "years": "2020", "description": ["Built stuff"]}],
        "additional": {"technicalSkills": ["Python"], "certificationsTraining": []},
    }
    improved = original.copy()

    summary, changes = calculate_resume_diff(original, improved)

    assert summary.total_changes == 0
    assert len(changes) == 0


def test_education_description_change_is_not_duplicated() -> None:
    """Editing only the education description must yield ONE diff, not an extra
    spurious entry-level 'education modified' (regression for the dedup fix)."""
    original = {
        "education": [
            {"institution": "MIT", "degree": "B.S. CS", "years": "2014 - 2018",
             "description": "Graduated with honors"}
        ]
    }
    improved = {
        "education": [
            {"institution": "MIT", "degree": "B.S. CS", "years": "2014 - 2018",
             "description": "Graduated with honors; focus on distributed systems"}
        ]
    }

    _summary, changes = calculate_resume_diff(original, improved)

    education_changes = [c for c in changes if c.field_type == "education"]
    assert len(education_changes) == 1
    assert education_changes[0].field_path == "education[0].description"
    assert education_changes[0].change_type == "modified"


def test_language_add_remove() -> None:
    original = {"additional": {"languages": ["English (Native)"]}}
    improved = {"additional": {"languages": ["English (Native)", "Spanish (Conversational)"]}}

    _summary, changes = calculate_resume_diff(original, improved)

    added = [c for c in changes if c.field_type == "language" and c.change_type == "added"]
    assert [c.new_value for c in added] == ["Spanish (Conversational)"]


def test_language_order_is_ignored() -> None:
    original = {"additional": {"languages": ["English", "Spanish"]}}
    improved = {"additional": {"languages": ["Spanish", "English"]}}

    _summary, changes = calculate_resume_diff(original, improved)

    assert [c for c in changes if c.field_type == "language"] == []


def test_award_add() -> None:
    original = {"additional": {"awards": []}}
    improved = {"additional": {"awards": ["Employee of the Year 2022"]}}

    _summary, changes = calculate_resume_diff(original, improved)

    awards = [c for c in changes if c.field_type == "award" and c.change_type == "added"]
    assert [c.new_value for c in awards] == ["Employee of the Year 2022"]


# --- Project descriptions (fine-tune regression: no identical before/after) ---


def test_project_description_changes_are_diffed_per_line() -> None:
    original = {
        "personalProjects": [
            {
                "name": "AI Toolkit",
                "role": "Core dev",
                "years": "2023",
                "description": ["Old bullet", "Kept bullet"],
            }
        ]
    }
    improved = {
        "personalProjects": [
            {
                "name": "AI Toolkit",
                "role": "Core dev",
                "years": "2023",
                "description": ["New bullet", "Kept bullet"],
            }
        ]
    }

    summary, changes = calculate_resume_diff(original, improved)

    description_changes = [c for c in changes if c.field_type == "description"]
    assert len(description_changes) == 1
    assert description_changes[0].field_path == "personalProjects[0].description"
    assert description_changes[0].original_value == "Old bullet"
    assert description_changes[0].new_value == "New bullet"
    assert summary.descriptions_modified == 1
    # No entry-level "project modified" card whose before/after are the same.
    assert [c for c in changes if c.field_type == "project"] == []


def test_style_only_project_change_emits_nothing() -> None:
    original = {
        "personalProjects": [
            {
                "name": "P",
                "role": "R",
                "years": "2023",
                "description": ["Did a thing"],
                "descriptionStyles": ["bullet"],
            }
        ]
    }
    improved = {
        "personalProjects": [
            {
                "name": "P",
                "role": "R",
                "years": "2023",
                "description": ["Did a thing"],
                "descriptionStyles": ["label"],
            }
        ]
    }

    summary, changes = calculate_resume_diff(original, improved)

    assert changes == []
    assert summary.total_changes == 0


def test_entry_id_change_is_not_a_diff() -> None:
    original = {
        "workExperience": [
            {"title": "Dev", "company": "A", "years": "2020", "description": [], "id": 1}
        ]
    }
    improved = {
        "workExperience": [
            {"title": "Dev", "company": "A", "years": "2020", "description": [], "id": 7}
        ]
    }

    _summary, changes = calculate_resume_diff(original, improved)

    assert changes == []


def test_entry_modified_card_surfaces_hidden_scalar_fields() -> None:
    """A change to a field absent from the header line (location) must still
    produce a card whose before/after visibly differ."""
    original = {
        "workExperience": [
            {
                "title": "Dev",
                "company": "A",
                "location": "NY",
                "years": "2020",
                "description": [],
            }
        ]
    }
    improved = {
        "workExperience": [
            {
                "title": "Dev",
                "company": "A",
                "location": "Remote",
                "years": "2020",
                "description": [],
            }
        ]
    }

    _summary, changes = calculate_resume_diff(original, improved)

    modified = [c for c in changes if c.field_type == "experience"]
    assert len(modified) == 1
    assert "location: NY" in (modified[0].original_value or "")
    assert "location: Remote" in (modified[0].new_value or "")
