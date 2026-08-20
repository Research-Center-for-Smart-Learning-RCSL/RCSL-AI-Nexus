"""HTTP resolution boundary."""

from __future__ import annotations

from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.api_key import ApiKey
from app.domain.entities.capability import ISSUABLE_CAPABILITIES


def _scopes_for(key: ApiKey) -> frozenset[Scope]:
    """Map the key's stored capability names onto scopes.

    Every inference capability grants the same scope, because there is one
    inference use case and `CHAT_USE` is the permission to reach it. Which
    capability was actually asked for is enforced separately, against
    `Actor.allowed_capabilities`.

    Still a fixed rule rather than a lookup: the stored list can only narrow
    what a key of this kind may ever hold, so a compromised database row cannot
    promote a key into the control plane. What it can no longer do is disagree
    about which names exist. An explicit table here listed only `chat`, which
    made a key issued for any of the other four powerless while the form
    offering the choice presented it as meaningful; a table whose values were
    then all identical would have carried no information and reintroduced that
    bug the next time a capability was added.
    """
    scopes = {Scope.CHAT_USE for c in key.scopes if c in ISSUABLE_CAPABILITIES}
    if scopes:
        # Reading your own usage is implied by being able to consume anything.
        # Granted with the first real scope rather than unconditionally, so a
        # key issued with none stays genuinely powerless.
        scopes.add(Scope.USAGE_READ_OWN)
    return frozenset(scopes)


def _actor_for_key(key: ApiKey) -> Actor:
    """What an API key is, as an actor. Built here rather than inline so the
    request can remember it before the checks that may refuse it."""
    return Actor(
        id=key.owner_id,
        display=key.key_id,
        role=Role.SERVICE,
        source="api_key",
        scopes=_scopes_for(key),
        api_key_id=key.key_id,
        # The key's tenant, so usage is attributed to it and, once the knowledge
        # base exists, a key can only ever reach its own tenant's data.
        tenant_id=key.tenant_id,
        # What the key was issued for, checked against the capability each
        # request names. Without it the list was decorative: any valid key
        # reached every capability the deployment could route.
        #
        # Intersected rather than passed through, for the same reason
        # `_scopes_for` is a fixed rule: a stored list may narrow what a key
        # reaches and must never widen it. `ManageApiKeys` already refuses to
        # issue a routable-only capability, so this only matters for a row that
        # did not come from it — but that row is exactly the threat the rule
        # exists for, and without the intersection a single direct database
        # write would let a gateway key reach `assist`, which serves the
        # management assistant.
        allowed_capabilities=key.scopes & ISSUABLE_CAPABILITIES,
        # This key's declared substitute for a capability it was not issued
        # for, or None to refuse — which is what every key without one does.
        # Passed through rather than intersected, because `Actor.capability_for`
        # re-checks it against the set above and a value outside it therefore
        # decides nothing. The one rule, in the one place that reads it.
        default_capability=key.default_capability,
        # The key-side debug window, carried onto the actor so the application
        # layer can read it. `grant_debug_detail` above sets the same value
        # into a contextvar for the error envelope; `RouteChatRequest` decides
        # full prompt logging from this one, because it sits two layers away
        # from the contextvar and reaching for it there would invert the
        # dependency the hexagon exists to hold. See §9.2.
        debug_logging_until=key.debug_logging_until,
    )
