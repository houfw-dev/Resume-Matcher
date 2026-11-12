#!/usr/bin/env python3
"""Export the parser rule YAML source into the shipped JSON artifact.

The YAML (rules/parser_rules.yaml) is the human-maintained source of truth for
the resume parser's declarative data (thresholds, vocabularies/aliases, regex
strings); the JSON it produces (apps/backend/app/services/parser_rules.json)
is the only artifact the backend reads at runtime. Cross-consumer word tables
in rules/shared_terms.yaml (canonical_tech_terms) are merged into the
artifact's ``vocabularies`` section — the same YAML also feeds
scripts/generate_frontend_rules.py. PyYAML is deliberately NOT a runtime
dependency — the production loader (app/services/parser_rules.py) reads plain
JSON and re-runs the same fail-fast validation with Pydantic.

Only declarative data belongs in the YAML. The 19-step post-processing
pipeline order, region state machines, date disambiguation scoring, container
validation, the ResumeData schema and the CJK compatibility glyph tables stay
in Python — they are structural contracts, not configurable data.

Run from the repo root with ephemeral PyYAML (the YAML is untrusted data):

    uv run --with pyyaml python -I scripts/export_parser_rules.py

Verify the output after regenerating:

    git diff --stat apps/backend/app/services/parser_rules.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = REPO_ROOT / "rules" / "parser_rules.yaml"
# Shared cross-consumer word tables (also the source for the frontend code
# generator); merged into the artifact's `vocabularies` section below.
SHARED_TERMS_PATH = REPO_ROOT / "rules" / "shared_terms.yaml"
OUT_PATH = REPO_ROOT / "apps" / "backend" / "app" / "services" / "parser_rules.json"

# Vocabularies injected from rules/shared_terms.yaml. Keep in sync with
# scripts/generate_frontend_rules.py — the same YAML feeds both the backend
# artifact and the generated TypeScript module.
SHARED_TERM_VOCABULARIES = frozenset({"canonical_tech_terms"})

REQUIRED_SECTIONS = ("spec_version", "thresholds", "vocabularies", "patterns")

# Keep the flag whitelist identical to app/services/parser_rules.py. The parser
# only ever needs these four; refusing unknown names fails loudly at export
# time instead of silently compiling a different regex at runtime.
PATTERN_FLAGS: dict[str, int] = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "UNICODE": re.UNICODE,
}

_SCALAR_TYPES = (str, int, float)

# Vocabularies whose string leaves are regex fragments rather than plain
# words; each leaf must compile on its own. The composed named-group regex is
# still built in parser.py (composition is algorithm, not data). Keep this set
# identical to app/services/parser_rules.py — the ephemeral export env cannot
# import the runtime loader.
REGEX_LEAF_VOCABULARIES = frozenset({"header_field_labels"})


def _fail(message: str) -> None:
    raise ValueError(f"{YAML_PATH.relative_to(REPO_ROOT)}: {message}")


def validate_thresholds(section: Any) -> None:
    if not isinstance(section, dict):
        _fail("`thresholds` must be a mapping of name -> scalar")
    for name, value in section.items():
        if not isinstance(name, str) or not name.strip():
            _fail(f"thresholds.{name!r}: threshold names must be non-empty strings")
        # bool is an int subclass; reject it explicitly so a YAML `yes/no`
        # typo cannot masquerade as a numeric threshold.
        if isinstance(value, bool) or not isinstance(value, _SCALAR_TYPES):
            _fail(
                f"thresholds.{name}: scalar value required (str/int/float), "
                f"got {type(value).__name__}"
            )


def validate_vocabularies(section: Any) -> None:
    if not isinstance(section, dict):
        _fail("`vocabularies` must be a mapping of name -> list or mapping")
    for name, value in section.items():
        if not isinstance(name, str) or not name.strip():
            _fail(f"vocabularies.{name!r}: vocabulary names must be non-empty strings")
        if isinstance(value, list):
            _validate_string_list(f"vocabularies.{name}", value)
            if name in REGEX_LEAF_VOCABULARIES:
                for entry in value:
                    _compile_regex_leaf(f"vocabularies.{name}.{entry}", entry)
        elif isinstance(value, dict):
            for key, inner in value.items():
                if not isinstance(key, str) or not key.strip():
                    _fail(f"vocabularies.{name}: mapping keys must be non-empty strings")
                if isinstance(inner, list):
                    _validate_string_list(f"vocabularies.{name}.{key}", inner)
                    if name in REGEX_LEAF_VOCABULARIES:
                        for entry in inner:
                            _compile_regex_leaf(
                                f"vocabularies.{name}.{key}", entry
                            )
                elif not isinstance(inner, str) or not inner.strip():
                    _fail(
                        f"vocabularies.{name}.{key}: value must be a non-empty "
                        "string or a list of non-empty strings"
                    )
                elif name in REGEX_LEAF_VOCABULARIES:
                    _compile_regex_leaf(f"vocabularies.{name}.{key}", inner)
        else:
            _fail(f"vocabularies.{name}: value must be a list or a mapping")


def _compile_regex_leaf(locator: str, pattern: str) -> None:
    """Compile one regex-leaf vocabulary entry, failing loudly on bad patterns."""
    try:
        re.compile(pattern)
    except re.error as exc:
        _fail(f"{locator}: regex leaf does not compile: {exc}")


def _validate_string_list(locator: str, values: list[Any]) -> None:
    seen: set[str] = set()
    for entry in values:
        if not isinstance(entry, str) or not entry.strip():
            _fail(f"{locator}: entries must be non-empty strings")
        if entry in seen:
            _fail(f"{locator}: duplicate entry {entry!r}")
        seen.add(entry)


def validate_patterns(section: Any) -> None:
    if not isinstance(section, dict):
        _fail("`patterns` must be a mapping of name -> {pattern, flags?}")
    for name, spec in section.items():
        if not isinstance(name, str) or not name.strip():
            _fail(f"patterns.{name!r}: pattern names must be non-empty strings")
        if not isinstance(spec, dict):
            _fail(f"patterns.{name}: entry must be a mapping with a `pattern` string")
        pattern = spec.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            _fail(f"patterns.{name}.pattern: must be a non-empty string")
        flags = spec.get("flags", [])
        if not isinstance(flags, list) or any(not isinstance(f, str) for f in flags):
            _fail(f"patterns.{name}.flags: must be a list of flag-name strings")
        unknown = [flag for flag in flags if flag not in PATTERN_FLAGS]
        if unknown:
            _fail(
                f"patterns.{name}.flags: unknown flags {unknown}; "
                f"allowed: {sorted(PATTERN_FLAGS)}"
            )
        try:
            compiled_flags = 0
            for flag in flags:
                compiled_flags |= PATTERN_FLAGS[flag]
            re.compile(pattern, compiled_flags)
        except re.error as exc:
            _fail(f"patterns.{name}.pattern does not compile: {exc}")
        if set(spec) - {"pattern", "flags"}:
            _fail(f"patterns.{name}: only `pattern` and `flags` keys are allowed")


def load_shared_terms() -> dict[str, list[str]]:
    """Load the cross-consumer shared word tables (rules/shared_terms.yaml).

    Only the whitelisted vocabulary names are accepted; every value must be a
    plain string list so the regular :func:`validate_vocabularies` pass can
    treat the merged result exactly like a parser-native vocabulary.
    """
    raw = yaml.safe_load(SHARED_TERMS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _fail(f"{SHARED_TERMS_PATH.name}: top-level document must be a mapping")
    vocabularies = {
        key: value
        for key, value in raw.items()
        if key not in ("spec_version",)
    }
    unknown = set(vocabularies) - SHARED_TERM_VOCABULARIES
    if unknown:
        _fail(
            f"{SHARED_TERMS_PATH.name}: unlisted vocabulary section(s) "
            f"{', '.join(sorted(unknown))}; add the name to "
            "SHARED_TERM_VOCABULARIES first"
        )
    missing = SHARED_TERM_VOCABULARIES - set(vocabularies)
    if missing:
        _fail(
            f"{SHARED_TERMS_PATH.name}: missing required vocabulary "
            f"{', '.join(sorted(missing))}"
        )
    for name, value in vocabularies.items():
        if not isinstance(value, list):
            _fail(f"{SHARED_TERMS_PATH.name}: `{name}` must be a string list")
    return vocabularies


def export() -> dict[str, Any]:
    raw = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        _fail("top-level document must be a mapping")

    missing = [section for section in REQUIRED_SECTIONS if section not in raw]
    if missing:
        _fail(f"missing required section(s): {', '.join(missing)}")
    unexpected = set(raw) - set(REQUIRED_SECTIONS)
    if unexpected:
        _fail(f"unexpected top-level section(s): {', '.join(sorted(unexpected))}")

    spec_version = raw["spec_version"]
    if not isinstance(spec_version, str) or not spec_version.strip():
        _fail("`spec_version` must be a non-empty string")

    validate_thresholds(raw["thresholds"])
    validate_patterns(raw["patterns"])

    # Merge the shared cross-consumer tables into the parser vocabularies so
    # the backend binds to one runtime artifact; collisions fail loudly.
    shared_vocabularies = load_shared_terms()
    collisions = set(raw["vocabularies"]) & set(shared_vocabularies)
    if collisions:
        _fail(
            "vocabulary name(s) duplicated across parser_rules.yaml and "
            f"shared_terms.yaml: {', '.join(sorted(collisions))}"
        )
    vocabularies = {**raw["vocabularies"], **shared_vocabularies}
    validate_vocabularies(vocabularies)

    return {
        "spec_version": spec_version,
        "thresholds": raw["thresholds"],
        "vocabularies": vocabularies,
        "patterns": raw["patterns"],
    }


def main() -> None:
    payload = export()
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    pattern_count = len(payload["patterns"])
    vocabulary_count = len(payload["vocabularies"])
    threshold_count = len(payload["thresholds"])
    print(
        f"wrote {OUT_PATH.relative_to(REPO_ROOT)}: spec_version={payload['spec_version']}, "
        f"{threshold_count} thresholds, {vocabulary_count} vocabularies, {pattern_count} patterns"
    )


if __name__ == "__main__":
    main()
