"""The node agent's own settings.

Deliberately not the platform's `Settings`: that class refuses to start
without the password pepper, TOTP key, session key and the rest, none of which
the agent needs or should hold. Like the parser, the agent reads only what it
uses (design revision 1, §2 on #24).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.infrastructure.config.core import SECRETS_DIR

_secrets_dir = str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        secrets_dir=_secrets_dir, extra="ignore", populate_by_name=True
    )

    node_id: str = Field(alias="NODE_AGENT_NODE_ID")
    database_url: str = Field(alias="agent_database_url")
    """A Docker secret: the `nexus_agent` role's URL."""
    token: str = Field(alias="node_agent_token", min_length=32)
    """A Docker secret shared with the gateway and admin entrances."""
    control_token: str | None = Field(default=None, alias="node_agent_control_token", min_length=32)
    """A separate Docker secret for the routes that drain, resume, interrupt,
    reset or restart (#61): the gateway holds the data token and must never be
    able to do any of those. Without it those routes refuse."""

    runtime_base_url: str = Field(
        default="http://host.docker.internal:11434", alias="NODE_AGENT_RUNTIME_URL"
    )
    keep_alive: str = Field(default="-1", alias="OLLAMA_KEEP_ALIVE")
    models_root: Path | None = Field(default=None, alias="OLLAMA_MODELS_PATH")

    lock_dir: Path = Field(default=Path("/var/lib/node-agent/lock"), alias="NODE_AGENT_LOCK_DIR")
    witness_out: Path = Field(
        default=Path("/run/node-agent-witness/out"), alias="NODE_AGENT_WITNESS_OUT"
    )
    witness_challenge: Path = Field(
        default=Path("/run/node-agent-witness/challenge"), alias="NODE_AGENT_WITNESS_CHALLENGE"
    )
    witness_endpoint: str = Field(default="127.0.0.1:11434", alias="NODE_AGENT_WITNESS_ENDPOINT")
    """The listener the host witness must report: Ollama listens on the host's
    loopback, and the VM reaches it through Colima's forwarding."""

    supervisor_requests: Path = Field(
        default=Path("/run/node-agent-supervisor/requests"),
        alias="NODE_AGENT_SUPERVISOR_REQUESTS",
    )
    supervisor_receipts: Path = Field(
        default=Path("/run/node-agent-supervisor/receipts"),
        alias="NODE_AGENT_SUPERVISOR_RECEIPTS",
    )
    supervisor_timeout_s: float = Field(default=180.0, alias="NODE_AGENT_SUPERVISOR_TIMEOUT", gt=0)
    """Long enough for a stop's unload, exit and signal waits and a start."""
    interrupt_deadline_s: float = Field(default=10.0, alias="NODE_AGENT_INTERRUPT_DEADLINE", gt=0)
    """How long an interrupt waits for cancelled senders to return. Not the
    inference timeout: maintenance does not wait for generation (#61)."""

    max_inflight: int = Field(default=4, alias="NODE_AGENT_MAX_INFLIGHT", ge=1)
    max_queued: int = Field(default=4, alias="NODE_AGENT_MAX_QUEUED", ge=1)
    request_timeout_s: float = Field(default=1500.0, alias="REQUEST_TIMEOUT_SECONDS", gt=0)
    queue_deadline_s: float = Field(default=30.0, alias="NODE_AGENT_QUEUE_DEADLINE", gt=0)
    watchdog_s: float = Field(default=2.0, alias="NODE_AGENT_WATCHDOG_SECONDS", gt=0)

    @model_validator(mode="after")
    def _distinct_tokens(self) -> AgentSettings:
        if self.control_token is not None and self.control_token == self.token:
            raise ValueError("node_agent_control_token must differ from node_agent_token")
        return self

    @property
    def dsn(self) -> str:
        """asyncpg takes a plain `postgresql://` URL, not SQLAlchemy's."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
