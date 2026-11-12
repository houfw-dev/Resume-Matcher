#!/usr/bin/env python3
"""Generate the frontend TypeScript rule modules from shared YAML sources.

The frontend build has no uv/PyYAML, so cross-consumer word tables are
generated into committed TypeScript modules instead of being parsed at build
time. The single human-maintained source is rules/shared_terms.yaml; the same
YAML is merged into the backend's parser_rules.json by
scripts/export_parser_rules.py, so both runtimes bind to one source of truth.

Only PUBLIC, non-confidential word lists are ever exported here. Diagnosis
criterion/QC text and mainstream-stack equivalence notes stay backend-only.

Run from the repo root with ephemeral PyYAML (the YAML is untrusted data):

    uv run --with pyyaml python -I scripts/generate_frontend_rules.py

Drift between the generated files and the shipped backend artifact is blocked
by scripts/check_generated_rules.py (wired into .githooks/pre-push).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_TERMS_PATH = REPO_ROOT / "rules" / "shared_terms.yaml"
GENERATED_DIR = (
    REPO_ROOT / "apps" / "frontend" / "lib" / "generated"
)
TECH_TERMS_OUT = GENERATED_DIR / "tech-terms.generated.ts"

# Must match SHARED_TERM_VOCABULARIES in export_parser_rules.py: every
# whitelisted shared vocabulary has exactly one generated representation.
CANONICAL_TECH_TERMS_KEY = "canonical_tech_terms"

_FILE_HEADER = (
    "// DO NOT EDIT — generated from rules/shared_terms.yaml by\n"
    "// scripts/generate_frontend_rules.py. Regenerate with:\n"
    "//   uv run --with pyyaml python -I scripts/generate_frontend_rules.py\n"
    "// Drift is blocked by scripts/check_generated_rules.py (pre-push gate).\n"
)


def _fail(message: str) -> None:
    raise ValueError(f"{SHARED_TERMS_PATH.relative_to(REPO_ROOT)}: {message}")


def _validate_string_list(name: str, values: Any) -> list[str]:
    """Fail loudly on blank/duplicate/non-string entries (export-time check)."""
    if not isinstance(values, list):
        _fail(f"`{name}` must be a string list")
    seen: set[str] = set()
    for entry in values:
        if not isinstance(entry, str) or not entry.strip():
            _fail(f"`{name}` entries must be non-empty strings")
        if entry in seen:
            _fail(f"`{name}`: duplicate entry {entry!r}")
        seen.add(entry)
    return values


def load_terms() -> list[str]:
    """Load and validate the canonical tech-term table."""
    raw = yaml.safe_load(SHARED_TERMS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _fail("top-level document must be a mapping")
    if CANONICAL_TECH_TERMS_KEY not in raw:
        _fail(f"missing required vocabulary `{CANONICAL_TECH_TERMS_KEY}`")
    unknown = set(raw) - {"spec_version", CANONICAL_TECH_TERMS_KEY}
    if unknown:
        _fail(f"unexpected section(s): {', '.join(sorted(unknown))}")
    return _validate_string_list(
        CANONICAL_TECH_TERMS_KEY, raw[CANONICAL_TECH_TERMS_KEY]
    )


def render_tech_terms_module(terms: list[str]) -> str:
    """Render the generated TS module (Prettier-shaped: 2 spaces, 'es5' comma)."""
    lines = [_FILE_HEADER.rstrip("\n")]
    lines.append("")
    lines.append(
        "// Canonical casing table for technical English terms; consumed by"
    )
    lines.append("// lib/utils/tech-terms.ts. Casing-only, longest-first at use site.")
    lines.append("export const CANONICAL_TERMS = [")
    lines.extend(f"  '{term}'," for term in terms)
    lines.append("] as const;")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    terms = load_terms()
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    rendered = render_tech_terms_module(terms)
    TECH_TERMS_OUT.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {TECH_TERMS_OUT.relative_to(REPO_ROOT)}: "
        f"{len(terms)} canonical terms"
    )


if __name__ == "__main__":
    main()
