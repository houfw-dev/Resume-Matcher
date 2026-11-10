"""Fine-tune endpoints: job-less self-improvement grounded in original + parsed."""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException

from app.ai_budget import (
    AIOperationDeadlineExceeded,
    AIOperationRoute,
    remaining_timeout,
)
from app.ai_limits import PromptSizeError
from app.config import settings
from app.database import DatabaseBusyError, db
from app.preview import (
    FineTuneClaim,
    PreviewBusyError,
    PreviewConflictError,
    PreviewValidationError,
    hash_resume_data,
    resume_fingerprint,
)
from app.schemas.fine_tune import (
    FineTuneConfirmRequest,
    FineTuneConfirmResponse,
    FineTunePreviewRequest,
    FineTunePreviewResponse,
)
from app.schemas.models import ResumeData
from app.services.fine_tune import (
    _canonical_source,
    build_grounding_evidence,
    restrict_to_scope,
    run_fine_tune,
)
from app.services.resume_preservation import finalize_ai_resume

logger = logging.getLogger(__name__)

router = APIRouter(
    route_class=AIOperationRoute, prefix="/resumes", tags=["FineTune"]
)

_COPY_TITLE_SUFFIX = " (fine-tuned)"


async def _load_resume_or_404(resume_id: str) -> dict:
    resume = await db.get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found.")
    return resume


def _source_hash(resume: dict) -> str:
    return resume_fingerprint(
        resume["content"],
        resume.get("processed_data"),
        resume.get("original_markdown"),
    )


@router.post(
    "/{resume_id}/fine-tune/preview",
    response_model=FineTunePreviewResponse,
)
async def fine_tune_preview(
    resume_id: str, request: FineTunePreviewRequest
) -> FineTunePreviewResponse:
    resume = await _load_resume_or_404(resume_id)
    if not isinstance(resume.get("processed_data"), dict):
        raise HTTPException(
            status_code=400,
            detail="Resume has no structured data. Please parse it before fine-tuning.",
        )
    try:
        result = await asyncio.wait_for(
            run_fine_tune(
                resume=resume,
                kind=request.scope.kind,
                targets=list(request.scope.targets),
                instruction=request.instruction,
                output_language=request.output_language,
            ),
            timeout=remaining_timeout(),
        )
    except (
        asyncio.CancelledError,
        AIOperationDeadlineExceeded,
        PromptSizeError,
        TimeoutError,
    ):
        # Mapped by AIOperationRoute (422) / operation budget (504).
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Fine-tune preview failed for %s: %s", resume_id, e)
        raise HTTPException(
            status_code=500, detail="Fine-tune generation failed. Please try again."
        ) from e

    improved_data = result.improved_data
    payload_hash = hash_resume_data(improved_data)
    scope_payload = {"kind": request.scope.kind, "targets": list(request.scope.targets)}
    stored_response = {
        "scope": scope_payload,
        "improved_data": improved_data,
        "diff_summary": (
            result.diff_summary.model_dump(mode="json")
            if result.diff_summary is not None
            else None
        ),
        "detailed_changes": [
            change.model_dump(mode="json") for change in result.detailed_changes
        ],
        "warnings": list(result.warnings),
    }
    try:
        registered = await db.register_fine_tune_preview(
            source_id=resume_id,
            scope_kind=request.scope.kind,
            scope_targets=list(request.scope.targets),
            instruction=request.instruction,
            payload_hash=payload_hash,
            source_hash=_source_hash(resume),
            prompt_id="fine_tune_v1",
            ttl_seconds=settings.preview_ttl_seconds,
            response_data=stored_response,
        )
    except PreviewConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return FineTunePreviewResponse(
        preview_id=registered["preview_id"],
        expires_at=registered.get("expires_at"),
        scope=request.scope,
        improved_data=ResumeData.model_validate(improved_data),
        diff_summary=result.diff_summary,
        detailed_changes=result.detailed_changes,
        warnings=result.warnings
        + [f"Ignored out-of-range target: {token}" for token in result.ignored_targets],
    )


