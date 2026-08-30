"""The Windows operator tools, served by the platform that issues the keys.

Until now the management UI handed out a PowerShell snippet that fetched the
whole repository archive from GitHub `main`. That is three separate problems
wearing one coat. It put deployment-shaped content on operator laptops to
deliver five files; it tracked a moving branch, so two operators following the
same instructions on different days ran different code and neither could name a
version; and it sent somebody who trusts this platform to a different origin for
a script that will hold their API key.

The archive here is built from the copy inside this image, so what an operator
downloads is the revision that is deployed, and it arrives over the same origin
and the same session as the key it is going to carry. It also stops the
operator path depending on the repository staying public.

Reachable by a member rather than an administrator only, for the reason
`gateway_info.py` gives about itself: members hold their own API keys, and a key
with no way to connect a client is not a working key.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, Response

from app.domain.entities.actor import Actor, Scope
from app.domain.ports.security_ports import AuthorizationPort
from app.infrastructure.di import get_authorization
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.admin_schemas import AdminErrorResponse

router = APIRouter(prefix="/client-tools", tags=["client-tools"])

ARCHIVE_FILENAME: Final = "rcsl-codex-app-tools.zip"

PACKAGED_FILES: Final = (
    "CodexAppSwitcher.Common.psm1",
    "Invoke-CodexAppSwitcherTests.ps1",
    "README.md",
    "Start-CodexAppSwitcher.ps1",
    "Test-CodexAppConnection.ps1",
)
"""Exactly what ships, named.

This was `rglob("*")`, which is a publication rule rather than a file list: any
file that ever lands in `scripts/windows/codex-app` — a note, a capture, a
key someone parked there while debugging — is handed to every member who clicks
the download link, and nothing in the change that put it there would say so.
`test_client_tools_archive.py` pins this tuple against the directory, so adding
a file is a decision somebody makes rather than one that happens.

The test suite is in the list on purpose. An operator is told to inspect these
scripts before running them, and running the suite on their own PowerShell is
the only check available to them that the download works on their host before
it touches `config.toml`.
"""

_IMAGE_LOCATION: Final = Path("client-tools") / "windows" / "codex-app"
"""Where the Dockerfile puts the scripts, relative to the application root.

They are copied in through a named build context rather than living under
`backend/`, because they are operator tools and not backend code: their home is
`scripts/windows/codex-app`, and one copy is the point.
"""

_SOURCE_LOCATION: Final = Path("scripts") / "windows" / "codex-app"
"""Where they are in a checkout, which is what the tests run against."""

# Fixed so the same scripts always produce byte-identical bytes: a zip records a
# timestamp per entry, and taking it from the filesystem would make every image
# rebuild serve a different archive for identical content.
_FIXED_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)

_LINE_ENDING: Final = b"\r\n"
"""One answer, rather than whichever the checkout happened to have.

`.gitattributes` fixes these files to CRLF in every working tree, which is what
makes a maintainer's checkout match the image. This is the same rule applied
again at the point the bytes are chosen, because the archive claims to be
reproducible and that claim should not rest on the build host having honoured a
git attribute. It was not academic: the packaged files were CRLF in a Windows
working tree and LF in the index, so the same commit built a different archive
on a Windows checkout than in the Linux image, and every entry differed.
"""

_cache: dict[tuple[Path, tuple[int, ...]], tuple[bytes, str]] = {}
"""Built once per directory *and* modification time.

Every request used to read five files and deflate 130 KB of them on the event
loop to produce bytes that are, by construction, the same every time. No lock:
two concurrent first requests build the same bytes and store the same value.

Keyed on the mtimes rather than the directory alone, which would have been
enough in an image and wrong in a checkout — the branch this falls back to and
the one local development uses. `uvicorn --reload` restarts on a `.py` edit and
not on a `.ps1` one, so a developer editing a switcher script would have been
served the pre-edit zip together with an ETag asserting it was current. Five
stats per request is a cheaper way to keep the docstring true than a claim that
the files cannot change.
"""


def _fingerprint(directory: Path) -> tuple[int, ...]:
    return tuple((directory / name).stat().st_mtime_ns for name in sorted(PACKAGED_FILES))


def resolve_tools_directory(candidates: Iterable[Path] | None = None) -> Path | None:
    """The packaged tools, or `None` when this build does not carry them.

    A directory counts only when it holds every file in `PACKAGED_FILES`. A
    half-copied build then reports itself at this endpoint rather than serving a
    switcher without the module it imports, which would fail on the operator's
    machine instead of here.

    Absence is reported rather than raised at import time, so that an image
    built without the extra build context still starts and says what is wrong at
    the one endpoint that needs it.

    `candidates` is here so the completeness rule can be exercised against a
    directory a test builds. Without it the only assertion available was a copy
    of the rule written out again in the test, which passes whatever this
    function does — the half-copied case was named and not covered.
    """
    if candidates is None:
        here = Path(__file__).resolve()
        candidates = (
            here.parents[4] / _IMAGE_LOCATION,
            here.parents[5] / _SOURCE_LOCATION,
        )
    for candidate in candidates:
        if all((candidate / name).is_file() for name in PACKAGED_FILES):
            return candidate
    return None


def build_archive(directory: Path) -> bytes:
    """A deterministic zip of the files named in `PACKAGED_FILES`.

    A fixed order, a fixed timestamp, a fixed mode, a fixed originating system
    and a fixed line ending, so that the bytes depend on the scripts and on
    nothing else, whoever builds it. An operator who downloads twice and
    compares should find no difference to explain, and the archive a maintainer
    builds from a checkout is the archive the deployment serves.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(PACKAGED_FILES):
            entry = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            # `ZipInfo` takes this from the host that builds the archive: 0 for
            # MS-DOS on Windows and 3 for Unix everywhere else. It is one byte
            # per entry in the central directory and does not change the length,
            # so an archive built from a Windows checkout and one built inside
            # the Linux image were the same size and a different hash. Measured,
            # not guessed: the five files were byte-identical either way.
            entry.create_system = 3
            archive.writestr(entry, _normalized(directory / name))
    return buffer.getvalue()


