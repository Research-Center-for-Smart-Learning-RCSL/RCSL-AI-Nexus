"""The archive the platform hands an operator instead of a GitHub branch.

What matters about it is not that a zip can be made. It is that the zip contains
the scripts an operator needs, that it is the same bytes every time so two
downloads can be compared, and that the endpoint keeps working when the layout
moves rather than serving something half-formed.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.routers.client_tools import (
    build_archive,
    resolve_tools_directory,
    router,
)

REQUIRED_ENTRIES = {
    "Start-CodexAppSwitcher.ps1",
    "Test-CodexAppConnection.ps1",
    "CodexAppSwitcher.Common.psm1",
    "Invoke-CodexAppSwitcherTests.ps1",
    "README.md",
}


def test_the_tools_are_where_the_endpoint_looks_for_them() -> None:
    """A checkout resolves to `scripts/windows/codex-app`.

    Pinned because the resolver walks a fixed number of parents up from its own
    file, which is the kind of thing a move of the module silently breaks: the
    endpoint would answer 503 and read as "this build does not carry them"
    rather than as "somebody moved the router".
    """
    directory = resolve_tools_directory()

    assert directory is not None, "the resolver no longer finds the scripts in a checkout"
    assert directory.name == "codex-app"
    assert (directory / "CodexAppSwitcher.Common.psm1").is_file()


def test_the_download_requires_a_session() -> None:
    """Asserted over the route's dependencies rather than by calling it.

    The integration suite runs the tailnet entrance in `AUTH_MODE=dev`, where
    identity is supplied automatically, so a request there proves nothing about
    the gate. These scripts are published in a public repository and the point
    is not secrecy; it is that an unauthenticated endpoint on the admin origin
    is a surface nobody decided to have.
    """
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/windows-codex-app"))

    assert current_actor in [dependency.call for dependency in route.dependant.dependencies]


def test_the_archive_carries_every_script_an_operator_runs() -> None:
    """Named individually rather than counted.

    A count passes on the day one is dropped and another added, and the failure
    that matters is an operator unzipping the archive and finding the switcher
    without the module it imports.
    """
    directory = resolve_tools_directory()
    assert directory is not None

    with zipfile.ZipFile(BytesIO(build_archive(directory))) as archive:
        names = set(archive.namelist())

    missing = REQUIRED_ENTRIES - names
    assert missing == set(), f"the archive would not run without: {sorted(missing)}"


def test_the_archive_does_not_depend_on_the_machine_that_built_it() -> None:
    """Every field a zip takes from its host is pinned.

    Found by building the archive from a Windows checkout and inside the Linux
    image and comparing: the five files were byte-identical, the archives were
    the same length, and the hashes differed. `ZipInfo` defaults
    `create_system` to 0 on Windows and 3 elsewhere, one byte per entry in the
    central directory. Same-process determinism, which the test below checks,
    passes on either machine and says nothing about this.
    """
    directory = resolve_tools_directory()
    assert directory is not None

    with zipfile.ZipFile(BytesIO(build_archive(directory))) as archive:
        entries = archive.infolist()

    assert entries, "nothing to check"
    for entry in entries:
        assert entry.create_system == 3, f"{entry.filename} carries the building host"
        assert entry.date_time == (1980, 1, 1, 0, 0, 0), f"{entry.filename} carries an mtime"
        assert entry.external_attr == 0o644 << 16, f"{entry.filename} carries a local mode"


def test_the_same_scripts_produce_the_same_bytes() -> None:
    """A zip records a timestamp per entry, so the default is an archive that
    differs on every build for identical content. An operator who downloads
    twice and diffs should have nothing to explain, and a deployment that
    rebuilds should not look like it changed the tools."""
    directory = resolve_tools_directory()
    assert directory is not None

    assert build_archive(directory) == build_archive(directory)


def test_the_archive_is_readable_and_its_contents_match_the_files(tmp_path: Path) -> None:
    """Round-tripped rather than inspected: the useful assertion is that what
    comes out equals what went in, byte for byte, after a real extraction."""
    directory = resolve_tools_directory()
    assert directory is not None

    with zipfile.ZipFile(BytesIO(build_archive(directory))) as archive:
        assert archive.testzip() is None
        archive.extractall(tmp_path)

    for original in sorted(p for p in directory.rglob("*") if p.is_file()):
        extracted = tmp_path / original.relative_to(directory)
        assert extracted.is_file(), f"{original.name} did not survive the round trip"
        assert extracted.read_bytes() == original.read_bytes()


def test_an_empty_directory_yields_a_valid_empty_archive(tmp_path: Path) -> None:
    """The degenerate case answers rather than raising, because a zip that
    cannot be opened is a worse failure than one that is obviously empty."""
    with zipfile.ZipFile(BytesIO(build_archive(tmp_path))) as archive:
        assert archive.namelist() == []


def test_nested_files_keep_their_relative_path(tmp_path: Path) -> None:
    """Entry names use forward slashes whatever built them, or the archive is
    wrong for every extractor that is not Windows."""
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "inner.ps1").write_text("Write-Host hi\n", encoding="utf-8")
    (tmp_path / "top.ps1").write_text("Write-Host hi\n", encoding="utf-8")

    with zipfile.ZipFile(BytesIO(build_archive(tmp_path))) as archive:
        assert set(archive.namelist()) == {"top.ps1", "nested/inner.ps1"}