async def _replay_or_validate_claim(
    resume: dict, claim: FineTuneClaim
) -> dict | None:
    """Return a replay response for completed claims; validate an active claim."""
    if claim.completed:
        return claim.response
    registered = claim.response or {}
    scope = registered.get("scope") or {}
    improved_echo = ResumeData.model_validate(
        registered.get("improved_data", {})
    ).model_dump()
    source = _canonical_source(resume)
    original_markdown = str(resume.get("original_markdown") or "")
    scope_kind = scope.get("kind", "all")
    evidence = build_grounding_evidence(source, original_markdown)
    candidate = finalize_ai_resume(
        source,
        improved_echo,
        allow_review_claims=True,
        allow_appended_rows=True,
        extra_evidence=evidence or None,
        allow_relocation=scope_kind == "all",
        allow_style_edits=True,
    )
    scoped, _, _ = restrict_to_scope(
        source,
        candidate,
        scope_kind,
        list(scope.get("targets", [])),
    )
    canonical_echo = ResumeData.model_validate(improved_echo).model_dump()
    if scoped != canonical_echo:
        raise PreviewValidationError(
            "Registered preview no longer satisfies preservation rules"
        )
    return None


@router.post(
    "/{resume_id}/fine-tune/confirm",
    response_model=FineTuneConfirmResponse,
)
async def fine_tune_confirm(
    resume_id: str, request: FineTuneConfirmRequest
) -> FineTuneConfirmResponse:
    resume = await _load_resume_or_404(resume_id)
    improved_data = request.improved_data.model_dump()
    claim: FineTuneClaim | None = None
    try:
        claim = await db.claim_fine_tune_preview(
            preview_id=request.preview_id,
            source_id=resume_id,
            payload_hash=hash_resume_data(improved_data),
            lease_seconds=settings.request_timeout_seconds + 15,
        )
        replay = await _replay_or_validate_claim(resume, claim)
        if replay is not None:
            return FineTuneConfirmResponse(
                resume_id=replay["resume_id"],
                mode=replay.get("mode", "copy"),
                title=replay.get("title"),
            )

        improved_text = json.dumps(improved_data, indent=2, ensure_ascii=False)
        if request.mode == "overwrite":
            await db.update_resume(
                resume_id,
                {
                    "content": improved_text,
                    "content_type": "json",
                    "processed_data": improved_data,
                    "processing_status": "ready",
                },
            )
            result_id = resume_id
            title = resume.get("title")
        else:
            base_title = resume.get("title") or "Resume"
            title = request.title or f"{base_title}{_COPY_TITLE_SUFFIX}"
            created = await db.create_resume(
                content=improved_text,
                content_type="json",
                filename=f"finetuned_{resume.get('filename') or 'resume'}",
                is_master=False,
                parent_id=resume_id,
                processed_data=improved_data,
                processing_status="ready",
                original_markdown=resume.get("original_markdown"),
                title=title,
            )
            result_id = created["resume_id"]

        stored = dict(claim.response or {})
        stored.update(mode=request.mode, title=title)
        await db.complete_fine_tune_preview(
            claim=claim,
            result_resume_id=result_id,
            response_data=stored,
        )
        claim = None
        return FineTuneConfirmResponse(
            resume_id=result_id, mode=request.mode, title=title
        )
    except PreviewBusyError as e:
        raise HTTPException(
            status_code=409, detail=str(e), headers={"Retry-After": "1"}
        ) from e
    except PreviewValidationError as e:
        logger.warning("Fine-tune confirm rejected for %s: %s", resume_id, e)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PreviewConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except HTTPException:
        raise
    except DatabaseBusyError:
        # Storage contention keeps its retryable 503 + Retry-After contract
        # (global handler); the broad 500 below must not mask it.
        raise
    except Exception as e:
        logger.error("Fine-tune confirm failed for %s: %s", resume_id, e)
        raise HTTPException(
            status_code=500, detail="Failed to apply fine-tuned resume. Please try again."
        ) from e
    finally:
        if claim is not None and claim.token is not None:
            try:
                # Shield the release from request-task cancellation (client
                # disconnect / deadline): a cancelled lease would otherwise
                # block every retry until its TTL expires.
                await asyncio.shield(
                    db.release_fine_tune_preview_claim(claim)
                )
            except Exception:
                logger.exception(
                    "Failed to release fine-tune claim for preview %s",
                    claim.preview_id,
                )
