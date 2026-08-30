"""The archive the platform hands an operator instead of a GitHub branch.

What matters about it is not that a zip can be made. It is that the zip contains
the scripts an operator needs and nothing nobody decided to publish, that it is
the same bytes on every machine so two downloads can be compared, and that the
endpoint keeps working when the layout moves rather than serving something
half-formed.
"""

from __future__ import annotations

import zipfile
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from starlette.requests import Request

from app.adapters.authz.role_authorization import RoleAuthorization
from app.domain.entities.actor import ROLE_SCOPES, Actor, Role, Scope
from app.domain.exceptions import NotAuthorizedError
from app.infrastructure.di import get_authorization
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.routers import client_tools
from app.interfaces.http.routers.client_tools import (
    PACKAGED_FILES,
    archive_with_etag,
    build_archive,
    download_windows_codex_app_tools,
    etag_matches,
    resolve_tools_directory,
    router,
)
from app.interfaces.http.schemas.admin_schemas import AdminErrorResponse

REQUIRED_ENTRIES = {
    "Start-CodexAppSwitcher.ps1",
    "Test-CodexAppConnection.ps1",
    "CodexAppSwitcher.Common.psm1",
    "Invoke-CodexAppSwitcherTests.ps1",
    "README.md",
}


def _request(headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/admin/client-tools/windows-codex-app",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
    )


def _actor(role: Role = Role.USER) -> Actor:
    """Built the way `_actor_for` builds one: scopes come from the role.

    Handing the constructor a scope set chosen by the test is what made the
    previous version of the authorization case worthless — it asserted over a
    role/scope combination the application can never produce, so it passed while
    the guard it was pointed at refused nobody.
    """
    return Actor(
        id="u1",
        display="someone",
        role=role,
        source="tailnet",
        scopes=ROLE_SCOPES[role],
    )


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


def test_the_published_list_is_the_whole_directory_and_no_more() -> None:
    """Both directions, because each catches a different accident.

    The archive was built by globbing the directory, which is a publication rule
    rather than a file list: anything that lands there — a note, a capture, a
    key parked while debugging — reaches every member who clicks download, and
    nothing in the change that put it there would say so. This fails when a file
    appears, so shipping it is a decision somebody makes. It fails the other way
    when a file is renamed and the tuple is not, which would otherwise surface
    as a 503 on a build that has the tools.
    """
    directory = resolve_tools_directory()
    assert directory is not None

    on_disk = {path.name for path in directory.rglob("*") if path.is_file()}

    unpublished = on_disk - set(PACKAGED_FILES)
    assert unpublished == set(), f"decide whether these ship, then name them: {sorted(unpublished)}"
    assert set(PACKAGED_FILES) - on_disk == set(), "PACKAGED_FILES names a file that is not there"


def test_the_download_requires_a_session_and_the_scope_that_makes_it_useful() -> None:
    """Asserted over the route's dependencies rather than by calling it.

    The integration suite runs the tailnet entrance in `AUTH_MODE=dev`, where
    identity is supplied automatically, so a request there proves nothing about
    the gate.
    """
    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/windows-codex-app"))
    dependencies = [dependency.call for dependency in route.dependant.dependencies]

    assert current_actor in dependencies
    assert get_authorization in dependencies


@pytest.mark.parametrize("role", sorted(ROLE_SCOPES, key=lambda r: r.value))
async def test_only_a_role_that_may_hold_a_key_gets_the_tools(role: Role) -> None:
    """Every role, and the rule stated once rather than a list to keep.

    The point of running it over all of them is the case below: a guard whose
    scope every role holds is a guard that refuses nobody, and the previous
    version of this test could not have noticed, because it asserted over an
    actor `_actor_for` cannot build. `api_key:write_own` is the scope an auditor
    lacks, and `catalog.py` gives the reason in the same breath — an auditor who
    can mint a key can act through the gateway.
    """
    may_hold_a_key = Scope.API_KEY_WRITE_OWN in ROLE_SCOPES[role]

    if may_hold_a_key:
        response = await download_windows_codex_app_tools(
            request=_request(), actor=_actor(role), authz=RoleAuthorization()
        )
        assert response.status_code == 200
    else:
        with pytest.raises(NotAuthorizedError):
            await download_windows_codex_app_tools(
                request=_request(), actor=_actor(role), authz=RoleAuthorization()
            )


