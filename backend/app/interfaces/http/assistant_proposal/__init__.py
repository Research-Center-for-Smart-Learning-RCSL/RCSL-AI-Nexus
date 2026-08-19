"""Stable proposal collection facade."""

from .collector import ProposalCollector
from .extraction import _final_visible, _visible_prefix
from .policy import (
    NO_PROPOSAL_CONTRACT,
    PROPOSAL_CLOSE,
    PROPOSAL_CONTRACT,
    PROPOSAL_OPEN,
    PROPOSAL_SURFACES,
)

__all__ = [
    "NO_PROPOSAL_CONTRACT",
    "PROPOSAL_CLOSE",
    "PROPOSAL_CONTRACT",
    "PROPOSAL_OPEN",
    "PROPOSAL_SURFACES",
    "ProposalCollector",
    "_final_visible",
    "_visible_prefix",
]
