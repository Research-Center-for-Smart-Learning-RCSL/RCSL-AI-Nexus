import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def _default_gateway() -> str:
    """`TAILNET_IP` from `.env`, not loopback.

    The gateway deliberately publishes on the tailnet address rather than
    `0.0.0.0` or `127.0.0.1` (see the README, "Two things that look like
    mistakes"), so a loopback default would fail on every real deployment and
    succeed only where `TAILNET_IP=127.0.0.1`, which is the dev-machine value
    in `.env.example`. Reading the same variable Compose reads keeps the two
    from disagreeing.
    """
    env = REPO / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TAILNET_IP" and value.split("#")[0].strip():
                return f"http://{value.split('#')[0].strip()}:8000"
    return "http://127.0.0.1:8000"


GATEWAY = os.environ.get("NEXUS_GATEWAY", _default_gateway()).rstrip("/")
BASE = f"{GATEWAY}/v1/chat/completions"
CLIENT_IP = os.environ.get("NEXUS_CLIENT_IP", "168.95.1.1")  # Chunghwa Telecom, TW
MODEL = os.environ.get("NEXUS_MODEL", "chat")  # the capability, not a model name
THINK = {"true": True, "false": False}.get(os.environ.get("NEXUS_THINK", "").lower())


def _required(env: str, secret_file: str, what: str) -> str:
    """Resolved on first use rather than at import, so `--help` and a syntax
    check work on a machine that has neither."""
    value = os.environ.get(env)
    if value:
        return value.strip()
    path = REPO / "secrets" / secret_file
    if path.is_file():
        return path.read_text().strip()
    sys.exit(f"{what}: set {env}, or run from a checkout with secrets/{secret_file}")


def key() -> str:
    value = os.environ.get("NEXUS_API_KEY")
    if not value:
        sys.exit(
            "NEXUS_API_KEY is not set. Issue a key for the capability under test "
            "from the management UI (API keys), or see "
            "docs/runbooks/connect-an-agent-client.md. The plaintext is shown once."
        )
    return value.strip()

# --- tools ---------------------------------------------------------------
