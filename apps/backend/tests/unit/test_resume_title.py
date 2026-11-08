"""Unit tests for the deterministic tailored-resume title builder.

Tailored resumes are titled ``姓名-岗位名称`` without an LLM call so model
prompt-echo text (e.g. "Max 60 chars. Output one line.") can never be stored
as a title.
"""

from app.services.cover_letter import build_resume_title


def test_name_plus_jd_role_uses_hyphen_convention() -> None:
    data = {"personalInfo": {"name": "王浩", "title": "Java开发工程师"}}
    keywords = {"role": "资深Java工程师", "company": "Acme"}
    assert build_resume_title(data, keywords, "zh") == "王浩-资深Java工程师"


def test_jd_role_takes_precedence_over_resume_target() -> None:
    data = {"personalInfo": {"name": "王浩", "title": "后端开发"}}
    keywords = {"role": "Platform Engineer"}
    assert build_resume_title(data, keywords, "en") == "王浩-Platform Engineer"


def test_falls_back_to_first_slash_segment_of_personal_target() -> None:
    data = {
        "personalInfo": {"name": "邹利平", "title": "Java 开发/资深开发/技术经理"}
    }
    assert build_resume_title(data, None, "zh") == "邹利平-Java 开发"


def test_full_width_slash_is_also_a_target_separator() -> None:
    data = {"personalInfo": {"name": "邹利平", "title": "Java 开发／资深开发"}}
    assert build_resume_title(data, {}, "zh") == "邹利平-Java 开发"


def test_blank_jd_role_falls_back_to_personal_target() -> None:
    data = {"personalInfo": {"name": "王浩", "title": "后端开发"}}
    assert build_resume_title(data, {"role": "  "}, "zh") == "王浩-后端开发"


def test_name_only_when_no_role_available() -> None:
    data = {"personalInfo": {"name": "王浩"}}
    assert build_resume_title(data, None, "zh") == "王浩"


def test_role_only_when_name_missing() -> None:
    data = {"personalInfo": {"title": "后端开发"}}
    assert build_resume_title(data, {"role": "Java Engineer"}, "en") == (
        "Java Engineer"
    )


def test_localized_fallback_when_neither_fact_exists() -> None:
    assert build_resume_title({}, None, "zh") == "定制简历"
    assert build_resume_title({"personalInfo": {}}, None, "en") == "Tailored Resume"
    # An unknown language code falls back to the English generic title.
    assert build_resume_title({}, None, "xx") == "Tailored Resume"


def test_whitespace_and_newlines_are_collapsed() -> None:
    data = {"personalInfo": {"name": "王\n浩", "title": "Java\n开发"}}
    keywords = {"role": "Java\n工程师"}
    assert build_resume_title(data, keywords, "zh") == "王 浩-Java 工程师"


def test_non_string_and_non_mapping_inputs_do_not_crash() -> None:
    assert build_resume_title({}, None, "zh") == "定制简历"  # type: ignore[arg-type]
    assert build_resume_title(
        {"personalInfo": {"name": 123, "title": None}}, {"role": 456}, "en"
    ) == "Tailored Resume"
    assert build_resume_title("not-a-mapping", None, "en") == "Tailored Resume"  # type: ignore[arg-type]


def test_title_is_capped_at_80_chars_without_dangling_dash() -> None:
    long_role = "工程师" * 40  # 120 code points
    data = {"personalInfo": {"name": "王浩", "title": long_role}}
    title = build_resume_title(data, None, "zh")
    assert len(title) <= 80
    assert not title.endswith(("-", " "))
    assert title.startswith("王浩-")


def test_builder_never_invokes_a_model_and_only_joins_facts() -> None:
    # The builder is synchronous: given the same facts it always returns the
    # same string, and the old LLM title prompt ("Max 60 chars. Output one
    # line.") has no code path into the result.
    data = {"personalInfo": {"name": "王浩", "title": "后端开发"}}
    first = build_resume_title(data, {"role": "Java 工程师"}, "zh")
    second = build_resume_title(data, {"role": "Java 工程师"}, "zh")
    assert first == second == "王浩-Java 工程师"
    assert "Max 60 chars" not in first
