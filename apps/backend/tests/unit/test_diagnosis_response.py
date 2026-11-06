"""Unit tests for diagnosis LLM-response tolerance.

Weak/local judge models have been observed to:

* emit checklist ids as numeric strings ("20" instead of 20);
* answer ids outside the assigned set (objective/gated items owned elsewhere);
* stop mid-array, leaving unbalanced JSON braces on every retry.

The validator coerces/drops what it can and the salvager recovers complete
item objects from truncated JSON so missing items can default to partial with
a warning instead of failing the whole diagnosis with HTTP 500.
"""

import pytest

from app.services.diagnosis import (
    _build_validator,
    salvage_diagnosis_response,
)


def _entry(item_id: object, rating: str = "partial") -> dict:
    return {"id": item_id, "rating": rating, "evidence": f"item {item_id}", "suggestion": "fix"}


class TestDiagnosisResponseValidator:
    def test_coerces_numeric_string_ids(self) -> None:
        validate = _build_validator(frozenset({18, 20}))
        result = validate({"items": [_entry("20"), _entry(18)]})
        assert [item["id"] for item in result["items"]] == [20, 18]
        assert all(isinstance(item["id"], int) for item in result["items"])

    def test_drops_out_of_scope_ids(self) -> None:
        # The model over-answered an objective item (id 4) and invented 99.
        validate = _build_validator(frozenset({18}))
        result = validate({"items": [_entry(4), _entry(18, "nonconform"), _entry(99)]})
        assert [item["id"] for item in result["items"]] == [18]

    def test_drops_invalid_rating_and_non_int_id(self) -> None:
        validate = _build_validator(frozenset({1, 2}))
        result = validate(
            {
                "items": [
                    _entry(1, "bogus-rating"),
                    _entry("abc"),
                    _entry(2),
                ]
            }
        )
        assert [item["id"] for item in result["items"]] == [2]

    def test_deduplicates_repeated_ids(self) -> None:
        validate = _build_validator(frozenset({1}))
        result = validate({"items": [_entry(1, "partial"), _entry("1", "conform")]})
        assert len(result["items"]) == 1
        assert result["items"][0]["rating"] == "partial"

    def test_rejects_when_no_usable_items_remains(self) -> None:
        validate = _build_validator(frozenset({1}))
        with pytest.raises(ValueError, match="no usable items"):
            validate({"items": [_entry(2), _entry(3)]})
        with pytest.raises(ValueError, match="no items list"):
            validate({})

    def test_conform_silencing_is_not_validators_job(self) -> None:
        # Validator only normalizes shape; empty-text policy lives in the merge.
        validate = _build_validator(frozenset({1}))
        result = validate(
            {"items": [{"id": 1, "rating": "conform", "evidence": "", "suggestion": ""}]}
        )
        assert result["items"][0]["id"] == 1


class TestSalvageDiagnosisResponse:
    def test_recovers_complete_items_from_truncated_array(self) -> None:
        content = (
            '{"items": [\n'
            '{"id": 2, "rating": "partial", "evidence": "a", "suggestion": "x"},\n'
            '{"id": 3, "rating": "nonconform", "evidence": "b", "sugge'
        )
        salvaged = salvage_diagnosis_response(content)
        assert salvaged is not None
        assert [item["id"] for item in salvaged["items"]] == [2]

    def test_handles_markdown_fenced_truncation(self) -> None:
        content = (
            '```json\n{"items": ['
            '{"id": 5, "rating": "conform", "evidence": "", "suggestion": ""}]\n'
        )
        salvaged = salvage_diagnosis_response(content)
        assert salvaged is not None
        assert salvaged["items"][0]["id"] == 5

    def test_ignores_braces_inside_json_strings(self) -> None:
        content = (
            '{"items": [{"id": 7, "rating": "partial", '
            '"evidence": "fix the } brace { layout", "suggestion": "s"},'
            '{"id": 8, "rating": "partial", "evid'
        )
        salvaged = salvage_diagnosis_response(content)
        assert salvaged is not None
        assert [item["id"] for item in salvaged["items"]] == [7]
        assert salvaged["items"][0]["evidence"] == "fix the } brace { layout"

    def test_no_complete_item_returns_none(self) -> None:
        assert salvage_diagnosis_response('{"items": [{"id": 1, "ratin') is None
        assert salvage_diagnosis_response("plain text without json") is None
        assert salvage_diagnosis_response('{"summary": "no items key"}') is None
