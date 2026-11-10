"""Hard, header-independent request body limits.

``Content-Length`` is client-controlled and is absent entirely on
``Transfer-Encoding: chunked`` requests, so a guard that only inspects the
header can be bypassed. These helpers stream the real body through a bounded
accumulator before any JSON parsing happens, mirroring the chunked upload
limit in :func:`app.routers.resumes._read_upload_content`.
"""

import logging
from typing import TypeVar

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Structured JSON writes (resume PATCH, cover letter, outreach, jobs upload)
# stay far below this: the AI source limit is 200k characters and legitimate
# resume/job documents serialize to a few tens of KB.
MAX_JSON_REQUEST_BYTES = 1024 * 1024

_READ_CHUNK_SIZE = 64 * 1024

ModelT = TypeVar("ModelT", bound=BaseModel)


async def read_limited_body(request: Request, max_bytes: int, detail: str) -> bytes:
    """Stream a request body, rejecting once the real byte count exceeds cap.

    The check counts actual received bytes, so neither a missing
    ``Content-Length`` (chunked transfer) nor a lying one can bypass it.
    """
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            logger.warning(
                "Rejected %s %s: body exceeds the %s-byte cap",
                request.method,
                request.url.path,
                max_bytes,
            )
            raise HTTPException(status_code=413, detail=detail)
    return bytes(body)


async def read_limited_json_model(
    request: Request,
    model: type[ModelT],
    max_bytes: int,
    detail: str,
) -> ModelT:
    """Read a capped body and validate it against a Pydantic request model.

    Validation errors are re-raised as ``RequestValidationError`` so the
    standard FastAPI 422 response contract is unchanged.
    """
    raw = await read_limited_body(request, max_bytes, detail)
    try:
        return model.model_validate_json(raw)
    except ValidationError as error:
        raise RequestValidationError(error.errors(), body=raw) from error
