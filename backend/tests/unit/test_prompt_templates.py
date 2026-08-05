"""Prompt templates: what they are, and the three ways this could go quietly wrong.

The feature is small. What is not small is that a template is the one message a
model treats as authoritative, so the properties worth pinning are about who
may write one, whose templates a name can reach, and what happens when the
answer is "no such template" — a question that must not be answered by serving
the completion anyway.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.apply_prompt_template import ApplyPromptTemplate
from app.application.use_cases.manage_prompt_templates import ManagePromptTemplates
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.prompt_template import MAX_SYSTEM_PROMPT_CHARS, PromptTemplate
from app.domain.exceptions import (
    ModelStateConflictError,
    NotAuthorizedError,
    PromptTemplateNotFoundError,
)
from app.domain.services.prompt_assembly import apply_template
from app.shared.clock import FixedClock
from tests.unit.fakes import FakeAudit

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

CURATOR = Actor(
    id="c1",
    display="curator",
    role=Role.CURATOR,
    source="local",
    scopes=RoleAuthorization().scopes_for("curator"),
    tenant_id="t1",
)
MEMBER = Actor(
    id="u1",
    display="member",
    role=Role.USER,
    source="local",
    scopes=RoleAuthorization().scopes_for("user"),
    tenant_id="t1",
)


class FakeTemplates:
    """Models the tenant-scoped repository, including that its filter is its
    own rather than the caller's: `tenant_id` is fixed at construction and no
    method takes one, which is the property that makes a caller-supplied name
    safe to resolve."""

    def __init__(self, tenant_id: str = "t1", rows: list[PromptTemplate] | None = None) -> None:
        self.tenant_id = tenant_id
        self.rows: dict[str, PromptTemplate] = {t.id: t for t in rows or []}

    async def get(self, template_id: str) -> PromptTemplate | None:
        row = self.rows.get(template_id)
        return row if row and row.tenant_id == self.tenant_id else None

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        return next(
            (t for t in self.rows.values() if t.name == name and t.tenant_id == self.tenant_id),
            None,
        )

    async def list_all(self) -> list[PromptTemplate]:
        return sorted(
            (t for t in self.rows.values() if t.tenant_id == self.tenant_id),
            key=lambda t: t.name,
        )

    async def save(self, template: PromptTemplate) -> None:
        self.rows[template.id] = template

    async def delete(self, template_id: str) -> None:
        self.rows.pop(template_id, None)


def harness(rows: list[PromptTemplate] | None = None, tenant_id: str = "t1"):
    templates = FakeTemplates(tenant_id, rows)
    audit = FakeAudit()
    use_case = ManagePromptTemplates(
        templates=templates,  # type: ignore[arg-type]
        authz=RoleAuthorization(),
        audit=audit,
        clock=FixedClock(NOW),
        tenant_id=tenant_id,
    )
    return use_case, templates, audit


def template(name: str, tenant_id: str = "t1", prompt: str = "Answer in Welsh.") -> PromptTemplate:
    return PromptTemplate(
        id=f"pt-{name}", tenant_id=tenant_id, name=name, description="", system_prompt=prompt
    )


# --- who may author one --------------------------------------------------


async def test_a_member_may_read_templates_but_not_write_one() -> None:
    """The split the feature rests on: choosing is part of asking a question,
    authoring is authority over what the model is told before it reads one."""
    use_case, _, _ = harness([template("welsh")])

    assert [t.name for t in await use_case.list_all(MEMBER)] == ["welsh"]

    with pytest.raises(NotAuthorizedError):
        await use_case.create(MEMBER, name="mine", description="", system_prompt="Do as I say.")


async def test_a_curator_may_author_one() -> None:
    use_case, templates, audit = harness()

    created = await use_case.create(
        CURATOR, name="reviewer", description="Code review", system_prompt="Be terse."
    )

    assert templates.rows[created.id].system_prompt == "Be terse."
    assert "prompt_template.created" in audit.actions()


async def test_creating_reads_back_the_timestamps_the_database_assigns() -> None:
    """Caught by looking at a live response, not by a test: the first version
    returned the entity as constructed, so `created_at` was null for a row that
    had one. The same mistake `IssueInvitation.create_account` carries a comment
    about — there it took the invitation link down with it."""
    use_case, templates, _ = harness()
    stamped = datetime(2026, 8, 5, 9, 30, tzinfo=UTC)

    real_save = templates.save

    async def save_and_stamp(t: PromptTemplate) -> None:
        # What the server default does: the stored row gains timestamps the
        # in-memory entity never had.
        await real_save(replace(t, created_at=stamped, updated_at=stamped))

    templates.save = save_and_stamp  # type: ignore[method-assign]

    created = await use_case.create(CURATOR, name="x", description="", system_prompt="Be terse.")

    assert created.created_at == stamped


# --- the name is the handle, so it has to mean one thing ------------------


async def test_a_duplicate_name_is_refused_before_the_unique_index() -> None:
    """Caught here so the caller gets a 409 naming the collision rather than a
    constraint violation raised at commit, after the response has been sent."""
    use_case, _, _ = harness([template("welsh")])

    with pytest.raises(ModelStateConflictError):
        await use_case.create(CURATOR, name="welsh", description="", system_prompt="Again.")


async def test_renaming_onto_another_templates_name_is_refused() -> None:
    use_case, _, _ = harness([template("welsh"), template("terse")])

    with pytest.raises(ModelStateConflictError):
        await use_case.update(CURATOR, "pt-terse", name="welsh")


async def test_renaming_a_template_to_its_own_name_is_allowed() -> None:
    """Otherwise editing the body while leaving the name alone is refused by
    the collision check finding the row it is about to write."""
    use_case, templates, _ = harness([template("welsh")])

    await use_case.update(CURATOR, "pt-welsh", name="welsh", system_prompt="Answer in Breton.")

    assert templates.rows["pt-welsh"].system_prompt == "Answer in Breton."


# --- refusing rather than serving something plausible --------------------


async def test_an_empty_system_prompt_is_refused() -> None:
    """Selectable, costs a round trip, does nothing — so the operator concludes
    selection is broken rather than that the template is empty."""
    use_case, _, _ = harness()

    with pytest.raises(ModelStateConflictError):
        await use_case.create(CURATOR, name="empty", description="", system_prompt="   ")


async def test_a_system_prompt_over_the_ceiling_is_refused() -> None:
    use_case, _, _ = harness()

    with pytest.raises(ModelStateConflictError):
        await use_case.create(
            CURATOR, name="huge", description="", system_prompt="x" * (MAX_SYSTEM_PROMPT_CHARS + 1)
        )


async def test_naming_a_template_that_does_not_exist_is_refused_not_ignored() -> None:
    """The failure this platform keeps naming: 200, a plausible answer, and
    nobody told the instructions were never applied."""
    applier = ApplyPromptTemplate(templates=FakeTemplates(), authz=RoleAuthorization())  # type: ignore[arg-type]

    with pytest.raises(PromptTemplateNotFoundError):
        await applier.execute(MEMBER, [Message(role=MessageRole.USER, content="hi")], "absent")


async def test_a_deleted_template_stops_resolving() -> None:
    use_case, templates, _ = harness([template("welsh")])
    applier = ApplyPromptTemplate(templates=templates, authz=RoleAuthorization())  # type: ignore[arg-type]

    await use_case.delete(CURATOR, "pt-welsh")

    with pytest.raises(PromptTemplateNotFoundError):
        await applier.execute(MEMBER, [Message(role=MessageRole.USER, content="hi")], "welsh")


# --- the tenant boundary -------------------------------------------------


async def test_a_name_cannot_reach_another_tenants_template() -> None:
    """The name arrives in the request body, so unscoped this would be a way to
    read somebody else's text by guessing what they called it. The scope is the
    repository's and comes from the wiring, not from the caller."""
    theirs = template("welsh", tenant_id="t2", prompt="Their private instructions.")
    applier = ApplyPromptTemplate(
        templates=FakeTemplates("t1", [theirs]),  # type: ignore[arg-type]
        authz=RoleAuthorization(),
    )

    with pytest.raises(PromptTemplateNotFoundError):
        await applier.execute(MEMBER, [Message(role=MessageRole.USER, content="hi")], "welsh")


