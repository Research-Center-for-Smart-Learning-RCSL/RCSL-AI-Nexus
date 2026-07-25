"""Building the single-use invitation and reset links.

Shared by the users and tenants routers so the path constants and the URL shape
live in one place: a change to the accept-invite route then updates every caller
at once, rather than leaving one emitting a link that 404s.
"""

from __future__ import annotations

from urllib.parse import quote

from app.domain.entities.invitation import InvitationPurpose
from app.infrastructure.config import Settings

ONBOARD_PATH = "/accept-invite"
RESET_PATH = "/reset-password"


def invitation_url(settings: Settings, purpose: InvitationPurpose, token: str) -> str:
    """The management-UI URL a recipient opens to accept an invitation or reset
    a password. Points at `admin_base_url` (the public entrance), since a tailnet
    URL is useless to someone who has no Tailscale; see config.admin_base_url."""
    path = ONBOARD_PATH if purpose is InvitationPurpose.ONBOARD else RESET_PATH
    return f"{settings.admin_base_url.rstrip('/')}{path}?token={quote(token)}"
