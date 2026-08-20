"""Stable explicit compatibility facade."""

from .authentication import (
    authenticate_api_key,
    authenticate_api_key_without_quota,
)

__all__ = [
    "authenticate_api_key",
    "authenticate_api_key_without_quota",
]
