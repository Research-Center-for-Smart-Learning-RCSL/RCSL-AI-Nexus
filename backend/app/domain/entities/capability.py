"""The names a request may ask for.

A capability is what a caller names in the `model` field, and what a routing
policy resolves to a model on a node. Several places have to agree on the set:
a key is issued for capabilities, a policy is written for one, and the gateway
maps one onto the scope that reaches inference.

They live here because they disagreed. The set was defined in
`application/use_cases/manage_api_keys.py` and consulted only there, so
`ManageRoutingPolicies.save` accepted any string at all — a policy for `chatt`
stored and audited cleanly, while no key could ever be issued for it — and the
gateway's capability-to-scope table listed only `chat`, which made a key issued
for any of the other four powerless. One definition in the domain is what stops
a further copy appearing the next time a capability is added.

**Two sets, because "may be routed to" and "may be sold to a caller" are
different questions.** They were the same set until the management assistant
needed a capability of its own: `assist` has to be routable, so that a policy
can point it at a fast model rather than at whatever serves `chat`, but it must
never be issuable, because a key for it would buy an external integrator access
to an internal management surface. Every reader must therefore say which
question it is asking. There is deliberately no third name meaning "either",
since that is the one every caller would reach for by default and the
distinction would be gone within a change or two.

`embedding` and `rerank` are the opposite case and are left where they are:
both are issuable and routable, but the gateway mounts only
`/v1/chat/completions`, so neither has an endpoint to reach yet. That is a
missing route rather than a capability that should not be sold, and it closes
with the Phase 2 knowledge base.
"""

from __future__ import annotations

ISSUABLE_CAPABILITIES = frozenset({"chat", "code", "vision", "embedding", "rerank"})
"""What an API key may be issued for, and therefore what the platform offers to
anybody integrating against it.

Read by `ManageApiKeys` at issue and at edit, by the gateway's scope mapping,
and by `ListCapabilities` — which needs it precisely because it derives its
answer from the policies that exist rather than from a constant, so without the
filter a routable-only capability would advertise itself on `GET /v1/models`
the moment somebody wrote a policy for it.
"""

ROUTABLE_CAPABILITIES = ISSUABLE_CAPABILITIES | frozenset({"assist"})
"""What a routing policy may be written for. A superset: everything sold has to
be servable, but not everything servable is sold.

`assist` serves the management assistant (`/admin/assistant`). It is separate
from `chat` so that it can be pointed at a fast, non-deliberating model: the
assistant sits beside a settings form, where a thinking model that spends its
whole budget reasoning is not a slow answer but no answer at all. Measured on
this deployment at 16,384 tokens and 10m53s for zero answer tokens; see
docs/PROGRESS.md, 2026-07-27.
"""