# --- where the template lands in the conversation ------------------------


def test_the_template_goes_first_and_the_callers_system_message_survives() -> None:
    """Order encodes who is trusted: the template was written by somebody
    holding `prompt:write` for this tenant, a caller's system message is
    whatever the request body contained. Keeping both matters as much — silently
    dropping part of an accepted request is the failure shape this codebase
    keeps finding."""
    messages = [
        Message(role=MessageRole.SYSTEM, content="caller says"),
        Message(role=MessageRole.USER, content="question"),
    ]

    result = apply_template(messages, "operator says")

    assert [(m.role.value, m.content) for m in result] == [
        ("system", "operator says"),
        ("system", "caller says"),
        ("user", "question"),
    ]


def test_applying_a_template_does_not_mutate_the_caller_list() -> None:
    """`ground` returns a new list for the same reason: the router holds the
    original and reuses it."""
    messages = [Message(role=MessageRole.USER, content="question")]

    apply_template(messages, "operator says")

    assert len(messages) == 1


async def test_applying_requires_chat_use_not_a_management_scope() -> None:
    """A gateway key issued for `chat` must be able to have its question
    answered under its own tenant's template; requiring `prompt:read` would
    mean every API caller needed a management scope."""
    applier = ApplyPromptTemplate(
        templates=FakeTemplates("t1", [template("welsh")]),  # type: ignore[arg-type]
        authz=RoleAuthorization(),
    )
    service = Actor(
        id="k1",
        display="a key",
        role=Role.SERVICE,
        source="api_key",
        scopes=frozenset({Scope.CHAT_USE}),
        tenant_id="t1",
    )

    result = await applier.execute(service, [Message(role=MessageRole.USER, content="hi")], "welsh")

    assert result[0].content == "Answer in Welsh."
