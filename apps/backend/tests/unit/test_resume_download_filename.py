"""Unit tests for resume PDF/DOCX download filename construction.

Both downloads are named 姓名-年龄-工作年限-学历-求职意向; the same helper
builds the stem for the RFC 5987 Content-Disposition headers.
"""

from urllib.parse import unquote

from app.routers.resumes import _resume_download_headers, _resume_download_stem


def test_stem_joins_all_five_facts_in_order() -> None:
    data = {
        "personalInfo": {
            "name": "王浩",
            "age": "28岁",
            "workYears": "5年",
            "educationLevel": "硕士",
            "title": "Java开发工程师",
        }
    }
    assert _resume_download_stem(data) == "王浩-28岁-5年-硕士-Java开发工程师"


def test_stem_skips_missing_and_blank_facts_without_dangling_dashes() -> None:
    data = {
        "personalInfo": {
            "name": "王浩",
            "age": "  ",
            "workYears": None,
            "educationLevel": "",
            "title": "后端开发",
        }
    }
    assert _resume_download_stem(data) == "王浩-后端开发"


def test_stem_falls_back_to_latest_education_degree() -> None:
    data = {
        "personalInfo": {"name": "王浩", "title": "工程师"},
        "education": [
            {"id": 2, "degree": "硕士"},
            {"id": 1, "degree": "本科"},
        ],
    }
    assert _resume_download_stem(data) == "王浩-硕士-工程师"


def test_stem_prefers_personal_info_education_level() -> None:
    data = {
        "personalInfo": {"name": "王浩", "educationLevel": "本科", "title": "工程师"},
        "education": [{"id": 1, "degree": "硕士"}],
    }
    assert _resume_download_stem(data) == "王浩-本科-工程师"


def test_stem_replaces_filename_illegal_characters() -> None:
    data = {"personalInfo": {"name": "王浩", "title": "Java/大数据 | 架构师"}}
    assert _resume_download_stem(data) == "王浩-Java-大数据 - 架构师"


def test_stem_trims_each_fact() -> None:
    data = {
        "personalInfo": {"name": "  王浩 ", "workYears": " 5年 ", "title": None}
    }
    assert _resume_download_stem(data) == "王浩-5年"


def test_stem_returns_empty_without_any_fact() -> None:
    assert _resume_download_stem({}) == ""
    assert _resume_download_stem({"personalInfo": {}}) == ""
    assert _resume_download_stem(None) == ""
    assert _resume_download_stem("not a dict") == ""


def test_stem_ignores_non_string_values() -> None:
    data = {"personalInfo": {"name": 123, "title": ["工程师"]}}
    assert _resume_download_stem(data) == ""


def test_headers_carry_utf8_filename_and_ascii_fallback() -> None:
    headers = _resume_download_headers("abcdef12-3456", "王浩-28岁-5年-硕士-后端开发", "pdf")
    disposition = headers["Content-Disposition"]
    assert disposition.startswith('attachment; filename="resume-abcdef12.pdf"; ')
    utf8_part = disposition.split("filename*=UTF-8''")[1]
    assert unquote(utf8_part) == "王浩-28岁-5年-硕士-后端开发.pdf"


def test_headers_fallback_when_stem_empty() -> None:
    headers = _resume_download_headers("abcdef12-3456", "", "docx")
    assert headers["Content-Disposition"] == 'attachment; filename="resume-abcdef12.docx"'
