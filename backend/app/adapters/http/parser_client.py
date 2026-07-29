"""Client for the isolated parser service.

Implements `DocumentParserPort`. The whole of this adapter is one POST, which
is the point: the complexity of reading a PDF lives in a container that holds
nothing worth stealing (app/parser/main.py), and this side only has to not
trust what comes back.
"""

from __future__ import annotations

import logging

import httpx

from app.domain.exceptions import DocumentParseError

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 20_000_000
"""A bound on the *response*, not the request. The parser is the component
assumed to fall, so a compromised one answering with an unbounded body must not
become a memory problem on this side. Generous enough that no real document
reaches it."""


class HttpDocumentParser:
    def __init__(self, base_url: str, timeout_seconds: int = 120) -> None:
        self._base_url = base_url.rstrip("/")
        # Long enough for a large PDF, short enough that a parser wedged on a
        # crafted file frees the ingestion task rather than holding it forever.
        self._timeout = httpx.Timeout(
            connect=5.0, read=float(timeout_seconds), write=60.0, pool=5.0
        )

    async def extract_text(self, *, media_type: str, data: bytes) -> str:
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await client.post(
                    "/extract",
                    content=data,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Document-Type": media_type,
                    },
                )
        except httpx.HTTPError as exc:
            # A parser that is down is an operational failure, not a bad
            # document, but the caller gets one error either way: the
            # distinction is in the log, where it can name the service.
            logger.warning("parser_unreachable url=%s error=%s", self._base_url, exc)
            raise DocumentParseError(detail=f"parser unreachable: {exc}") from exc

        if response.status_code != 200:
            raise DocumentParseError(
                detail=f"parser returned {response.status_code} for {media_type}"
            )

        body = response.json()
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise DocumentParseError(detail="parser returned no text field")
        if len(text) > MAX_TEXT_CHARS:
            raise DocumentParseError(detail=f"parser returned {len(text)} characters")
        return text
