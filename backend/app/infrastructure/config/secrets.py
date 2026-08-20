"""Flat secrets setting declarations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class SecretsSettings(BaseSettings):
    api_key_pepper: str = Field(default="dev-pepper-not-for-production")

    api_key_pepper_previous: str = Field(
        default="",
        description="Set during a pepper rotation so keys signed with the old "
        "value keep verifying until they are reissued.",
    )

    totp_encryption_key: str = Field(default="dev-totp-key-not-for-production")

    session_signing_key: str = Field(default="dev-session-key-not-for-production")

    proxy_shared_secret: str = Field(default="dev-proxy-secret-not-for-production")

    qdrant_api_key: str = Field(default="dev-qdrant-key-not-for-production")
    """Qdrant ships with **no authentication at all** (security.md section 10),
    and the whole knowledge base is readable to anything that reaches it. Set
    through `QDRANT__SERVICE__API_KEY` on the service and read from the same
    file secret here, so the two cannot drift."""
