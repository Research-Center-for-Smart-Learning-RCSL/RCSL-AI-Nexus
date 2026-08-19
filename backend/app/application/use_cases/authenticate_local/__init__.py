"""Stable explicit compatibility facade."""

from .facade import (
    AuthenticateLocal,
)
from .results import (
    PasswordResult,
)

__all__ = [
    "AuthenticateLocal",
    "PasswordResult",
]
