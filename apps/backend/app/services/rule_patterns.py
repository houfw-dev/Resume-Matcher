"""Shared regex-spec validation for the externalized rule artifacts.

Both the parser rules (``parser_rules.json``) and the diagnosis rules
(``diagnosis_rules.json`` parameters/vocabularies sections) externalize regex
strings with the same flag whitelist and the same fail-fast contract, so the
Pydantic spec lives here once. The export scripts under ``scripts/`` cannot
import application code (they run in an ephemeral uv environment at the repo
root) and deliberately mirror this whitelist in plain Python — keep the two
sides in sync when adding a flag.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Narrow on purpose: an unknown flag name must fail loudly instead of being
# silently ignored. Mirrored by scripts/export_*_rules.py.
PATTERN_FLAGS: dict[str, int] = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "UNICODE": re.UNICODE,
}


class PatternSpec(BaseModel):
    """One externalized regex: source string plus whitelisted flag names."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(min_length=1)
    flags: list[str] = Field(default_factory=list)

    @field_validator("flags")
    @classmethod
    def _check_flag_names(cls, flags: list[str]) -> list[str]:
        unknown = [name for name in flags if name not in PATTERN_FLAGS]
        if unknown:
            raise ValueError(
                f"unknown regex flags {unknown}; allowed: {sorted(PATTERN_FLAGS)}"
            )
        return flags

    def compile(self) -> re.Pattern[str]:
        """Compile the source pattern with its declared flags."""
        compiled_flags = 0
        for name in self.flags:
            compiled_flags |= PATTERN_FLAGS[name]
        return re.compile(self.pattern, compiled_flags)


def compile_specs(specs: dict[str, PatternSpec]) -> dict[str, re.Pattern[str]]:
    """Compile a mapping of specs, failing loudly on the first bad pattern."""
    compiled: dict[str, re.Pattern[str]] = {}
    for name, spec in specs.items():
        try:
            compiled[name] = spec.compile()
        except re.error as exc:
            raise ValueError(f"pattern {name!r} does not compile: {exc}") from exc
    return compiled


def validate_string_list(locator: str, values: list[str]) -> None:
    """Reject blank and duplicate vocabulary entries."""
    seen: set[str] = set()
    for entry in values:
        if not entry.strip():
            raise ValueError(f"{locator}: blank entries are not allowed")
        if entry in seen:
            raise ValueError(f"{locator}: duplicate entry {entry!r}")
        seen.add(entry)
