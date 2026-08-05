"""Resolving `"prompt_template": "name"` into the message that carries it.

Runs *before* `RouteChatRequest`, as a transformation of the messages, for the
reason `ground_chat.py` states at length: `RouteChatRequest` is the most
carefully ordered file in the tree, and putting a database read in front of the
concurrency slot and the `finally` that records usage would disturb an order
that took two reviews to get right. This reads one row and returns a longer
list.

**A missing template is refused, not ignored.** The alternative — serve the
completion without it — is the failure this platform keeps naming: 200, a
plausible answer, and nobody told that the instructions the answer was supposed
to follow were never applied. A caller who mistypes a name, or whose template an
operator has since deleted, gets a 404 saying so.

Selection is opt-in per request, like grounding. Applying a template to every
completion would surprise an API caller who never asked for one, and it would
make the platform's behaviour depend on a row they cannot see.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.chat import Message
from app.domain.exceptions import PromptTemplateNotFoundError
from app.domain.ports.repositories import PromptTemplateRepositoryPort
from app.domain.ports.security_ports import AuthorizationPort
from app.domain.services.prompt_assembly import apply_template


class ApplyPromptTemplate:
    def __init__(self, templates: PromptTemplateRepositoryPort, authz: AuthorizationPort) -> None:
        self._templates = templates
        self._authz = authz

    async def execute(self, actor: Actor, messages: list[Message], name: str) -> list[Message]:
        """The conversation with the named template's system prompt at the front.

        Authorized on `chat:use` rather than `prompt:read`, the same judgement
        `GroundChat` makes about retrieval: a gateway key issued for `chat` is
        entitled to have its question answered under its own tenant's template,
        and requiring a management scope for that would mean every API caller
        needed one. `prompt:read` governs *listing* templates, which is a
        different act — it enumerates what a tenant has authored.

        The repository is tenant-scoped, so the name resolves within the
        caller's tenant and nowhere else; that scope, not this check, is what
        stops a guessed name reaching somebody else's text.
        """
        self._authz.require(actor, Scope.CHAT_USE)

        template = await self._templates.get_by_name(name)
        if template is None:
            raise PromptTemplateNotFoundError(detail=f"no prompt template named {name!r}")
        return apply_template(messages, template.system_prompt)
