"""The document parser, as its own application.

security.md section 7.3 requires that document parsing run in a separate,
resource-limited process with no network access, because PDF and Office parsers
have a dense CVE history and the bytes they read are supplied by whoever can
upload. This is that process.

**What makes it isolated is what it does not have**, and each of these is
enforced in `docker-compose.yml` rather than here:

- no volumes, so a file-write primitive has nothing to write to;
- no secrets and no database credentials, which is why this module reads no
  settings at all — `get_settings()` is never called, so there is nothing for a
  compromise to read out of the environment;
- one internal network shared only with the admin entrances, so it can reach
  neither the internet nor Postgres, Redis or Qdrant;
- a memory limit, so a decompression bomb kills this container rather than the
  host.

It is a fourth ASGI application in the same image, not a second image: the
isolation that matters is the process, network and credential boundary, not
which layers the code was built from.

The request body is raw bytes under `application/octet-stream`, with the real
type in `X-Document-Type`. Declaring the document's own media type as the
request's would invite the framework to negotiate on it, and content
negotiation over attacker-controlled bytes is a step worth not having.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Header, Request, Response
from pydantic import BaseModel

from app.parser.extract import ExtractionFailed, UnsupportedMediaType, extract

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 32 * 1024 * 1024
"""Mirrors `upload_policy.MAX_UPLOAD_BYTES` on the calling side. Duplicated
deliberately: this service must bound its own input rather than trust that its
one caller is the version of the code that also bounds it."""

app = FastAPI(
    title="RCSL AI Nexus document parser",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class ExtractResponse(BaseModel):
    text: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract")
async def extract_document(
    request: Request,
    response: Response,
    x_document_type: str = Header(default=""),
) -> ExtractResponse | dict[str, str]:
    data = await request.body()
    if len(data) > MAX_BODY_BYTES:
        response.status_code = 413
        return {"error": "too_large"}

    try:
        return ExtractResponse(text=extract(x_document_type, data))
    except UnsupportedMediaType:
        response.status_code = 415
        return {"error": "unsupported_media_type"}
    except ExtractionFailed as exc:
        # The failure class goes to this container's log and the caller learns
        # only that extraction failed. A parser's own message can quote document
        # bytes, and the caller renders what it is told in an operator UI.
        logger.info("extraction_failed type=%s reason=%s", x_document_type, exc)
        response.status_code = 422
        return {"error": "extraction_failed"}
