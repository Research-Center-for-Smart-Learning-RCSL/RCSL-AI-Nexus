"""The Windows operator tools, served by the platform that issues the keys.

Until now the management UI handed out a PowerShell snippet that fetched the
whole repository archive from GitHub `main`. That is three separate problems
wearing one coat. It put deployment-shaped content on operator laptops to
deliver four files; it tracked a moving branch, so two operators following the
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
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Response

from app.domain.entities.actor import Actor
from app.interfaces.http.middleware.identity import current_actor

router = APIRouter(prefix="/client-tools", tags=["client-tools"])

ARCHIVE_FILENAME: Final = "rcsl-codex-app-tools.zip"

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


def resolve_tools_directory() -> Path | None:
    """The packaged tools, or `None` when this build does not carry them.

    Absence is reported rather than raised at import time, so that an image
    built without the extra build context still starts and says what is wrong at
    the one endpoint that needs it.
    """
    here = Path(__file__).resolve()
    candidates = (
        here.parents[4] / _IMAGE_LOCATION,
        here.parents[5] / _SOURCE_LOCATION,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def build_archive(directory: Path) -> bytes:
    """A deterministic zip of everything in `directory`.

    Sorted names, a fixed timestamp, a fixed mode and a fixed originating
    system, so that the bytes depend on the scripts and on nothing else, whoever
    builds it. An operator who downloads twice and compares should find no
    difference to explain, and the archive a maintainer builds from a checkout
    is the archive the deployment serves.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in directory.rglob("*") if p.is_file()):
            entry = zipfile.ZipInfo(
                path.relative_to(directory).as_posix(),
                date_time=_FIXED_TIMESTAMP,
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            # `ZipInfo` takes this from the host that builds the archive: 0 for
            # MS-DOS on Windows and 3 for Unix everywhere else. It is one byte
            # per entry in the central directory and does not change the length,
            # so an archive built from a Windows checkout and one built inside
            # the Linux image were the same size and a different hash. Measured,
            # not guessed: the five files were byte-identical either way.
            entry.create_system = 3
            archive.writestr(entry, path.read_bytes())
    return buffer.getvalue()


@router.get("/windows-codex-app")
async def download_windows_codex_app_tools(
    actor: Annotated[Actor, Depends(current_actor)],
) -> Response:
    """The switcher, the doctor, the shared module and their README, as a zip.

    `actor` is here to require a session, which is the whole of the
    authorization: these are the same scripts published in a public repository,
    so the point is not secrecy but provenance.
    """
    directory = resolve_tools_directory()
    if directory is None:
        return Response(
            content=(
                '{"detail":"This build does not carry the Windows client tools. '
                "They are copied in from the `client_tools` build context; see "
                'backend/Dockerfile."}'
            ),
            status_code=503,
            media_type="application/json",
        )

    return Response(
        content=build_archive(directory),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{ARCHIVE_FILENAME}"'},
    )
