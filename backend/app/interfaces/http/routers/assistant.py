"""The management assistant drawer, served by the admin API.

Alongside `admin_chat.py` rather than inside it. Both stream a completion and
both authorise by user identity, but they are different products: one is a chat
panel the operator steers, the other is a helper bound to a screen whose
instructions the operator must not be able to replace. Folding them together
would mean one request schema that has to accept a `system` message for one
caller and refuse it for the other, and the refusal would then be a branch
rather than the absence of a field.

This handler is the composition point for the two halves of the assistant, and
it is where they are made to agree: the capability list that goes into the
prompt is the same object that validates the proposal coming back, so the
assistant cannot recommend something the form would then reject.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.domain.entities.actor import Actor
from app.domain.entities.chat import Message, MessageRole
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.di import AssistOperatorDep, ListCapabilitiesDep
from app.interfaces.http import sse
from app.interfaces.http.assistant_proposal import (
    NO_PROPOSAL_CONTRACT,
    PROPOSAL_CONTRACT,
    PROPOSAL_SURFACES,
    ProposalCollector,
)
from app.interfaces.http.middleware.identity import current_actor
from app.interfaces.http.schemas.assistant_schemas import AssistRequest
from app.shared.clock import SystemClock

router = APIRouter(tags=["assistant"])


@router.post("/assistant")
async def assist(
    body: AssistRequest,
    actor: Annotated[Actor, Depends(current_actor)],
    use_case: AssistOperatorDep,
    capabilities: ListCapabilitiesDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Always streaming, like `/admin/chat`, and for the same reason: a drawer
    that shows nothing for twenty seconds reads as broken."""
    # One read, two consumers. The prompt tells the operator what they may issue
    # a key for and the collector refuses a proposal naming anything else, so a
    # single list is not a convenience here — two reads could disagree across a
    # policy edit landing mid-request, and the visible symptom would be a card
    # that vanishes for no stated reason.
    issuable = await capabilities.execute(actor)

    history = [Message(role=MessageRole(m.role), content=m.content) for m in body.messages]

    collector = ProposalCollector(
        now=SystemClock().now(),
        servable_capabilities=issuable,
        max_lifetime_days=settings.api_key_max_lifetime_days,
    )

    generation = collector.wrap(
        use_case.execute(
            actor,
            surface=body.surface,
            issuable_capabilities=issuable,
            context=_context_for(body),
            history=history,
            # Only where a proposal has a form to land in. Elsewhere the
            # model is not shown the format at all, which is a stronger
            # guarantee than an instruction not to use it.
            output_contract=(
                PROPOSAL_CONTRACT if body.surface in PROPOSAL_SURFACES else NO_PROPOSAL_CONTRACT
            ),
        )
    )

    # Primed through the collector, so an authorization or routing failure is
    # still a status code rather than a 200 containing an error frame. See
    # interfaces/http/sse.py.
    first = await sse.prime(generation)

    return sse.streaming_response(
        completion_id=sse.new_completion_id(),
        created=sse.created_now(),
        model="assist",
        generation=generation,
        first=first,
        trailer=collector.trailer,
    )


def _context_for(body: AssistRequest) -> dict[str, object] | None:
    """What the operator's screen contributes, as data.

    Built from the typed request rather than passed through, so the block
    interpolated into the prompt holds only fields this function names. A
    dictionary forwarded verbatim would carry whatever a future frontend
    happened to put in it, and the one thing that must never travel here — the
    plaintext from `IssuedApiKeyResponse` — is exactly what a create dialog has
    in scope at the moment it would be tempting to send "the whole state".
    """
    context: dict[str, object] = {"screen": body.surface}
    if body.key_id is not None:
        context["editing_key_id"] = body.key_id
    if body.draft is not None:
        context["form_draft"] = body.draft.model_dump(exclude_none=True)
    return context if len(context) > 1 else None
