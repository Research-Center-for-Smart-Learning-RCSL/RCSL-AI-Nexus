"""Flat environment settings with separated declaration and policy boundaries."""

from functools import lru_cache

from .core import SECRETS_DIR, SETTINGS_CONFIG, AuthMode, CacheBackend, Environment
from .declarations import SettingDeclarations
from .derived import DerivedValuesMixin
from .production_validation import ProductionValidationMixin
from .secret_validation import SecretValidationMixin


class Settings(
    DerivedValuesMixin, SecretValidationMixin, ProductionValidationMixin, SettingDeclarations
):
    # Restated, and not decoration. The three mixins derive from `BaseSettings`
    # directly, so each carries a full copy of *its* defaults, and pydantic's
    # merge across bases lets those beat the config `SettingDeclarations`
    # inherits from `CoreSettings`. The composed class was therefore built with
    # `secrets_dir=None`, `env_file=None` and `extra="forbid"` -- meaning no
    # file under /run/secrets was read at all, so in production every secret
    # held its committed placeholder and `Settings()` refused to construct.
    # It fails closed, which is why this surfaced as a deploy that would not
    # start rather than as a platform running on placeholder keys, and it is
    # invisible to the unit suite because /run/secrets does not exist there.
    model_config = SETTINGS_CONFIG


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