def test_the_scope_the_route_requires_is_one_some_role_lacks() -> None:
    """Directly, because the case above is silent about it.

    `chat:use` was the first choice and is held by every role in the table, so
    the check passed for every caller while its comment claimed to exclude one.
    A scope nobody lacks is a scope that decides nothing, and that is a property
    of the catalogue rather than of this route, so it is asserted rather than
    inferred from a refusal that happens to occur.
    """
    refused = {
        role for role, scopes in ROLE_SCOPES.items() if Scope.API_KEY_WRITE_OWN not in scopes
    }

    assert refused, "every role holds this scope, so the route's guard refuses nobody"
    assert Role.AUDITOR in refused


async def test_a_member_gets_the_zip_with_a_strong_etag() -> None:
    response = await download_windows_codex_app_tools(
        request=_request(), actor=_actor(), authz=RoleAuthorization()
    )

    assert response.status_code == 200
    assert response.media_type == "application/zip"
    assert response.headers["etag"] == f'"{sha256(response.body).hexdigest()}"'
    assert "rcsl-codex-app-tools.zip" in response.headers["content-disposition"]


async def test_a_caller_holding_the_current_archive_is_not_sent_it_again() -> None:
    """The archive cannot change while the process runs, so a reload should cost
    a header exchange rather than 130 KB. The ETag is also what distinguishes
    one deployment's tools from the next under a URL that does not change."""
    directory = resolve_tools_directory()
    assert directory is not None
    _, etag = archive_with_etag(directory)

    response = await download_windows_codex_app_tools(
        request=_request({"If-None-Match": etag}),
        actor=_actor(),
        authz=RoleAuthorization(),
    )

    assert response.status_code == 304
    assert response.body == b""
    assert response.headers["etag"] == etag


@pytest.mark.parametrize(
    "header",
    [
        '"{tag}"',
        'W/"{tag}"',
        "*",
        '"other", W/"{tag}"',
    ],
)
async def test_the_forms_of_if_none_match_an_intermediary_can_produce(header: str) -> None:
    """A plain `in` over the comma-split header handles the first of these.

    The rest are RFC 7232 and are not decoration: `*` is the wildcard any
    conditional GET may send, and a proxy is free to weaken a strong tag —
    nginx does it whenever it transforms a response — so the client echoes
    `W/"<sha>"` and an exact comparison never matches again. Each miss costs
    the full 130 KB body, which is what the ETag was added to avoid.
    """
    directory = resolve_tools_directory()
    assert directory is not None
    _, etag = archive_with_etag(directory)

    response = await download_windows_codex_app_tools(
        request=_request({"If-None-Match": header.format(tag=etag.strip('"'))}),
        actor=_actor(),
        authz=RoleAuthorization(),
    )

    assert response.status_code == 304


def test_an_unrelated_tag_still_gets_the_body() -> None:
    assert not etag_matches('"something-else"', '"abc"')
    assert not etag_matches(None, '"abc"')
    assert not etag_matches("", '"abc"')


