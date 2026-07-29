"""The isolated parser service and its client.

Two properties matter here and neither is "it extracts text from a real PDF",
which needs a real PDF and proves little. What is worth pinning is that a
crafted file becomes a refusal rather than an exception escaping the handler,
and that nothing about the failure reaches the caller beyond the fact of it.

There is also a structural test: this package must not import the application.
That is the whole of its isolation, and an ordinary-looking import would undo
it silently.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.http.parser_client import HttpDocumentParser
from app.domain.exceptions import DocumentParseError
from app.parser.main import app

client = TestClient(app)


def post(data: bytes, media_type: str) -> httpx.Response:
    return client.post(
        "/extract",
        content=data,
        headers={"Content-Type": "application/octet-stream", "X-Document-Type": media_type},
    )


# --- the service ---------------------------------------------------------


def test_plain_text_and_markdown_are_decoded() -> None:
    assert post(b"hello world", "text/plain").json()["text"] == "hello world"
    assert post(b"# heading", "text/markdown").json()["text"] == "# heading"


def test_undecodable_text_is_replaced_rather_than_refused() -> None:
    """A text file in an unexpected encoding is ordinary; mangling a character
    beats rejecting the upload."""
    assert post(b"caf\xe9", "text/plain").status_code == 200


def test_a_crafted_pdf_becomes_a_refusal_not_a_traceback() -> None:
    """The expected case, not the surprising one: pypdf raises plain ValueError
    and KeyError on malformed input as readily as its own error class."""
    response = post(b"%PDF-1.7\nnot really a pdf at all", "application/pdf")
    assert response.status_code == 422
    assert response.json() == {"error": "extraction_failed"}


def test_a_crafted_docx_becomes_a_refusal() -> None:
    response = post(
        b"PK\x03\x04garbage",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert response.status_code == 422


def test_an_unknown_media_type_is_refused_without_guessing() -> None:
    """The declared type selects the parser and nothing sniffs the bytes, so an
    unrecognised type cannot fall through to a parser written for something
    else."""
    assert post(b"%PDF-1.7", "application/x-msdownload").status_code == 415


def test_the_failure_response_carries_no_parser_detail() -> None:
    body = post(b"%PDF-1.7\nbroken", "application/pdf").json()
    assert set(body) == {"error"}


def test_the_service_exposes_no_schema() -> None:
    """`docs_url`, `redoc_url` and `openapi_url` are all None: this service
    describes nothing about itself to anything that reaches it."""
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404


def test_health_is_available_for_the_compose_check() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


# --- the isolation, as a structural property -----------------------------


def test_the_parser_package_imports_nothing_from_the_application() -> None:
    """What it cannot import, an exploit in it cannot reach.

    The parser holds no credentials because it reads no settings, and it reaches
    no database because it imports nothing that opens one. Both stop being true
    the moment someone adds a convenient import, and neither the type checker
    nor a functional test would notice.
    """
    package = Path(__file__).resolve().parents[2] / "app" / "parser"
    forbidden = (
        "app.domain",
        "app.infrastructure",
        "app.adapters",
        "app.application",
        "app.interfaces",
    )

    for source in package.glob("*.py"):
        # Parsed rather than grepped: the module docstrings name these packages
        # precisely because they explain the rule, and a text scan would read
        # the explanation as a violation.
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        for module in imported:
            assert not module.startswith(forbidden), f"{source.name} imports {module}"


# --- the client ----------------------------------------------------------


class FakeStreamResponse:
    """Enough of a streamed `httpx.Response` for the client's read loop.

    `aiter_bytes` yields separately from `aread`, so a test can hand back a body
    far larger than the ceiling without ever building it: the point of the
    streaming read is that the client stops before the whole thing exists.
    """

    def __init__(self, status_code: int, chunks: list[bytes]) -> None:
        self.status_code = status_code
        self._chunks = chunks
        self.chunks_read = 0

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks_read += 1
            yield chunk

    async def aread(self) -> bytes:
        return b"".join(self._chunks)


class _StubStream:
    def __init__(self, response: FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        return False


def patch_stream(monkeypatch, response: FakeStreamResponse) -> None:
    def fake_stream(self: object, *args: object, **kwargs: object) -> _StubStream:
        return _StubStream(response)

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)


async def test_the_client_stops_reading_once_the_response_passes_the_ceiling(
    monkeypatch,
) -> None:
    """The parser is the component assumed to fall, so a compromised one
    answering with an unbounded body must not become a memory problem here.

    The earlier version of this bound checked the length of the *decoded* string,
    by which point httpx had buffered the whole body and `json()` had built a
    second copy of it, so it protected nothing. This asserts the read is
    abandoned partway rather than merely rejected afterwards.
    """
    monkeypatch.setattr("app.adapters.http.parser_client.MAX_RESPONSE_BYTES", 100)
    response = FakeStreamResponse(200, [b"x" * 60] * 1000)
    patch_stream(monkeypatch, response)

    with pytest.raises(DocumentParseError, match="exceeded"):
        await HttpDocumentParser("http://parser:8000").extract_text(
            media_type="text/plain", data=b"x"
        )

    # Two chunks is 120 bytes, past the 100-byte ceiling. The remaining 998 were
    # never pulled off the wire.
    assert response.chunks_read == 2


async def test_a_response_within_the_ceiling_is_returned(monkeypatch) -> None:
    patch_stream(monkeypatch, FakeStreamResponse(200, [b'{"text": "hel', b'lo"}']))
    text = await HttpDocumentParser("http://parser:8000").extract_text(
        media_type="text/plain", data=b"x"
    )
    assert text == "hello"


async def test_the_client_turns_an_unreachable_parser_into_a_domain_error(monkeypatch) -> None:
    def fail(self: object, *args: object, **kwargs: object) -> _StubStream:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.AsyncClient, "stream", fail)
    with pytest.raises(DocumentParseError):
        await HttpDocumentParser("http://parser:8000").extract_text(
            media_type="text/plain", data=b"x"
        )


async def test_the_client_refuses_a_response_with_no_text_field(monkeypatch) -> None:
    patch_stream(monkeypatch, FakeStreamResponse(200, [b'{"unexpected": true}']))
    with pytest.raises(DocumentParseError):
        await HttpDocumentParser("http://parser:8000").extract_text(
            media_type="text/plain", data=b"x"
        )


async def test_the_client_refuses_a_non_json_body(monkeypatch) -> None:
    patch_stream(monkeypatch, FakeStreamResponse(200, [b"not json at all"]))
    with pytest.raises(DocumentParseError, match="non-JSON"):
        await HttpDocumentParser("http://parser:8000").extract_text(
            media_type="text/plain", data=b"x"
        )


async def test_a_non_200_is_reported_by_status_without_the_body(monkeypatch) -> None:
    """The parser's error body can quote the document, so only the status
    crosses back."""
    patch_stream(monkeypatch, FakeStreamResponse(422, [b'{"error": "extraction_failed"}']))
    with pytest.raises(DocumentParseError, match="422"):
        await HttpDocumentParser("http://parser:8000").extract_text(
            media_type="application/pdf", data=b"x"
        )
