"""What a caller can actually ask for.

A capability is servable when a routing policy names it: the policy is what
turns `model: "chat"` into a model on a node, and without one the request can
only ever answer "no available model". Whether that model is loaded *right
now* is a different question, answered at request time and deliberately not
here — a list that flickered with node state would be worse than one that
describes the deployment.

Two callers, one answer. The gateway serves it as `GET /v1/models` so that
OpenAI client libraries can discover what to put in the `model` field, and the
management UI serves it so the key-issuing form can offer only capabilities
that will work. Deriving it twice is how the two would come to disagree.
"""

from __future__ import annotations

from app.domain.entities.actor import Actor, Scope
from app.domain.ports.repositories import RoutingPolicyRepositoryPort
from app.domain.ports.security_ports import AuthorizationPort


class ListCapabilities:
    def __init__(self, policies: RoutingPolicyRepositoryPort, authz: AuthorizationPort) -> None:
        self._policies = policies
        self._authz = authz

    async def execute(self, actor: Actor) -> list[str]:
        """Requires `chat:use`, the same scope inference requires.

        Not `routing:read`, which is the scope for editing what serves a
        capability and which a member deliberately does not hold. Naming it
        here would make the list readable only by administrators, and the
        people who need it are the ones integrating against a key.
        """
        self._authz.require(actor, Scope.CHAT_USE)

        servable = sorted({policy.capability for policy in await self._policies.list_all()})
        # Narrowed to the key's own list, so the answer is "what may I call"
        # rather than "what exists". A person on an admin entrance carries None
        # and sees all of them.
        return [name for name in servable if actor.may_use(name)]