async def test_a_build_without_the_tools_says_so_in_the_envelope_the_ui_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 503 hand-wrote `{"detail": ...}`, which is neither this
    application's error shape nor the one FastAPI would have produced, and the
    generated contract declared no body at all — so the one thing the response
    exists to say was unreadable from the other side."""
    monkeypatch.setattr(client_tools, "resolve_tools_directory", lambda: None)

    response = await download_windows_codex_app_tools(
        request=_request(), actor=_actor(), authz=RoleAuthorization()
    )

    assert response.status_code == 503
    envelope = AdminErrorResponse.model_validate_json(response.body)
    assert envelope.code == "client_tools_unavailable"
    assert "build context" in envelope.message


def test_the_archive_is_built_once_rather_than_per_request() -> None:
    """Reading five files and deflating 130 KB of them on the event loop, to
    produce bytes that are the same every time, is work the second caller should
    not pay for. Identity rather than equality: equal bytes would pass on a
    rebuild."""
    directory = resolve_tools_directory()
    assert directory is not None

    assert archive_with_etag(directory)[0] is archive_with_etag(directory)[0]


def test_editing_a_script_is_not_served_from_the_cache(tmp_path: Path) -> None:
    """The cache was keyed on the directory, and its comment said the files
    cannot change while the process runs. True in an image, false in a checkout
    — which is the branch the resolver falls back to and the one local
    development uses. `uvicorn --reload` restarts on a `.py` edit and not on a
    `.ps1` one, so the developer got the pre-edit zip with an ETag asserting it
    was current."""
    directory = tmp_path / "tools"
    directory.mkdir()
    for name in PACKAGED_FILES:
        (directory / name).write_text("before\n", encoding="utf-8")
    _, before = archive_with_etag(directory)

    edited = directory / PACKAGED_FILES[0]
    edited.write_text("after\n", encoding="utf-8")
    # Written back with a distinct mtime, because a same-nanosecond rewrite is
    # not what this is about and the filesystem may not resolve two of them.
    edited.touch()

    _, after = archive_with_etag(directory)

    assert before != after, "an edited script was served from the cache"


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


def test_a_build_missing_one_of_them_reports_itself_rather_than_serving_it(
    tmp_path: Path,
) -> None:
    """A half-copied image answers 503 here instead of handing an operator a
    switcher without the module it imports, which would fail on their machine
    rather than on ours.

    Driven through `resolve_tools_directory` rather than by re-deciding the rule
    in the test. The previous version wrote the predicate out again, so reverting
    the resolver to a bare `is_dir()` left it green and the case it names
    uncovered.
    """
    complete, missing_one = tmp_path / "complete", tmp_path / "missing-one"
    for directory in (complete, missing_one):
        directory.mkdir()
        for name in PACKAGED_FILES:
            (directory / name).write_text("x\n", encoding="utf-8")
    (missing_one / PACKAGED_FILES[0]).unlink()

    assert resolve_tools_directory([missing_one]) is None
    assert resolve_tools_directory([complete]) == complete
    assert resolve_tools_directory([missing_one, complete]) == complete


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


def test_the_archive_does_not_depend_on_the_checkout_that_built_it(tmp_path: Path) -> None:
    """The other half of reproducibility, and the half that was missing.

    `create_system` was pinned; the file contents were not. These files were
    CRLF in a Windows working tree and LF in the index, so the same commit
    produced a different archive on a Windows checkout than inside the Linux
    image — every entry differing, while the metadata test above passed. Two
    directories, identical but for their line endings, must build one archive.
    """
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    for directory, ending in ((lf, "\n"), (crlf, "\r\n")):
        directory.mkdir()
        for name in PACKAGED_FILES:
            (directory / name).write_bytes(f"one{ending}two{ending}".encode())

    assert build_archive(lf) == build_archive(crlf)


def test_the_same_scripts_produce_the_same_bytes() -> None:
    """A zip records a timestamp per entry, so the default is an archive that
    differs on every build for identical content. An operator who downloads
    twice and diffs should have nothing to explain, and a deployment that
    rebuilds should not look like it changed the tools."""
    directory = resolve_tools_directory()
    assert directory is not None

    assert build_archive(directory) == build_archive(directory)


def test_the_archive_is_readable_and_its_contents_are_the_files(tmp_path: Path) -> None:
    """Round-tripped rather than inspected: the useful assertion is that what
    comes out is what the operator would have got from a checkout, after a real
    extraction. Compared line by line, because the bytes are deliberately
    normalized on the way in and a byte comparison would pin the checkout's
    line endings instead of the file's content."""
    directory = resolve_tools_directory()
    assert directory is not None

    with zipfile.ZipFile(BytesIO(build_archive(directory))) as archive:
        assert archive.testzip() is None
        archive.extractall(tmp_path)

    for name in PACKAGED_FILES:
        extracted = tmp_path / name
        assert extracted.is_file(), f"{name} did not survive the round trip"
        assert extracted.read_text(encoding="utf-8").splitlines() == (
            (directory / name).read_text(encoding="utf-8").splitlines()
        )


def test_every_entry_ends_its_lines_the_same_way() -> None:
    """CRLF, because these are Windows PowerShell scripts and that is what the
    host they run on writes natively. Which one matters far less than that the
    archive answers the same on every build host."""
    directory = resolve_tools_directory()
    assert directory is not None

    with zipfile.ZipFile(BytesIO(build_archive(directory))) as archive:
        for name in archive.namelist():
            body = archive.read(name)
            assert b"\n" in body, f"{name} has no lines to check"
            assert body.replace(b"\r\n", b"").count(b"\n") == 0, f"{name} carries a bare LF"
