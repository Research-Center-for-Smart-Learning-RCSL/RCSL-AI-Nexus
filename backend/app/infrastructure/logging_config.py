"""Application logging.

**Why this file exists.** Until 2026-08-03 nothing in this tree configured
logging at all. The root logger therefore had no handler, and Python's
`logging.lastResort` fallback took every record — a handler that emits at
WARNING and silently discards everything below it. Every `logger.info` in the
application was written, formatted and thrown away, in all three processes,
since the first deploy.

That is not a cosmetic loss, and the day it was found says why. Bringing up the
public entrance produced `400 untrusted_proxy` on every request through it.
That code has three causes — a wrong shared secret, an absent
`X-Forwarded-For`, and one that will not parse — and the response deliberately
distinguishes none of them, because telling a caller which half of the
perimeter it failed is telling an attacker which half to work on. The operator
is supposed to read the difference here instead, from the one line
`geo_middleware` writes for exactly this purpose:

    perimeter_rejected path=/admin/me code=untrusted_proxy detail=...

It had never appeared. The cause was established by probing the deployment from
outside with deliberately wrong values until the responses narrowed it down,
which is the diagnosis this line exists to make unnecessary. **The control was
working correctly and its own record of firing did not exist** — the same shape
of defect as the audit gap closed on 2026-08-02, where every administrative
action was recorded and no authentication event was.

**The `app` logger is configured, not the root**, and that is deliberate rather
than cautious. Raising the root to INFO also raises `httpx`, which logs a line
per request — including one per generation to the model runtime, on the hot
path, saying nothing this project does not already record in `usage_records`.
Every module here uses `logging.getLogger(__name__)` under the `app` package,
so this reaches all of them and nothing else.

`uvicorn` configures its own loggers and is untouched by this; its access log
is the reason the 400s above were visible as *status codes* while the reason
for them was not.
"""

from __future__ import annotations

import logging
import sys

from app.infrastructure.config import Settings

APP_LOGGER = "app"


def configure_logging(settings: Settings) -> None:
    """Install one stdout handler on the `app` logger tree.

    Idempotent: existing handlers are dropped first, because `create_app` runs
    more than once in a test session and each call would otherwise add another
    handler and multiply every line.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

    logger = logging.getLogger(APP_LOGGER)
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
    logger.addHandler(handler)
    logger.setLevel(settings.log_level.upper())

    # Not propagated to the root. With no root handler the record would reach
    # `lastResort` and print a second, unformatted copy of everything at
    # WARNING and above.
    logger.propagate = False
