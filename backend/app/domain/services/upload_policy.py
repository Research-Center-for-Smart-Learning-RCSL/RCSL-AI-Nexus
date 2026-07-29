"""What an upload is allowed to be.

Three things about an upload come from whoever is uploading, and each is a
distinct problem (security.md section 7.3):

- **The bytes** are fed to a parser with a CVE history. Nothing here can make
  that safe; the parser's isolation does. What this can do is bound the size,
  so a single upload cannot exhaust the parser's memory or the volume.
- **The media type** decides which parser runs. It is matched against an
  allowlist and, where the format has one, against the file's own magic bytes,
  so a declared type cannot steer the bytes to a parser that was not written
  for them.
- **The filename** is the classic path traversal. It is never used to build a
  path at all (storage keys come from a generated id), so sanitising it here is
  about what is safe to *display*, not about what is safe to open.
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.exceptions import UploadRejectedError

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
"""32 MiB. Above the research PDFs this is for and far below what would let one
upload occupy the parser container's memory limit. The nginx `client_max_body_size`
in deployment.md section 8 is 64m, so this is the tighter of the two and the
one that produces a clean error rather than a truncated request."""

MAX_FILENAME_LENGTH = 200

ALLOWED_MEDIA_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "md",
}
"""Media type to the extension shown in the UI.

An allowlist, not a denylist, and short on purpose: every entry is a parser
this deployment runs, and adding one means accepting that parser's CVE surface.
Legacy `.doc` and `.xls` are absent deliberately — the parsers for them are the
worst of the family, and the formats convert.
"""

_MAGIC: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    # docx is a zip container. Every Office Open XML file starts with the local
    # file header, so this catches a renamed executable without unzipping
    # anything, which is itself a parsing step best left to the isolated side.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04",
}
"""Formats whose first bytes are fixed. The text types have no magic number, so
they are accepted on the declared type alone; that is safe because their parser
is a decode, not a format reader."""

_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\- ]", flags=re.UNICODE)


def assert_upload_allowed(*, media_type: str, size_bytes: int, data: bytes) -> None:
    """Raise `UploadRejectedError` unless this upload may be stored and parsed."""
    if size_bytes <= 0:
        raise UploadRejectedError(detail="the uploaded file is empty")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise UploadRejectedError(
            detail=f"upload is {size_bytes} bytes, over the {MAX_UPLOAD_BYTES} limit"
        )
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise UploadRejectedError(detail=f"media type {media_type!r} is not accepted")

    magic = _MAGIC.get(media_type)
    if magic is not None and not data.startswith(magic):
        # The declared type decides which parser runs, so a mismatch here is an
        # attempt to hand one parser another format's bytes rather than a
        # mislabelled upload worth being lenient about.
        raise UploadRejectedError(detail=f"file contents do not match {media_type!r}")


def sanitise_filename(raw: str) -> str:
    """A filename safe to store and display, derived from an untrusted one.

    Not a path defence: no path is ever built from this. It exists because the
    string is rendered in the management UI and written to the audit log, where
    a control character or a right-to-left override is a spoofing tool rather
    than a traversal one. Normalising to NFC first means two visually identical
    names do not survive as different strings.
    """
    normalised = unicodedata.normalize("NFC", raw).strip()
    # Take the last segment under either separator, so a browser that sent a
    # full path (some do, on some platforms) yields the name rather than a
    # string containing slashes.
    normalised = normalised.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", normalised).strip(". ")
    if not cleaned:
        return "document"
    return cleaned[:MAX_FILENAME_LENGTH]
