"""Schemas for the resume diagnosis feature (rubric V4, checklist edition)."""

from typing import Literal

from pydantic import BaseModel, Field

Rating = Literal["conform", "partial", "nonconform", "na"]
Severity = Literal["redline", "normal"]

TemplateTypeIn = Literal[
    "swiss-single",
    "swiss-two-column",
    "modern",
    "modern-two-column",
    "latex",
    "clean",
    "vivid",
]
PageSizeIn = Literal["A4", "LETTER"]
FontFamilyIn = Literal["serif", "sans-serif", "mono"]
AccentColorIn = Literal["blue", "green", "orange", "red"]
LocatorKindIn = Literal["summary", "entry", "custom_text", "custom_item"]
EntrySectionIn = Literal["workExperience", "personalProjects"]


class MarginSettingsIn(BaseModel):
    model_config = {"extra": "ignore"}

    top: int = Field(default=10, ge=5, le=25)
    bottom: int = Field(default=10, ge=5, le=25)
    left: int = Field(default=10, ge=5, le=25)
    right: int = Field(default=10, ge=5, le=25)


class SpacingSettingsIn(BaseModel):
    model_config = {"extra": "ignore"}

    section: int = Field(default=3, ge=1, le=5)
    item: int = Field(default=2, ge=1, le=5)
    lineHeight: int = Field(default=3, ge=1, le=5)


class FontSizeSettingsIn(BaseModel):
    model_config = {"extra": "ignore"}

    base: int = Field(default=3, ge=1, le=5)
    headerScale: int = Field(default=3, ge=1, le=5)
    headerFont: FontFamilyIn = "serif"
    bodyFont: FontFamilyIn = "sans-serif"


class TemplateSettingsIn(BaseModel):
    """The builder's template/typography choice (mirror of the TS type).

    Sent alongside the measured render so the server knows which template
    produced the snapshot; fields are optional with builder defaults.
    """

    model_config = {"extra": "ignore"}

    template: TemplateTypeIn = "swiss-single"
    pageSize: PageSizeIn = "A4"
    margins: MarginSettingsIn = Field(default_factory=MarginSettingsIn)
    spacing: SpacingSettingsIn = Field(default_factory=SpacingSettingsIn)
    fontSize: FontSizeSettingsIn = Field(default_factory=FontSizeSettingsIn)
    compactMode: bool = False
    showContactIcons: bool = True
    accentColor: AccentColorIn = "blue"


class LayoutLocatorIn(BaseModel):
    """Stable address of a measured point inside the structured resume."""

    model_config = {"extra": "ignore"}

    kind: LocatorKindIn
    section: EntrySectionIn | None = None
    key: str | None = Field(default=None, max_length=100)
    entry_index: int | None = Field(default=None, ge=0)
    point_index: int = Field(ge=0)


class LayoutPointIn(BaseModel):
    model_config = {"extra": "ignore"}

    locator: LayoutLocatorIn
    location: str = Field(default="", max_length=120)
    text: str = Field(default="", max_length=120)
    chars: int = Field(default=0, ge=0, le=10_000)
    visual_lines: int = Field(ge=1, le=100)
    height_px: int = Field(default=0, ge=0, le=10_000)
    page: int = Field(ge=1, le=12)


class LayoutSectionIn(BaseModel):
    model_config = {"extra": "ignore"}

    key: str = Field(max_length=100)
    title: str = Field(default="", max_length=120)
    visible: bool = True
    index: int = Field(ge=0, le=99)
    height_px: int = Field(default=0, ge=0, le=100_000)
    pages: list[int] = Field(default_factory=list, max_length=12)


class LayoutHeaderIn(BaseModel):
    model_config = {"extra": "ignore"}

    height_px: int = Field(default=0, ge=0, le=10_000)
    cell_count: int = Field(default=0, ge=0, le=100)
    rows: list[dict[str, int]] = Field(default_factory=list, max_length=20)


class LayoutPageMirrorIn(BaseModel):
    model_config = {"extra": "ignore"}

    page: int = Field(ge=1, le=12)
    text: str = Field(default="", max_length=6_000)


