"""A named system prompt an operator writes once and a caller selects by name.

**There is no substitution, and that is the design rather than a missing
feature.** "Prompt template" almost always means a body with `{{slots}}` filled
in per request, and that is precisely what this platform's prompt rules forbid.
`domain/services/prompt_assembly.py` exists because retrieved passages can
contain "ignore previous instructions", and security.md §7.4 states the rule it
implements: *values are serialised into a slot, never formatted into the
template body*. A substitution mechanism whose values come from the caller is
the same hazard wearing a friendlier name — the caller would be writing into
the one message the model treats as authoritative, which is a privilege escalation
from "asks questions" to "gives instructions", and no escaping makes text stop
meaning what it says to a language model.

So a template is text an operator wrote, chosen by name, inserted whole. The
caller's own words stay where they have always been, in the user message. What
a caller controls is *which* template, out of the set their tenant's operator
authored — a choice among trusted values rather than a value of their own.

If per-request values are ever genuinely needed, the shape already exists and
should be reused rather than invented: `build_context_message` puts untrusted
text in its own message, fenced with a per-request nonce, with the instruction
naming it as data placed *after* it. That is a second message, not a hole in
this one.

Tenant-scoped, like the knowledge base and for the same reason: a template is
content a team wrote, it can encode how they work, and one tenant's must not be
readable or selectable by another's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MAX_SYSTEM_PROMPT_CHARS = 8000
"""A bound on what one template can spend of the context window.

Not a security control — the author is trusted, holding `prompt:write`. It is a
resource guardrail of the same family as the ones in security.md §4.3: the
context ceiling is 65536 tokens and shared with the conversation, tool
definitions and any retrieved passages, so a template large enough to crowd
those out would turn "select a template" into "the request no longer fits", far
from where the choice was made.
"""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    id: str
    tenant_id: str
    name: str
    """Chosen by the operator and used by callers to select it. Unique within a
    tenant, which is what makes `"prompt_template": "code-review"` mean one
    thing."""

    description: str
    """For the person picking one in the UI. Never sent to a model — it
    describes the template rather than instructing with it."""

    system_prompt: str
    """Inserted verbatim as a system message, ahead of the conversation."""

    created_at: datetime | None = None
    updated_at: datetime | None = None
