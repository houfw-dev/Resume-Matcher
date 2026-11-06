"""Durable preview identity and input-version contracts."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from typing import Any


class PreviewValidationError(ValueError):
    """The request does not match a registered preview."""


class PreviewConflictError(ValueError):
    """The preview is stale, expired, deleted, or owned by another confirmer."""


class PreviewBusyError(PreviewConflictError):
    """Another request currently owns this confirmation."""


@dataclass(frozen=True)
class PreviewClaim:
    preview_id: str
    token: str | None = None
    response: dict[str, Any] | None = None
    improvements: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class FineTuneClaim:
    preview_id: str
    token: str | None = None
    response: dict[str, Any] | None = None
    completed: bool = False


def resume_fingerprint(
    content: str,
    processed_data: dict[str, Any] | None,
    original_markdown: str | None,
) -> str:
    serialized = json.dumps(
        [content, processed_data, original_markdown],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def job_fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            (unicodedata.normalize("NFC", key) if isinstance(key, str) else key): (
                _normalize_payload(val)
            )
            for key, val in value.items()
        }
    return value


def hash_resume_data(data: dict[str, Any]) -> str:
    """Stable sha256 of a ResumeData-shaped payload.

    Canonicalizes through ``ResumeData`` when possible so payloads that only
    differ by schema defaults hash identically, and NFC-normalizes strings.
    Importing the schema lazily keeps this low-level module import-cycle free.
    """
    try:
        from app.schemas.models import ResumeData

        canonical: Any = ResumeData.model_validate(data).model_dump()
    except Exception:
        canonical = data
    normalized = _normalize_payload(canonical)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
