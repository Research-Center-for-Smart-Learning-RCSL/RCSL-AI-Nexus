"""The composed `Settings` must keep the configuration its declarations carry.

`Settings` is assembled from four bases. Three of them derive from
`BaseSettings` directly, so each carries a full copy of pydantic's *defaults*,
and those beat the config `SettingDeclarations` inherits from `CoreSettings`
when pydantic merges across bases. The composed class was built with
`secrets_dir=None`, `env_file=None` and `extra="forbid"` on 2026-08-20, which
meant no file under `/run/secrets` was read: in production every secret held
the placeholder committed in `.env.example` and `Settings()` refused to
construct, so the deploy stopped at the `migrate` one-shot.

It failed closed, which is the only reason this was an outage of a few minutes
rather than a platform quietly running on a published pepper. The unit suite
could not see it -- every existing test passes its secrets as keyword
arguments, and `/run/secrets` does not exist on a test machine, so the source
that was missing had nothing to read either way. These tests are about the
configuration itself for that reason.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from app.infrastructure.config import Settings
from app.infrastructure.config.core import SETTINGS_CONFIG


def test_composed_settings_keeps_every_declared_config_key() -> None:
    """The assertion is over the whole dict rather than over `secrets_dir`
    alone: on a machine with no `/run/secrets` that key is `None` in both the
    correct and the broken build, so a test naming only it would have passed
    through the failure it exists to catch."""
    for key, expected in SETTINGS_CONFIG.items():
        assert Settings.model_config.get(key) == expected, (
            f"the composed Settings lost `{key}`; a mixin's BaseSettings "
            f"defaults won the merge against CoreSettings"
        )


def test_secret_files_populate_fields(tmp_path) -> None:
    """What `secrets_dir` is for, pinned as behaviour: a file whose name is the
    field's populates it, so the value never passes through the environment."""
    (tmp_path / "api_key_pepper").write_text("pepper-from-a-file")
    (tmp_path / "qdrant_api_key").write_text("qdrant-from-a-file")

    class _FromFiles(Settings):
        model_config = SettingsConfigDict(**{**Settings.model_config, "secrets_dir": str(tmp_path)})

    settings = _FromFiles(
        env="production",
        auth_mode="tailnet",
        totp_encryption_key="real-totp-key",
        session_signing_key="real-session-key",
        proxy_shared_secret="real-proxy-secret",
        metrics_scrape_token="real-metrics-token",
        database_url="postgresql+asyncpg://nexus:real@db:5432/nexus",
    )

    assert settings.api_key_pepper == "pepper-from-a-file"
    assert settings.qdrant_api_key == "qdrant-from-a-file"
