"""Tests for the generated-frontend-rules drift gate.

The gate (scripts/check_generated_rules.py) is pure standard library so the
pre-push hook can run it without Node or PyYAML. It is loaded by file path
because ``scripts/`` is outside the importable ``app`` package.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
GATE_PATH = REPO_ROOT / "scripts" / "check_generated_rules.py"

spec = importlib.util.spec_from_file_location("check_generated_rules", GATE_PATH)
assert spec is not None and spec.loader is not None
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

_TERMS = ["Spring Cloud Alibaba", "Spring Boot", "Java", "C++"]


def _write_artifact(path: Path, terms: list[str]) -> Path:
    payload = {"vocabularies": {"canonical_tech_terms": terms}}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_generated(path: Path, terms: list[str], *, banner: bool = True) -> Path:
    header = "// DO NOT EDIT — generated file.\n" if banner else ""
    body = "\n".join(f"  '{term}'," for term in terms)
    path.write_text(
        f"{header}export const CANONICAL_TERMS = [\n{body}\n] as const;\n",
        encoding="utf-8",
    )
    return path


def test_in_sync_files_report_no_errors(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "parser_rules.json", _TERMS)
    generated = _write_generated(tmp_path / "tech-terms.generated.ts", _TERMS)

    assert gate.check_drift(artifact, generated) == []


def test_hand_edited_term_list_is_drift_with_actionable_fix(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "parser_rules.json", _TERMS)
    drifted_terms = ["Spring Cloud Alibaba", "Spring Boot", "Java", "Rust"]
    generated = _write_generated(
        tmp_path / "tech-terms.generated.ts", drifted_terms
    )

    errors = gate.check_drift(artifact, generated)

    assert any("out of sync" in error for error in errors)
    assert any("Rust" in error and "only in generated" in error for error in errors)
    assert any("C++" in error and "only in backend" in error for error in errors)
    assert any("generate_frontend_rules.py" in error for error in errors)


def test_order_only_drift_is_reported(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "parser_rules.json", _TERMS)
    reordered = [_TERMS[1], _TERMS[0], *_TERMS[2:]]
    generated = _write_generated(tmp_path / "tech-terms.generated.ts", reordered)

    errors = gate.check_drift(artifact, generated)

    assert any("order differs" in error for error in errors)


def test_missing_do_not_edit_banner_is_flagged(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "parser_rules.json", _TERMS)
    generated = _write_generated(
        tmp_path / "tech-terms.generated.ts", _TERMS, banner=False
    )

    errors = gate.check_drift(artifact, generated)

    assert any("DO NOT EDIT" in error for error in errors)


def test_missing_array_declaration_fails_loudly(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "parser_rules.json", _TERMS)
    generated = tmp_path / "tech-terms.generated.ts"
    generated.write_text("export const SOMETHING_ELSE = [];\n", encoding="utf-8")

    errors = gate.check_drift(artifact, generated)

    assert any("CANONICAL_TERMS array declaration not found" in e for e in errors)


def test_artifact_without_vocabulary_fails_loudly(tmp_path: Path) -> None:
    artifact = tmp_path / "parser_rules.json"
    artifact.write_text(json.dumps({"vocabularies": {}}), encoding="utf-8")
    generated = _write_generated(tmp_path / "tech-terms.generated.ts", _TERMS)

    with pytest.raises(ValueError, match="canonical_tech_terms"):
        gate.check_drift(artifact, generated)


def test_shipped_files_are_in_sync() -> None:
    # End-to-end lock over the real committed paths (same call the pre-push
    # gate makes); fails after a YAML edit without regenerating either output.
    errors = gate.check_drift(gate.ARTIFACT_PATH, gate.GENERATED_TECH_TERMS)
    assert errors == []
