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


class StubTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


async def test_the_client_refuses_an_oversized_response_body(monkeypatch) -> None:
    """The parser is the component assumed to fall, so a compromised one
    answering with an unbounded body must not become a memory problem here."""
    parser = HttpDocumentParser("http://parser:8000")
    monkeypatch.setattr("app.adapters.http.parser_client.MAX_TEXT_CHARS", 10)

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"text": "x" * 100})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DocumentParseError):
        await parser.extract_text(media_type="text/plain", data=b"x")


async def test_the_client_turns_an_unreachable_parser_into_a_domain_error(monkeypatch) -> None:
    parser = HttpDocumentParser("http://parser:8000")

    async def fail(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail)
    with pytest.raises(DocumentParseError):
        await parser.extract_text(media_type="text/plain", data=b"x")


async def test_the_client_refuses_a_response_with_no_text_field(monkeypatch) -> None:
    parser = HttpDocumentParser("http://parser:8000")

    async def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(DocumentParseError):
        await parser.extract_text(media_type="text/plain", data=b"x")
