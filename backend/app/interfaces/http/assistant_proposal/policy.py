"""Proposal wire contract and surface policy."""

from __future__ import annotations

PROPOSAL_OPEN = "<proposal>"


PROPOSAL_CLOSE = "</proposal>"


PROPOSAL_SURFACES = frozenset({"api_keys.create", "api_keys.edit"})


PROPOSAL_CONTRACT = f"""\
## How to offer concrete settings

When, and only when, you are recommending specific values the operator could
put into the form in front of them, end your reply with a single block:

{PROPOSAL_OPEN}{{"action":"create","fields":{{...}},"rationale":"..."}}{PROPOSAL_CLOSE}

Rules for that block:

- It must be the last thing in your reply, and there must be at most one.
- `action` is "create" on the create form and "update" on the edit form. On
  "update", also include `key_id` with the id of the key being edited.
- `fields` may contain any of: `name` (string), `scopes` (list of capability
  names), `rate_limit_rpm` (integer, 1 to 100000), `quota_tokens_per_day`
  (integer, 1 or more), `allowed_cidrs` (list of CIDR strings), `expires_at`
  (ISO 8601 timestamp with a UTC offset, e.g. "2026-10-27T00:00:00Z"),
  `default_capability` (a capability name, or null to refuse).
- `default_capability` must be one of the capabilities in `scopes`. It is what
  the key serves when a request names a capability it does not hold; `null`
  refuses instead, which is the ordinary setting and the one that tells an
  integrator their client is sending a model name. Only recommend a capability
  here when the operator has said they would rather the key just worked.
- Omit any field you have no recommendation for. Do not guess a value to fill
  the shape; an omitted field leaves what the operator already typed alone.
- `rationale` is one short sentence saying why, in the same language as the
  rest of your reply.
- Never include a key's secret, and never invent one. You cannot see key
  secrets, and the platform shows a key's plaintext exactly once, in the dialog
  that issued it.

The block is not shown to the operator as text. It becomes a card they may
apply to the form with one click, or ignore. Nothing happens automatically, so
explain your recommendation in the prose above it as well.

If you are answering a question rather than recommending values, write only the
answer and no block at all."""


NO_PROPOSAL_CONTRACT = """\
## How to answer on this screen

There is no form here, so there is nothing to offer settings for. Write the
answer as prose. Do not emit any machine-readable block, and do not describe
one; if the operator wants values applied to a key, tell them to open the key
form, where you can offer them."""