class RenderedLayoutIn(BaseModel):
    """Client-measured real render of the resume in the chosen template.

    Bounds mirror the frontend LAYOUT_LIMITS; all fields are permissive and
    unknown fields are ignored. The server re-validates usability (template
    match, sane page count) before trusting any value.
    """

    model_config = {"extra": "ignore"}

    schema_version: int = Field(default=1, ge=1, le=100)
    measured_at: str = Field(default="", max_length=40)
    template: TemplateTypeIn
    page_size: PageSizeIn
    margins: MarginSettingsIn = Field(default_factory=MarginSettingsIn)
    content_width_px: int = Field(default=0, ge=0, le=10_000)
    content_height_px: int = Field(default=0, ge=0, le=10_000)
    page_count: int = Field(ge=1, le=12)
    total_height_px: int = Field(default=0, ge=0, le=200_000)
    two_column: bool = False
    header: LayoutHeaderIn = Field(default_factory=LayoutHeaderIn)
    sections: list[LayoutSectionIn] = Field(default_factory=list, max_length=40)
    points: list[LayoutPointIn] = Field(default_factory=list, max_length=300)
    page_mirror: list[LayoutPageMirrorIn] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class DiagnosisRequest(BaseModel):
    """Body of POST /resumes/{id}/diagnose."""

    job_description: str | None = Field(
        default=None,
        description="Optional target JD; without it the JD-fit items are rated na.",
    )
    target_title: str | None = Field(
        default=None,
        description=(
            "Target job title for the diagnosis (求职意向). Defaults to the "
            "resume's personalInfo.title; sent explicitly when the resume lists "
            "multiple intentions and the user picked one."
        ),
    )
    competency_model_key: str | None = Field(
        default=None,
        description=(
            "Explicitly chosen competency model key (e.g. java-p5). Sent when "
            "the user picks/confirms a level in the UI; overrides title-based "
            "auto-matching. 400 when the key does not identify a shipped model."
        ),
    )
    template_settings: TemplateSettingsIn | None = Field(
        default=None,
        description=(
            "Builder template/typography choice. Optional; when sent together "
            "with rendered_layout, the length/density checks judge the measured "
            "render of this template instead of the text-only estimates."
        ),
    )
    rendered_layout: RenderedLayoutIn | None = Field(
        default=None,
        description=(
            "Offscreen, browser-measured render (page count, per-point visual "
            "lines, per-page text mirror). Trusted only when its template "
            "matches template_settings and the payload passes usability gates."
        ),
    )


class RatingCounts(BaseModel):
    """Verdict counts for the whole resume or one dimension."""

    conform: int = 0
    partial: int = 0
    nonconform: int = 0
    na: int = 0
    effective: int = 0  # conform + partial + nonconform (na excluded)


class DiagnosisItemResult(BaseModel):
    """One rubric checklist item with its verdict.

    ``topic`` is the public problem-location label (module/topic only). The
    full criterion text is intentionally absent — the rubric standards stay
    server-side; ``evidence`` says what is wrong in this resume and
    ``suggestion`` how to fix it.
    """

    id: int
    dimension: str
    dimension_name: str
    sub_dimension: str
    topic: str
    severity: Severity
    judgment_method: Literal["objective", "subjective"]
    rating: Rating
    evidence: str = ""
    suggestion: str = ""


class DimensionResult(BaseModel):
    """Checklist row for one first-level dimension."""

    key: str
    name: str
    counts: RatingCounts


class CompetencyModelInfo(BaseModel):
    """The competency model activated for this diagnosis, if any."""

    key: str
    name: str


class CompetencyModelOption(BaseModel):
    """One selectable competency model (catalog for the diagnosis picker)."""

    key: str
    name: str
    family: str = ""
    level: str = ""


class CompetencyCatalog(BaseModel):
    """All shipped competency models plus the auto-match for a given title."""

    models: list[CompetencyModelOption]
    matched_key: str | None = None


class RedLineStatus(BaseModel):
    """One hard-veto item (any nonconform fails the resume)."""

    id: int
    topic: str
    passed: bool
    rating: Rating
    evidence: str = ""
    suggestion: str = ""


class DiagnosisReport(BaseModel):
    """Full diagnosis response (not persisted; computed on demand)."""

    resume_id: str
    spec_version: str
    language: str
    target_title: str | None = None
    competency_model: CompetencyModelInfo | None = None
    counts: RatingCounts
    redline_passed: bool
    failed_redline_ids: list[int]
    dimensions: list[DimensionResult]
    redlines: list[RedLineStatus]
    items: list[DiagnosisItemResult]
    warnings: list[str] = Field(default_factory=list)
