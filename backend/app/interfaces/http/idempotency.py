"""The `Idempotency-Key` header (final spec §5 on #24).

Optional, scoped to the caller's tenant, and honoured while node agents are
enabled: a repeat of a key is answered from the attempt it was bound to and
never run again. With direct runtimes the header is accepted and has no
effect, because there is no attempt record to answer a repeat from.

The identity carries the body **as the client sent it** (`exclude_unset`), so
an omitted field is absent from the hash rather than present as a default
(decision Q4).
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header
from pydantic import BaseModel

from app.domain.entities.attempt import RequestIdentity
from app.domain.exceptions import InvalidIdempotencyKeyError

_KEY = re.compile(r"[\x21-\x7e]{1,120}")
"""Visible ASCII without spaces; 120 leaves room for the `k:` namespace in the
128-character `request_id` column."""

IdempotencyKeyDep = Annotated[str | None, Header(alias="Idempotency-Key")]


def request_identity(key: str | None, shape: str, body: BaseModel) -> RequestIdentity:
    if key is not None and not _KEY.fullmatch(key):
        raise InvalidIdempotencyKeyError(detail=f"rejected Idempotency-Key of length {len(key)}")
    return RequestIdentity(
        key=key, shape=shape, body=body.model_dump(mode="json", exclude_unset=True)
    )
