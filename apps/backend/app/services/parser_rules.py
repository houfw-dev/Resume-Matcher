"""Typed loader for the externalized resume-parser rule artifact.

The parser's declarative data (numeric thresholds, vocabulary/alias lists,
regex strings) is maintained in ``rules/parser_rules.yaml`` and exported into
``parser_rules.json`` next to this module. Runtime code never reads the YAML —
PyYAML is an export-time-only dependency; the JSON is the versioned artifact
the app ships with, validated here with Pydantic and cached via ``lru_cache``.

Validation is deliberately loud and happens at load time:

* unknown top-level sections or pattern keys are rejected (``extra="forbid"``);
* every regex string is compiled once, so a bad pattern fails the loader
  instead of surfacing deep inside the 4k-line parser;
* vocabulary lists reject blank and duplicate entries.

Only declarative data lives in the artifact. The post-processing pipeline
order, region state machines, date disambiguation scoring, container
validation, the ``ResumeData`` schema and the CJK glyph tables are structural
contracts and stay in Python. Like ``config_cache`` and ``diagnosis_rules``,
this assumes a single worker process and has no runtime hot-reload story:
artifacts ship with releases and the cache lives for the process lifetime.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.rule_patterns import (
    PATTERN_FLAGS,
    PatternSpec,
    compile_specs,
    validate_string_list,
)

_RULES_PATH = Path(__file__).with_name("parser_rules.json")

# A vocabulary value is either an ordered word list or an alias/canonical-name
# mapping whose leaves are strings or string lists.
VocabularyValue = list[str] | dict[str, str | list[str]]

# Vocabularies whose string leaves are regex fragments rather than plain words.
# The composed named-group regex itself is built in parser.py; here we only
# guarantee every fragment compiles at load time. Keep identical to the
# REGEX_LEAF_VOCABULARIES set in scripts/export_parser_rules.py (the export
# environment cannot import app code, so the two lists are synced by hand).
REGEX_LEAF_VOCABULARIES = frozenset({"header_field_labels"})


class ParserRules(BaseModel):
    """Typed view over the whole parser rule artifact (no raw dicts)."""

    model_config = ConfigDict(extra="forbid")

    spec_version: str = Field(min_length=1)
    thresholds: dict[str, int | float | str]
    vocabularies: dict[str, VocabularyValue]
    patterns: dict[str, PatternSpec]

    @field_validator("spec_version")
    @classmethod
    def _non_blank_spec_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("spec_version must be a non-blank string")
        return value

    @field_validator("thresholds", mode="before")
    @classmethod
    def _reject_boolean_thresholds(cls, value: Any) -> Any:
        # Runs before lax coercion: pydantic otherwise turns True into 1, so an
        # after-validator could no longer see that an unquoted YAML yes/no was
        # ever a bool.
        if isinstance(value, dict):
            for name, item in value.items():
                if isinstance(item, bool):
                    raise ValueError(
                        f"thresholds.{name}: bool is not allowed (use str/int/float)"
                    )
        return value

    @model_validator(mode="after")
    def _validate_vocabularies_and_patterns(self) -> "ParserRules":
        for name, value in self.vocabularies.items():
            if isinstance(value, list):
                validate_string_list(f"vocabularies.{name}", value)
                if name in REGEX_LEAF_VOCABULARIES:
                    for entry in value:
                        self._compile_regex_leaf(f"vocabularies.{name}.{entry}", entry)
            else:
                for key, inner in value.items():
                    if isinstance(inner, list):
                        validate_string_list(f"vocabularies.{name}.{key}", inner)
                        if name in REGEX_LEAF_VOCABULARIES:
                            for entry in inner:
                                self._compile_regex_leaf(
                                    f"vocabularies.{name}.{key}", entry
                                )
                    elif name in REGEX_LEAF_VOCABULARIES:
                        self._compile_regex_leaf(
                            f"vocabularies.{name}.{key}", inner
                        )
        # Fail fast: every externalized pattern must compile at load time.
        compile_specs(self.patterns)
        return self

    @staticmethod
    def _compile_regex_leaf(locator: str, pattern: str) -> None:
        """Compile one regex-leaf vocabulary entry or raise a load-time error."""
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{locator}: regex leaf does not compile: {exc}") from exc

    @functools.cached_property
    def compiled_patterns(self) -> dict[str, re.Pattern[str]]:
        """Patterns compiled once per process; keyed by artifact name."""
        return compile_specs(self.patterns)

    def pattern(self, name: str) -> re.Pattern[str]:
        """Return one compiled pattern, raising KeyError on unknown names."""
        return self.compiled_patterns[name]

    def vocabulary(self, name: str) -> VocabularyValue:
        """Return one vocabulary entry, raising KeyError on unknown names."""
        return self.vocabularies[name]

    def vocabulary_list(self, name: str) -> list[str]:
        """Return a list-shaped vocabulary, raising on shape mismatch."""
        value = self.vocabularies[name]
        if not isinstance(value, list):
            raise ValueError(f"vocabularies.{name}: expected a list vocabulary")
        return value

    def vocabulary_mapping(self, name: str) -> dict[str, str | list[str]]:
        """Return a mapping-shaped vocabulary, raising on shape mismatch."""
        value = self.vocabularies[name]
        if not isinstance(value, dict):
            raise ValueError(f"vocabularies.{name}: expected a mapping vocabulary")
        return value

    def threshold(self, name: str) -> int | float | str:
        """Return one raw scalar threshold, raising KeyError on unknown names."""
        return self.thresholds[name]

    def int_threshold(self, name: str) -> int:
        """Return an integer threshold (bool is rejected even though it subclasses int)."""
        value = self.thresholds[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"thresholds.{name}: expected an int, got {type(value).__name__}")
        return value

    def float_threshold(self, name: str) -> float:
        """Return a numeric threshold as float (bool is rejected)."""
        value = self.thresholds[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"thresholds.{name}: expected a number, got {type(value).__name__}"
            )
        return float(value)


def _read_json(path: Path) -> dict[str, Any]:
    """Read the JSON artifact from disk (split out for fail-fast tests)."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_rules(raw: dict[str, Any]) -> ParserRules:
    """Validate an in-memory artifact document and build the typed view."""
    if not isinstance(raw, dict):
        raise ValueError("parser rules artifact must be a JSON object")
    return ParserRules.model_validate(raw)


@functools.lru_cache(maxsize=1)
def get_parser_rules() -> ParserRules:
    """Return the shipped parser rules (cached for the process lifetime)."""
    rules = parse_rules(_read_json(_RULES_PATH))
    # Force compilation now so a corrupt artifact fails at first load rather
    # than at the first regex call site.
    _ = rules.compiled_patterns
    return rules
