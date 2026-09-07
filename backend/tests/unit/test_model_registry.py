from __future__ import annotations

from dataclasses import replace

import pytest

from app.domain.entities.actor import Scope
from app.domain.entities.model import ModelState, RuntimeKind
from app.domain.entities.routing_policy import RoutingCandidate, RoutingPolicy
from app.domain.exceptions import (
    InvalidModelReferenceError,
    ModelStateConflictError,
    NodeNotFoundError,
    NotAuthorizedError,
    RuntimeUnavailableError,
)
from tests.unit.fakes import (
    FakeRuntime,
)
from tests.unit.manage_models_fixtures import (
    ADMIN,
    NODE,
    PROFILE,
    READER,
    DeclaringCounter,
    Harness,
    make_model,
)

pytest_plugins = ("tests.unit.manage_models_fixtures",)


async def test_a_new_model_starts_undownloaded() -> None:
    """Registration records intent. Whether the weights are present is
    discovered by downloading, not asserted by whoever filled the form."""
    harness = Harness()
    model = await harness.register()

    assert model.state is ModelState.NOT_DOWNLOADED


async def test_a_reader_cannot_register() -> None:
    harness = Harness()
    with pytest.raises(NotAuthorizedError):
        await harness.use_case.register(
            READER,
            alias="x",
            ref="library/x:1",
            runtime=RuntimeKind.OLLAMA,
            node_id=NODE.id,
            capabilities=frozenset({"chat"}),
            resource_profile=PROFILE,
        )


async def test_the_reference_is_validated_by_the_runtime_that_will_use_it() -> None:
    """What counts as a reference differs by runtime, so the check belongs on
    the port rather than in a shared helper that would have to be the union of
    every runtime's grammar."""
    harness = Harness(runtime=FakeRuntime(invalid_refs=frozenset({"; rm -rf /"})))

    with pytest.raises(InvalidModelReferenceError):
        await harness.register(ref="; rm -rf /")


async def test_registering_against_an_unknown_node_is_refused() -> None:
    harness = Harness()
    with pytest.raises(NodeNotFoundError):
        await harness.register(node_id="node-missing")


async def test_registering_against_a_runtime_with_no_adapter_is_refused() -> None:
    """A row bound to a runtime nothing implements can never be downloaded or
    loaded, and the failure would otherwise appear much later as a KeyError."""
    harness = Harness()
    with pytest.raises(RuntimeUnavailableError):
        await harness.register(runtime=RuntimeKind.VLLM)


async def test_a_duplicate_alias_is_refused() -> None:
    harness = Harness()
    await harness.register()

    with pytest.raises(ModelStateConflictError):
        await harness.register(ref="library/other:1")


async def test_a_downloaded_model_cannot_be_repointed() -> None:
    """`ref`, `runtime` and `node_id` name what is on disk. Changing them
    under a downloaded model makes the registry describe something that is not
    there."""
    harness = Harness([make_model()])

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.update(ADMIN, "m1", ref="library/something-else:1")


async def test_capabilities_can_still_be_edited_on_a_downloaded_model() -> None:
    """The restriction is about what is on disk, not about the row generally."""
    harness = Harness([make_model()])

    updated = await harness.use_case.update(ADMIN, "m1", capabilities=frozenset({"chat", "code"}))

    assert updated.capabilities == frozenset({"chat", "code"})


async def test_renaming_a_model_a_policy_binds_to_is_refused() -> None:
    """Policies bind to the alias, so a rename silently detaches every policy
    pointing at it. Refused rather than cascaded: rewriting policies is not
    what someone editing a form is asking for."""
    harness = Harness(
        [make_model(state=ModelState.NOT_DOWNLOADED)],
        [RoutingPolicy(capability="chat", candidates=(RoutingCandidate("chat-main", 1),))],
    )

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.update(ADMIN, "m1", alias="chat-new")


async def test_a_loaded_model_cannot_be_deleted() -> None:
    harness = Harness([make_model(state=ModelState.LOADED)])

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.delete(ADMIN, "m1")


async def test_deleting_a_model_a_policy_names_is_refused() -> None:
    """No foreign key enforces this: the binding is a string. Without the
    check, inference starts answering "no available model" with nothing in the
    registry to explain why."""
    harness = Harness(
        [make_model()],
        [RoutingPolicy(capability="chat", candidates=(RoutingCandidate("chat-main", 1),))],
    )

    with pytest.raises(ModelStateConflictError):
        await harness.use_case.delete(ADMIN, "m1")


async def test_an_unreferenced_model_deletes() -> None:
    harness = Harness([make_model()])

    await harness.use_case.delete(ADMIN, "m1")

    assert harness.models.rows == {}
    assert "model.deleted" in harness.audit.actions()


async def test_the_declared_context_comes_from_the_model_not_the_operator() -> None:
    """What replaced the register form's 8192.

    That value has a history: it is what `qwen7b` was registered with, which
    put `_refuse_what_this_target_would_truncate` at 4096 and served `assist`
    from a truncated prompt for as long as nobody noticed. A default that looks
    plausible and is wrong is worse than none, because the form submits and the
    consequence arrives later and quietly.
    """
    harness = Harness([], tokens=DeclaringCounter(declared=262144))

    assert await harness.use_case.declared_context_length(ADMIN, "gemma4:31b-it-q8_0") == 262144


async def test_a_reference_this_host_cannot_read_offers_nothing() -> None:
    """`None` is cannot-say, as everywhere on `TokenCounterPort`: not pulled, a
    different runtime, a missing mount. The form then suggests nothing, which
    is the whole point — a guess is what it is replacing."""
    harness = Harness([], tokens=DeclaringCounter(declared=None))

    assert await harness.use_case.declared_context_length(ADMIN, "absent:latest") is None


async def test_a_build_with_no_counter_offers_nothing() -> None:
    """Every deployment that holds no GGUF to read."""
    harness = Harness([])

    assert await harness.use_case.declared_context_length(ADMIN, "anything:latest") is None


async def test_reading_a_reference_needs_model_write() -> None:
    """`MODEL_WRITE`, not `MODEL_READ`. It answers "does this host hold weights
    under that name", which is a fact about the inventory, and a reader who
    cannot register a model has nothing to do with the answer."""
    harness = Harness([], tokens=DeclaringCounter(declared=8192))
    reader = replace(ADMIN, scopes=frozenset({Scope.MODEL_READ}))

    with pytest.raises(NotAuthorizedError):
        await harness.use_case.declared_context_length(reader, "gemma4:31b-it-q8_0")
