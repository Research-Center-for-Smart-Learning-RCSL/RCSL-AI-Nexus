"""Rendering a TOTP provisioning URI as a QR image.

Server-side because the URI contains the secret. Handing it to a third-party
QR service, which is the usual shortcut, would hand that service everyone's
second factor. Rendering it in the browser instead would mean shipping a QR
library to redraw a value the backend already holds.

`segno` produces PNG with no imaging dependency, which keeps the container
free of a native image stack for the sake of one 160-pixel square.
"""

from __future__ import annotations

import io

import segno
from starlette.responses import Response

SCALE = 6
BORDER = 2


def provisioning_qr_response(provisioning_uri: str) -> Response:
    buffer = io.BytesIO()
    segno.make(provisioning_uri, error="m").save(buffer, kind="png", scale=SCALE, border=BORDER)

    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            # The image *is* the secret. It must not sit in a shared cache, and
            # it must not be written to disk by the browser, so that closing
            # the enrolment page ends its existence on that machine.
            "Cache-Control": "no-store, private",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
