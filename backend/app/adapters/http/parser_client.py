"""Client for the isolated parser service.

Implements `DocumentParserPort`. The whole of this adapter is one POST, which
is the point: the complexity of reading a PDF lives in a container that holds
nothing worth stealing (app/parser/main.py), and this side only has to not
trust what comes back.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.domain.exceptions import DocumentParseError

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
"""A bound on the *response*, enforced while it is being read.

The parser is the component assumed to fall, so a compromised one answering with
an unbounded body must not become a memory problem on this side. Generous enough
that no real document reaches it: the upload ceiling is 32 MiB and extracted text
is smaller than its source in every format here.

Bytes rather than characters, because the check has to happen before the body is
decoded — which is the whole point. An earlier version bounded the decoded
string, by which time httpx had already buffered the entire response and
`json()` had built a second copy of it."""


class HttpDocumentParser:
    def __init__(self, base_url: str, timeout_seconds: int = 120) -> None:
        self._base_url = base_url.rstrip("/")
        # Long enough for a large PDF, short enough that a parser wedged on a
        # crafted file frees the ingestion task rather than holding it forever.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(timeout_seconds), write=60.0, pool=5.0
        )

    async def extract_text(self, *, media_type: str, data: bytes) -> str:
        """Streamed, and the ceiling is applied while reading rather than after.

        A non-streaming `post()` buffers the entire body before any check can
        run, and `response.json()` then materialises it a second time as Python
        objects. So a bound applied to the decoded string protected nothing: the
        parser is the one component this deployment assumes can be compromised,
        and a multi-gigabyte reply would exhaust the admin backend before the
        length check was ever reached. Reading in chunks and abandoning the
        response the moment it passes the ceiling is what makes the bound real.
        """
        raw = bytearray()
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                async with client.stream(
                    "POST",
                    "/extract",
                    content=data,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Document-Type": media_type,
                    },
                ) as response:
                    if response.status_code != 200:
                        # Read the (bounded) error body so the connection closes
                        # cleanly, then report the status only.
                        await response.aread()
                        raise DocumentParseError(
                            detail=f"parser returned {response.status_code} for {media_type}"
                        )

                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise DocumentParseError(
                                detail=f"parser response exceeded {MAX_RESPONSE_BYTES} bytes"
                            )
        except httpx.HTTPError as exc:
            # A parser that is down is an operational failure, not a bad
            # document, but the caller gets one error either way: the
            # distinction is in the log, where it can name the service.
            logger.warning("parser_unreachable url=%s error=%s", self._base_url, exc)
            raise DocumentParseError(detail=f"parser unreachable: {exc}") from exc

        try:
            body = json.loads(raw)
        except ValueError as exc:
            raise DocumentParseError(detail="parser returned a non-JSON body") from exc

        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise DocumentParseError(detail="parser returned no text field")
        return text