def _normalized(path: Path) -> bytes:
    """The file's bytes with every line ending rewritten to `_LINE_ENDING`.

    Read as bytes and rewritten, not decoded: the point is a fixed archive, and
    decoding would add an encoding assumption these files do not need here.
    """
    return (
        path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", _LINE_ENDING)
    )


def archive_with_etag(directory: Path) -> tuple[bytes, str]:
    """The archive and a strong ETag over it, rebuilt only when a file changes."""
    key = (directory, _fingerprint(directory))
    cached = _cache.get(key)
    if cached is None:
        content = build_archive(directory)
        cached = (content, f'"{sha256(content).hexdigest()}"')
        _cache[key] = cached
    return cached


def etag_matches(header: str | None, etag: str) -> bool:
    """RFC 7232 `If-None-Match`, rather than a string comparison.

    Two forms a plain `in` misses, both of which cost the full body on every
    revalidation — the exact expense the cache and the ETag were added to avoid.
    `*` matches any current representation. And an intermediary is free to
    weaken a strong tag, which nginx does whenever it transforms a response, so
    the client echoes `W/"<sha>"` and an exact match never fires again.
    Comparison is by opaque tag either way, because this ETag is a hash of the
    bytes and means the same thing weak or strong.
    """
    if not header:
        return False
    for candidate in header.split(","):
        tag = candidate.strip()
        if tag == "*":
            return True
        if tag.removeprefix("W/") == etag.removeprefix("W/"):
            return True
    return False


_UNAVAILABLE: Final = AdminErrorResponse(
    code="client_tools_unavailable",
    message=(
        "This build does not carry the Windows client tools. They are copied in "
        "from the `client_tools` build context; see backend/Dockerfile."
    ),
)
"""The envelope every other admin error carries, rather than a hand-written
`{"detail": ...}` that matched neither this application's shape nor FastAPI's.
The frontend parses `code` and `message`; a body with neither is a 503 nothing
on the other side can read."""


@router.get(
    "/windows-codex-app",
    # Declared, because FastAPI infers `application/json` from the return
    # annotation and the committed contract in `frontend/src/lib/generated`
    # is generated from what is declared here. A route that answers with a zip
    # and a document that says otherwise is the drift `lib/api-contract.ts`
    # exists to prevent, arriving through the one route it cannot see.
    response_class=Response,
    responses={
        200: {
            "description": "The switcher, the doctor, the module, the suite and their README.",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        },
        304: {"description": "The archive already held by the caller is current."},
        # Both carry a body, and a `description` alone generates
        # `content?: never`, so a client typed off the committed contract cannot
        # read the message. That is the drift this block exists to close, and
        # leaving it on two status codes over would be the same defect one door
        # along. 403 is reachable because of the scope check below.
        403: {
            "description": "The caller may not hold an API key for these tools to carry.",
            "model": AdminErrorResponse,
        },
        503: {
            "description": "This build does not carry the Windows client tools.",
            "model": AdminErrorResponse,
        },
    },
)
async def download_windows_codex_app_tools(
    request: Request,
    actor: Annotated[Actor, Depends(current_actor)],
    authz: Annotated[AuthorizationPort, Depends(get_authorization)],
) -> Response:
    """The switcher, the doctor, the shared module, the suite and their README.

    `api_key:write_own`, which is narrower than the `chat:use` that
    `GET /admin/gateway` is held to, and narrower deliberately. These scripts
    exist to put an API key into a client, so the audience is whoever may have a
    key to put there. `chat:use` was tried first and is not that check: every
    role in `catalog.py` holds it — `_BASE_SCOPES` grants it, `_AUDITOR_SCOPES`
    lists it again on purpose, `_SERVICE_SCOPES` is barely more than it — so the
    guard refused nobody while its comment claimed to exclude a role that cannot
    hold a key. `api_key:write_own` is the scope that role actually lacks, and
    `catalog.py` says why in the same breath: an auditor who can mint themselves
    a key can act through the gateway, which is the thing the role exists not to
    do. Handing them the tooling for it is the same grant one step earlier.

    Checked here rather than in a use case because there is no domain operation
    to put one around — the response is a file that came with the image.
    """
    authz.require(actor, Scope.API_KEY_WRITE_OWN)

    directory = resolve_tools_directory()
    if directory is None:
        return Response(
            content=_UNAVAILABLE.model_dump_json(),
            status_code=503,
            media_type="application/json",
        )

    content, etag = archive_with_etag(directory)
    # `private` because this is served over a session; `must-revalidate` because
    # a deployment can be replaced under a URL that does not change, and the
    # ETag is what tells the two apart.
    headers = {
        "ETag": etag,
        "Cache-Control": "private, must-revalidate",
        "Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"',
    }
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    return Response(content=content, media_type="application/zip", headers=headers)
