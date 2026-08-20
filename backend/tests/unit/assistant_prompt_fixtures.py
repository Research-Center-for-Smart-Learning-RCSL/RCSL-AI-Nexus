"""The assistant's instructions, which are the only description of this
platform the model ever sees.

The risk being tested is not that the prompt is badly worded. It is that the
prompt states a rule the platform does not enforce — confidently, to the one
person in the building who does not already know the rule. So what is pinned
here is that the figures in it come from the live configuration rather than
from prose somebody typed once, and that the boundary between instruction and
the operator's own data cannot be talked across.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.assist_operator import (
    AssistOperator,
    build_system_prompt,
)
from app.domain.entities.actor import Actor, Role, Scope
from app.interfaces.http.assistant_proposal import PROPOSAL_CONTRACT
from app.shared.clock import FixedClock

NOW = datetime(2026, 7, 29, 9, 30, tzinfo=UTC)


def prompt(**overrides: object) -> str:
    kwargs: dict = {
        "surface": "api_keys.create",
        "issuable_capabilities": ["chat", "code"],
        "gateway_base_url": "https://api.example.test",
        "max_lifetime_days": 90,
        "max_context_length": 122880,
        "today": "2026-07-29",
        "context": None,
        "nonce": "deadbeefdeadbeef",
        "output_contract": PROPOSAL_CONTRACT,
    }
    kwargs.update(overrides)
    return build_system_prompt(**kwargs)


def operator() -> Actor:
    return Actor(
        id="u1",
        display="op@example.test",
        role=Role.ADMIN,
        source="tailnet",
        scopes=frozenset({Scope.CHAT_USE}),
    )


def build() -> AssistOperator:
    return AssistOperator(
        chat=None,  # type: ignore[arg-type]  # not reached; no generation is started
        authz=RoleAuthorization(),
        clock=FixedClock(NOW),
        gateway_base_url="https://api.example.test",
        max_lifetime_days=90,
        max_context_length=122880,
        max_tokens=1536,
    )
