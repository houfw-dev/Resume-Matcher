"""Pydantic models for job-less resume fine-tuning (original + parsed sources)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.models import ResumeData, ResumeDiffSummary, ResumeFieldDiff

FineTuneKind = Literal["all", "modules"]

# Section-level tokens, plus per-item tokens for work/projects and per-block
# tokens for custom sections (``custom_<key>``). Item indices refer to the
# stored (canonical preview) sequence, matching enrichment's exp_N/proj_N
# convention. Builder-created custom keys are themselves ``custom_N``, so their
# tokens carry a double prefix (``custom_custom_1``). ``personalInfo`` and
# ``sectionMeta`` have no tokens: they are always frozen, regardless of scope.
# A syntactically valid custom_<key> whose key is absent from the resume is NOT
# a 422: it is reported as an ignored out-of-range target at runtime, mirroring
# work_N semantics.
#
# Third level: a label sub-module inside one work/project entry,
# ``(work|project)_<index>:<region>`` (e.g. project_2:highlights = only the
# rows under the 项目亮点 label). Region ids are defined in
# app/services/description_regions.py. A valid shape whose entry lacks that
# region (or where the entry kind never carries the id, e.g. work background)
# is likewise a runtime ignored target, not a 422.
_TARGET_PATTERN = (
    r"^(?:summary|education|additional|customSections"
    r"|workExperience|personalProjects|work_\d+|project_\d+"
    r"|(?:work|project)_\d+:(?:techStack|background|duties|highlights"
    r"|achievements|role)"
    r"|custom_[\w.-]+)$"
)

_MAX_TARGETS = 30
_MAX_INSTRUCTION_LENGTH = 2000
_MAX_TITLE_LENGTH = 200


class FineTuneScope(BaseModel):
    """What a fine-tune run is allowed to change."""

    kind: FineTuneKind = "all"
    targets: list[str] = Field(default_factory=list)

    @field_validator("targets")
    @classmethod
    def _validate_targets(cls, value: list[str]) -> list[str]:
        import re

        for token in value:
            if not isinstance(token, str) or not re.match(_TARGET_PATTERN, token):
                raise ValueError(f"Unsupported fine-tune target: {token!r}")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_kind_combo(self) -> "FineTuneScope":
        if self.kind == "all" and self.targets:
            raise ValueError("Whole-resume fine-tune takes no module targets")
        if self.kind == "modules" and not self.targets:
            raise ValueError("Module fine-tune requires at least one target")
        if len(self.targets) > _MAX_TARGETS:
            raise ValueError("Too many fine-tune targets")
        return self


class FineTunePreviewRequest(BaseModel):
    """Body for POST /resumes/{id}/fine-tune/preview."""

    scope: FineTuneScope = Field(default_factory=FineTuneScope)
    instruction: str = Field(default="", max_length=_MAX_INSTRUCTION_LENGTH)
    output_language: str | None = Field(default=None, max_length=16)

    @field_validator("instruction")
    @classmethod
    def _normalize_instruction(cls, value: str) -> str:
        return value.strip()


class FineTunePreviewResponse(BaseModel):
    """The generated result plus its registered preview identity."""

    preview_id: str
    expires_at: str | None = None
    scope: FineTuneScope
    improved_data: ResumeData
    diff_summary: ResumeDiffSummary | None = None
    detailed_changes: list[ResumeFieldDiff] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FineTuneConfirmRequest(BaseModel):
    """Body for POST /resumes/{id}/fine-tune/confirm."""

    preview_id: str
    improved_data: ResumeData
    mode: Literal["overwrite", "copy"]
    title: str | None = Field(default=None, max_length=_MAX_TITLE_LENGTH)


class FineTuneConfirmResponse(BaseModel):
    resume_id: str
    mode: Literal["overwrite", "copy"]
    title: str | None = None
