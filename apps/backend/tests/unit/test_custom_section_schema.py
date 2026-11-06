"""Custom-section text must keep the source line structure.

Weak models return a "text" block as a JSON array of lines (or nested
fragments). The schema used to join fragments with spaces, which collapsed
every source line into one paragraph and silently changed the original
formatting on import. The renderer numbers lines on "\\n", so list fragments
must be newline-joined while plain strings keep their internal newlines.
"""

from app.schemas import ResumeData


def _custom_text(payload: object) -> str | None:
    dumped = ResumeData.model_validate(
        {"customSections": {"volunteer": {"sectionType": "text", "text": payload}}}
    ).model_dump()
    return dumped["customSections"]["volunteer"]["text"]


def test_string_text_keeps_internal_newlines() -> None:
    assert _custom_text("第一点\n第二点\n第三点") == "第一点\n第二点\n第三点"


def test_list_of_lines_is_newline_joined_not_space_joined() -> None:
    # This is the failure mode: the model emitted one string per source line.
    assert _custom_text(["第一点", "第二点"]) == "第一点\n第二点"


def test_nested_line_fragments_are_newline_joined() -> None:
    assert _custom_text([{"text": "第一点"}, {"text": "第二点"}]) == "第一点\n第二点"


def test_blank_text_normalizes_to_none() -> None:
    assert _custom_text("   ") is None
    assert _custom_text(["  ", ""]) is None
    assert _custom_text(None) is None


def test_string_list_section_still_splits_lines() -> None:
    dumped = ResumeData.model_validate(
        {
            "customSections": {
                "honors": {
                    "sectionType": "stringList",
                    "strings": "证书 A\n证书 B",
                }
            }
        }
    ).model_dump()
    assert dumped["customSections"]["honors"]["strings"] == ["证书 A", "证书 B"]
