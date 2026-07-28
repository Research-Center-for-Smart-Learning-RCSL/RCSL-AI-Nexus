"""The names a request may ask for.

A capability is what a caller names in the `model` field, and what a routing
policy resolves to a model on a node. Three places have to agree on the set: a
key is issued for capabilities, a policy is written for one, and the gateway
maps one onto the scope that reaches inference.

They live here because they disagreed. The set was defined in
`application/use_cases/manage_api_keys.py` and consulted only there, so
`ManageRoutingPolicies.save` accepted any string at all — a policy for `chatt`
stored and audited cleanly, while no key could ever be issued for it — and the
gateway's capability-to-scope table listed only `chat`, which made a key issued
for any of the other four powerless. One definition in the domain is what stops
a fourth copy appearing the next time a capability is added.
"""

from __future__ import annotations

KNOWN_CAPABILITIES = frozenset({"chat", "code", "vision", "embedding", "rerank"})
