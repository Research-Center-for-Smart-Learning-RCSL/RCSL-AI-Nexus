"""Volume-backed document storage.

The property under test is the one the port was shaped for: a caller names a
document, never a location, so there is no argument through which a traversal
can travel. These run against a real temporary directory rather than a fake,
because the thing being asserted is where bytes land on a filesystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.storage.filesystem_documents import FilesystemDocumentStorage
from app.domain.entities.tenant import DEFAULT_TENANT_ID
from app.domain.exceptions import DocumentNotFoundError

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "99999999-9999-9999-9999-999999999999"
DOCUMENT = "22222222-2222-2222-2222-222222222222"


def storage(root: Path, tenant: str = TENANT_A) -> FilesystemDocumentStorage:
    return FilesystemDocumentStorage(root, tenant)


async def test_round_trips_the_original_and_the_extracted_text(tmp_path: Path) -> None:
    store = storage(tmp_path)
    await store.put_original(DOCUMENT, b"%PDF-1.7")
    await store.put_text(DOCUMENT, "hello")

    assert await store.read_original(DOCUMENT) == b"%PDF-1.7"
    assert await store.read_text(DOCUMENT) == "hello"


async def test_the_tenant_is_in_the_path_so_another_tenants_document_does_not_resolve(
    tmp_path: Path,
) -> None:
    """The isolation is a path that is not reachable rather than a check that
    could be forgotten. security.md 7.3."""
    await storage(tmp_path, TENANT_A).put_original(DOCUMENT, b"secret")

    with pytest.raises(DocumentNotFoundError):
        await storage(tmp_path, TENANT_B).read_original(DOCUMENT)


@pytest.mark.parametrize(
    "hostile",
    [
        "../../../etc/passwd",
        "..",
        "/etc/passwd",
        "22222222-2222-2222-2222-222222222222/../../escape",
        "",
    ],
)
async def test_a_document_id_that_is_not_a_uuid_is_refused(tmp_path: Path, hostile: str) -> None:
    store = storage(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        await store.put_original(hostile, b"x")
    with pytest.raises(DocumentNotFoundError):
        await store.read_original(hostile)


@pytest.mark.parametrize("hostile", ["../escape", "a/b", "..", "", "a" * 100, "tenant\x00"])
async def test_a_tenant_id_that_is_not_a_safe_path_segment_is_refused(
    tmp_path: Path, hostile: str
) -> None:
    with pytest.raises(ValueError, match="safe path segment"):
        FilesystemDocumentStorage(tmp_path, hostile)


async def test_the_default_tenant_is_accepted(tmp_path: Path) -> None:
    """`DEFAULT_TENANT_ID` is the literal string `default`, not a UUID, and it
    is the tenant every existing deployment runs under. Requiring a UUID here
    refused it outright, which no unit test using a generated id would notice."""
    store = FilesystemDocumentStorage(tmp_path, DEFAULT_TENANT_ID)
    await store.put_original(DOCUMENT, b"x")
    assert await store.read_original(DOCUMENT) == b"x"


async def test_nothing_is_written_outside_the_tenant_directory(tmp_path: Path) -> None:
    await storage(tmp_path).put_original(DOCUMENT, b"x")
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written
    for path in written:
        assert path.is_relative_to(tmp_path / TENANT_A / DOCUMENT)


async def test_delete_removes_both_objects_and_is_idempotent(tmp_path: Path) -> None:
    """A row whose bytes are already gone must stay deletable, or a failed
    upload leaves an undeletable document."""
    store = storage(tmp_path)
    await store.put_original(DOCUMENT, b"x")
    await store.put_text(DOCUMENT, "y")

    await store.delete(DOCUMENT)
    await store.delete(DOCUMENT)

    with pytest.raises(DocumentNotFoundError):
        await store.read_original(DOCUMENT)


async def test_reading_a_document_that_was_never_stored_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(DocumentNotFoundError):
        await storage(tmp_path).read_text(DOCUMENT)


async def test_a_write_leaves_no_partial_file_behind(tmp_path: Path) -> None:
    """Written to a sibling and renamed, so a crash leaves the previous content
    or none, never a truncated file that would parse as a shorter document."""
    store = storage(tmp_path)
    await store.put_original(DOCUMENT, b"first")
    await store.put_original(DOCUMENT, b"second")

    assert await store.read_original(DOCUMENT) == b"second"
    assert not list((tmp_path / TENANT_A / DOCUMENT).glob("*.partial"))
