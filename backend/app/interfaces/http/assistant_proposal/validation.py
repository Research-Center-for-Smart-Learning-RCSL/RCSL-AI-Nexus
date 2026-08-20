"""Proposal policy validation against the active request context."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.interfaces.http.schemas.assistant_schemas import ProposalOut

logger = logging.getLogger("app.interfaces.http.assistant_proposal")


class ProposalPolicyMixin:
    _now: datetime
    _servable: frozenset[str]
    _max_lifetime: timedelta

    def _within_policy(self, proposal: ProposalOut) -> bool:
        """Apply the rules that require the active capability and expiry policy."""
        fields = proposal.fields

        if proposal.action == "update" and not proposal.key_id:
            logger.info("assistant proposed an update naming no key")
            return False

        if fields.scopes is not None:
            unknown = sorted(set(fields.scopes) - self._servable)
            if unknown:
                logger.info("assistant proposed unservable capabilities %s", unknown)
                return False

        if fields.default_capability is not None and fields.scopes is not None:
            if fields.default_capability not in fields.scopes:
                logger.info(
                    "assistant proposed a default outside the capabilities beside it: %s",
                    fields.default_capability,
                )
                return False

        if fields.expires_at is not None:
            if fields.expires_at <= self._now:
                logger.info("assistant proposed an expiry in the past")
                return False
            if fields.expires_at > self._now + self._max_lifetime:
                logger.info("assistant proposed an expiry beyond the maximum lifetime")
                return False

        return True
