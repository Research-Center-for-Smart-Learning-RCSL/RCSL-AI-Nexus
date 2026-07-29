"""What an upload is allowed to be.

The three attacker-controlled parts of an upload, each tested for the property
`upload_policy` claims: the size cannot exhaust the parser, the declared type
cannot steer bytes to a parser written for something else, and the filename is
made safe to display rather than trusted.
"""

from __future__ import annotations

import pytest

from app.domain.exceptions import UploadRejectedError
from app.domain.services.upload_policy import (
    MAX_UPLOAD_BYTES,
    assert_upload_allowed,
    sanitise_filename,
)

PDF = b"%PDF-1.7\nbody"
DOCX = b"PK\x03\x04rest of a zip"


def allow(media_type: str, data: bytes, size: int | None = None) -> None:
    assert_upload_allowed(
        media_type=media_type, size_bytes=len(data) if size is None else size, data=data
    )


def test_accepts_the_allowlisted_types_with_matching_magic() -> None:
    allow("application/pdf", PDF)
    allow(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        DOCX,
    )
    # Text has no magic number, so it is accepted on the declared type alone.
    allow("text/plain", b"just words")
    allow("text/markdown", b"# heading")


def test_rejects_a_type_outside_the_allowlist() -> None:
    # The legacy Office formats are absent on purpose: their parsers are the
    # worst of the family and the formats convert.
    for media_type in ("application/msword", "image/svg+xml", "application/zip"):
        with pytest.raises(UploadRejectedError):
            allow(media_type, b"anything")


def test_rejects_bytes_that_do_not_match_the_declared_type() -> None:
    """The declared type decides which parser runs, so this is the case that
    matters: a zip's bytes handed to the PDF parser."""
    with pytest.raises(UploadRejectedError):
        allow("application/pdf", DOCX)
    with pytest.raises(UploadRejectedError):
        allow(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            PDF,
        )


def test_rejects_an_empty_file() -> None:
    with pytest.raises(UploadRejectedError):
        allow("text/plain", b"")


def test_rejects_over_the_size_ceiling_and_accepts_exactly_at_it() -> None:
    with pytest.raises(UploadRejectedError):
        allow("text/plain", b"x", size=MAX_UPLOAD_BYTES + 1)
    allow("text/plain", b"x", size=MAX_UPLOAD_BYTES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32", "system32"),
        ("/absolute/path/report.pdf", "report.pdf"),
        ("ordinary name.pdf", "ordinary name.pdf"),
        ("...", "document"),
        ("", "document"),
    ],
)
def test_sanitise_filename_keeps_the_last_segment_and_drops_separators(
    raw: str, expected: str
) -> None:
    """Not a path defence — no path is built from this — but the string is
    rendered in the UI and written to the audit log, where a separator or a
    control character is a spoofing tool."""
    assert sanitise_filename(raw) == expected


def test_sanitise_filename_strips_control_characters() -> None:
    cleaned = sanitise_filename("report‮.fdp.exe")
    assert "‮" not in cleaned


def test_sanitise_filename_is_bounded() -> None:
    assert len(sanitise_filename("a" * 5000)) <= 200
