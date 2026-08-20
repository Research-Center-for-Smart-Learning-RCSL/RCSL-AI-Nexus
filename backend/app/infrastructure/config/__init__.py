"""Flat environment settings with separated declaration and policy boundaries."""

from functools import lru_cache

from .core import SECRETS_DIR, AuthMode, CacheBackend, Environment
from .declarations import SettingDeclarations
from .derived import DerivedValuesMixin
from .production_validation import ProductionValidationMixin
from .secret_validation import SecretValidationMixin


class Settings(
    DerivedValuesMixin, SecretValidationMixin, ProductionValidationMixin, SettingDeclarations
):
    pass


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = [
    "AuthMode",
    "CacheBackend",
    "Environment",
    "SECRETS_DIR",
    "Settings",
    "get_settings",
]
