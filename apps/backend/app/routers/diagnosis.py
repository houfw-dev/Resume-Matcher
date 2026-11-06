"""Read-only diagnosis catalog endpoints."""

from fastapi import APIRouter, Query

from app.schemas.diagnosis import CompetencyCatalog, CompetencyModelOption
from app.services.diagnosis_competency import (
    parse_competency_models,
    select_competency_model,
)
from app.services.diagnosis_rules import get_rules

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])


@router.get("/competency-models", response_model=CompetencyCatalog)
async def list_competency_models(
    title: str | None = Query(default=None, description="Target title to auto-match."),
) -> CompetencyCatalog:
    """List shipped competency models and (optionally) the auto-match for title.

    The picker calls this when the diagnosis modal opens and whenever the
    selected target title changes, so title-to-level regex matching stays
    server-side (the single source of truth lives in the rules artifact).
    """
    rules = get_rules()
    models = parse_competency_models(rules.competency_models)
    matched = select_competency_model(models, title) if title else None
    return CompetencyCatalog(
        models=[
            CompetencyModelOption(
                key=model.key, name=model.name, family=model.family, level=model.level
            )
            for model in models
        ],
        matched_key=matched.key if matched is not None else None,
    )
