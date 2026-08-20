"""Actor scope definitions."""

from __future__ import annotations

from enum import StrEnum


class Scope(StrEnum):
    """A single permission. Use cases declare the scope they require."""

    CHAT_USE = "chat:use"

    MODEL_READ = "model:read"
    MODEL_WRITE = "model:write"

    ROUTING_READ = "routing:read"
    ROUTING_WRITE = "routing:write"

    API_KEY_READ_OWN = "api_key:read_own"
    API_KEY_WRITE_OWN = "api_key:write_own"
    API_KEY_WRITE_ANY = "api_key:write_any"

    USER_READ = "user:read"
    USER_WRITE = "user:write"

    NODE_READ = "node:read"
    NODE_WRITE = "node:write"

    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"

    USAGE_READ_OWN = "usage:read_own"
    USAGE_READ_ALL = "usage:read_all"

    LOGS_READ = "logs:read"

    REFUSAL_READ_OWN = "refusal:read_own"
    """Read the refusals this account and its keys provoked.

    In the base scopes, because being able to see why you were refused is the
    whole of the feature: on 2026-08-17 two people spent an evening each on
    refusals that were correct and silent about which of several things they
    had just changed had caused them, and neither had anywhere to look.

    It discloses nothing new. Every row is a second copy of a response the
    holder already received — the code, the status, the message, and the
    figures that came with it — which is why it sits beside `usage:read_own`
    rather than behind an administrator.
    """

    REFUSAL_READ_ALL = "refusal:read_all"
    """Read anyone's, which is what made that evening's diagnosis possible.

    Granted like `usage:read_all` and for a closely related reason: both are
    metadata about requests rather than their content, and the roles that
    investigate load are the roles that investigate refusals. It is deliberately
    *not* in `ADMIN_ONLY_SCOPES` beside `prompt_log:read` — that one reads what
    somebody typed, and this one reads only what the platform told them.

    What it does disclose is shape, and that is worth naming rather than
    waving past: a `composition` says a conversation was 97% one message, and a
    month of 413s says how somebody works. That is the reason it is a scope at
    all instead of following `logs:read`, and the reason the retention bound on
    this dataset is a ceiling.
    """

    PROMPT_LOG_READ = "prompt_log:read"
    """Read the full prompt and completion text captured while a debug window
    was open (§9.2).

    Separate from `logs:read`, and held by strictly fewer roles, because the
    two read different things about the same event. `logs:read` sees that a
    request happened, from whom, against which model, and whether it was
    refused — the metadata column of §9.2's table. This sees what was actually
    typed, which on this deployment is unpublished research.

    Admin-only, and named as such in `ADMIN_ONLY_SCOPES` with the argument.
    Withheld from `tenant_admin` in particular: that role holds every other
    authority inside its tenant, so the exclusion reads as an oversight until
    the reason is stated — administering a tenant's people and keys does not
    require reading their conversations, and the tenant boundary that confines
    the role offers its members no protection from the person administering
    them.
    """

    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"

    PROMPT_READ = "prompt:read"
    """List the tenant's prompt templates and see what each contains.

    In the base scopes, unlike `knowledge:read`, because selecting a template
    is an ordinary part of asking a question: a member who may use the chat has
    to be able to see which templates exist in order to choose one. What they
    see is text their own tenant's operator wrote.
    """

    PROMPT_WRITE = "prompt:write"
    """Author a template, which is authority over what a model is told before
    it reads anybody's question — so it is content authorship, not fleet
    operation, and it goes to the roles that already hold the knowledge base
    rather than to the one that runs the nodes."""

    RETENTION_WRITE = "retention:write"
    """Set how long records are kept, and delete them ahead of that.

    One scope for reading the policy and for acting on it, because there is no
    audience for the first without the second: the number is only interesting
    to whoever can change it. Admin-only, and the reason is the same one that
    makes `tenant:write` admin-only — it has no smaller sensible holder. A
    tenant administrator who could purge would be able to remove the record of
    what they did inside their own tenant, which is the one boundary the audit
    log exists to see across."""
