#!/usr/bin/env python3
"""Drift gate between generated frontend rules and the backend JSON artifact.

Pure standard library — the pre-push hook runs ``python3`` without PyYAML.
The shipped ``apps/backend/app/services/parser_rules.json`` is the validated
product of both YAML sources (rules/parser_rules.yaml +
rules/shared_terms.yaml, merged by export_parser_rules.py), so it is the
reference the generated TypeScript must match.

Checks:

1. ``tech-terms.generated.ts`` carries the DO NOT EDIT banner.
2. Its ``CANONICAL_TERMS`` list equals the artifact's
   ``vocabularies.canonical_tech_terms`` — same entries, same order.

Exit 0 when in sync, 1 with actionable output on drift. Run manually:

    python3 scripts/check_generated_rules.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = (
    REPO_ROOT / "apps" / "backend" / "app" / "services" / "parser_rules.json"
)
GENERATED_TECH_TERMS = (
    REPO_ROOT / "apps" / "frontend" / "lib" / "generated" / "tech-terms.generated.ts"
)

DO_NOT_EDIT_MARKER = "DO NOT EDIT"
_TERM_LINE_RE = re.compile(r"^\s*'((?:[^'\\]|\\.)*)',?\s*$")
_ARRAY_BLOCK_RE = re.compile(
    r"export const CANONICAL_TERMS = \[(.*?)\] as const;",
    re.DOTALL,
)


def extract_generated_terms(ts_text: str) -> list[str]:
    """Parse the term literals out of the generated TS module.

    Raises ValueError when the array declaration is missing or a line inside
    it is not a single-quoted string literal.
    """
    block = _ARRAY_BLOCK_RE.search(ts_text)
    if block is None:
        raise ValueError("CANONICAL_TERMS array declaration not found")
    terms: list[str] = []
    for line in block.group(1).splitlines():
        if not line.strip():
            continue
        match = _TERM_LINE_RE.match(line)
        if match is None:
            raise ValueError(f"unparsable term line: {line.strip()!r}")
        terms.append(match.group(1))
    return terms


def load_artifact_terms(artifact_path: Path) -> list[str]:
    """Read the reference term list from the shipped parser rules JSON."""
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    try:
        terms = payload["vocabularies"]["canonical_tech_terms"]
    except KeyError as exc:
        raise ValueError(
            "artifact is missing vocabularies.canonical_tech_terms"
        ) from exc
    if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
        raise ValueError("artifact canonical_tech_terms must be a string list")
    return terms


def _display_path(path: Path) -> str:
    """Repo-relative path when inside the repo, absolute path otherwise."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_drift(artifact_path: Path, generated_path: Path) -> list[str]:
    """Return human-readable drift errors (empty list means everything matches)."""
    errors: list[str] = []
    display = _display_path(generated_path)
    ts_text = generated_path.read_text(encoding="utf-8")
    if DO_NOT_EDIT_MARKER not in ts_text:
        errors.append(
            f"{display}: missing the DO NOT EDIT banner — hand-editing a "
            "generated file is not allowed"
        )
    try:
        generated_terms = extract_generated_terms(ts_text)
    except ValueError as exc:
        errors.append(f"{display}: {exc}")
        return errors
    reference_terms = load_artifact_terms(artifact_path)

    if generated_terms != reference_terms:
        errors.append(
            "tech-terms.generated.ts is out of sync with parser_rules.json "
            f"({len(generated_terms)} generated vs {len(reference_terms)} "
            "reference terms)"
        )
        generated_set, reference_set = set(generated_terms), set(reference_terms)
        only_generated = [t for t in generated_terms if t not in reference_set]
        only_reference = [t for t in reference_terms if t not in generated_set]
        if only_generated:
            errors.append(f"  only in generated TS: {only_generated}")
        if only_reference:
            errors.append(f"  only in backend artifact: {only_reference}")
        if not only_generated and not only_reference:
            errors.append("  entries match but their order differs")
        errors.append(
            "  fix: uv run --with pyyaml python -I "
            "scripts/generate_frontend_rules.py"
        )
    return errors


def main() -> int:
    """CLI entry point: print every drift error and return the exit code."""
    errors = check_drift(ARTIFACT_PATH, GENERATED_TECH_TERMS)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("generated frontend rules are in sync with parser_rules.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
