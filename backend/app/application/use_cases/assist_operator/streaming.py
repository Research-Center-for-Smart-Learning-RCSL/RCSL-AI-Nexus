"""Management-assistant streaming use case."""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import CompletionChunk, Message, MessageRole
from app.domain.exceptions import AssistantUnavailableError, NoAvailableModelError
from app.domain.ports.security_ports import AuthorizationPort
from app.shared.clock import Clock

from ..route_chat_request import RouteChatRequest
from .prompt import ASSIST_CAPABILITY, build_system_prompt


class AssistOperator:
    """Streams an answer for the management assistant drawer.

    Delegates to `RouteChatRequest` unchanged, which is what keeps every
    resource guardrail in force: the concurrency slot, the token ceiling, the
    wall-clock deadline and cancel-on-disconnect apply here exactly as they
    apply to inference from outside. They protect the hardware, and a drawer in
    the management UI can exhaust unified memory as easily as anything else can
    (docs/architecture/security.md §4.3).
    """

    required_scope = Scope.CHAT_USE
    """The scope for reaching inference at all, the same one `/admin/chat` and
    `ListCapabilities` require. Not a scope of its own: a new one would have to
    be granted to both roles to be useful, which is a table entry that says
    nothing, and the assistant reads no data the caller cannot already see on
    the screen it is describing.
    """

    def __init__(
        self,
        chat: RouteChatRequest,
        authz: AuthorizationPort,
        clock: Clock,
        *,
        gateway_base_url: str,
        max_lifetime_days: int,
        max_context_length: int,
        max_tokens: int,
    ) -> None:
        self._chat = chat
        self._authz = authz
        self._clock = clock
        self._gateway_base_url = gateway_base_url
        self._max_lifetime_days = max_lifetime_days
        # Read rather than written into the prompt text: the ceiling has been
        # raised four times, and every place that copied the number instead of
        # asking for it was still quoting an old one when the audit of
        # 2026-08-18 went looking.
        self._max_context_length = max_context_length
        self._max_tokens = max_tokens

    def build_prompt(
        self,
        *,
        surface: str,
        issuable_capabilities: Sequence[str],
        context: dict[str, object] | None,
        output_contract: str,
    ) -> str:
        return build_system_prompt(
            surface=surface,
            issuable_capabilities=issuable_capabilities,
            gateway_base_url=self._gateway_base_url,
            max_lifetime_days=self._max_lifetime_days,
            max_context_length=self._max_context_length,
            today=self._clock.now().date().isoformat(),
            context=context,
            # Per request. A fixed marker would be guessable by anyone who has
            # read this file, which includes anyone who can name an API key.
            nonce=secrets.token_hex(8),
            output_contract=output_contract,
        )

    async def execute(
        self,
        actor: Actor,
        *,
        surface: str,
        issuable_capabilities: Sequence[str],
        context: dict[str, object] | None,
        history: Sequence[Message],
        output_contract: str,
    ) -> AsyncGenerator[CompletionChunk, None]:
        """`history` carries only user and assistant turns.

        The endpoint's schema has no `system` role, so the instructions
        assembled below cannot be displaced by anything a client sends. That is
        the one difference from `/admin/chat` that matters, and it is enforced
        by the shape of `AssistMessageIn` rather than by filtering here — a
        filter is something a later edit can forget.
        """
        self._authz.require(actor, self.required_scope)

        messages = [
            Message(
                role=MessageRole.SYSTEM,
                content=self.build_prompt(
                    surface=surface,
                    issuable_capabilities=issuable_capabilities,
                    context=context,
                    output_contract=output_contract,
                ),
            ),
            *history,
        ]

        generation = self._chat.execute(
            actor,
            ASSIST_CAPABILITY,
            messages,
            self._max_tokens,
            # Never. Deliberation is what makes a model useless in a drawer,
            # and this is a lookup-and-explain task rather than a hard one.
            # Expressed as suppression, which is the only direction the
            # runtimes accept; see `ModelRuntimePort.generate`.
            thinking=False,
        )

        try:
            async with aclosing(generation) as stream:
                async for chunk in stream:
                    yield chunk
        except NoAvailableModelError as exc:
            # Only ever raised here because no policy names `assist`, or because
            # the one that does points at a model that cannot serve. Both are
            # fixed under Routing, and the generic message sends the operator to
            # look at node load instead.
            raise AssistantUnavailableError(detail=str(exc)) from exc
