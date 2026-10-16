"""Embedding failover must retain weights and space, not vector dimensions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.application.use_cases.embed_texts import EmbedTexts, embedding_identity
from app.application.use_cases.search_knowledge import SearchKnowledge
from app.domain.entities.actor import Scope
from app.domain.entities.embedding import current_embedding_manifest
from app.domain.entities.model import ModelState
from app.domain.entities.routing_policy import RoutingCandidate
from app.domain.exceptions import NoAvailableModelError
from app.domain.services.routing_service import RoutingService
from tests.unit.fakes import FakeModels, FakeNodes, FakePolicies, FakeVectorStore
from tests.unit.test_embedding_and_search import EMBEDDER, NODE, PLAIN_USER, POLICY, StubRuntime


class PinAwareRuntime(StubRuntime):
    supports_embedding_manifest_pin = True

    def __init__(self):
        super().__init__()
        self.manifest = "exact"
        self.expected = []

    async def embed(self, ref, texts):
        expected = current_embedding_manifest.get()
        self.expected.append(expected)
        if expected is not None and expected != self.manifest:
            raise NoAvailableModelError(detail="manifest changed before embedding dispatch")
        return await super().embed(ref, texts)


def embedder(models, policy, nodes=(NODE,)):
    runtime = PinAwareRuntime()
    return EmbedTexts(
        policies=FakePolicies([policy]),
        models=FakeModels(models),
        nodes=FakeNodes(nodes),
        runtimes={next(iter(NODE.runtimes)): runtime},
        routing=RoutingService(),
    ), runtime


async def test_failover_selects_same_weights_and_space_on_another_node():
    primary = replace(EMBEDDER, manifest_digest="exact", state=ModelState.DOWNLOADED)
    compatible = replace(primary, alias="replica", id="replica", state=ModelState.LOADED)
    second_node = replace(NODE, id="node-2", name="replica-node")
    compatible = replace(compatible, node_id=second_node.id)
    unrelated = replace(
        primary,
        alias="unrelated",
        id="unrelated",
        ref="another-model",
        manifest_digest="different",
        state=ModelState.LOADED,
    )
    policy = replace(
        POLICY,
        candidates=(
            RoutingCandidate(primary.alias, 3, POLICY.candidates[0].require),
            RoutingCandidate(unrelated.alias, 2, POLICY.candidates[0].require),
            RoutingCandidate(compatible.alias, 1, POLICY.candidates[0].require),
        ),
    )
    use_case, runtime = embedder(
        [primary, compatible, unrelated], policy, nodes=(NODE, second_node)
    )
    chosen, _ = await use_case.resolve(required_identity=embedding_identity(primary))
    assert chosen.alias == "replica"
    search = SearchKnowledge(FakeVectorStore(), use_case, RoleAuthorization())
    await search.execute(
        PLAIN_USER,
        "question",
        scope=Scope.CHAT_USE,
        expected_identity=embedding_identity(primary),
    )
    assert runtime.calls == [["question"]]


async def test_same_dimensions_with_different_weights_is_not_a_failover_candidate():
    pinned = replace(EMBEDDER, manifest_digest="exact")
    unrelated = replace(pinned, manifest_digest="different", ref="another-model")
    use_case, runtime = embedder([unrelated], POLICY)
    with pytest.raises(NoAvailableModelError):
        await use_case.resolve(required_identity=embedding_identity(pinned))
    assert not runtime.calls


def test_mutable_reference_without_manifest_is_unresolved_and_changed_weights_change_identity():
    assert embedding_identity(EMBEDDER) is None
    pinned = replace(EMBEDDER, manifest_digest="exact")
    assert embedding_identity(pinned) != embedding_identity(
        replace(pinned, manifest_digest="changed")
    )


async def test_manifest_is_pinned_for_every_batch_and_context_is_reset_after_failure():
    pinned = replace(EMBEDDER, manifest_digest="exact")
    use_case, runtime = embedder([pinned], POLICY)
    identity = embedding_identity(pinned)
    await use_case.embed_with(runtime, ["text"] * 33, pinned.ref, expected_identity=identity)
    assert runtime.expected == ["exact", "exact"]
    assert current_embedding_manifest.get() is None
    runtime.manifest = "new-same-size-space"
    with pytest.raises(NoAvailableModelError):
        await use_case.embed_with(runtime, ["text"], pinned.ref, expected_identity=identity)
    assert current_embedding_manifest.get() is None
    assert len(runtime.calls) == 2


async def test_query_refuses_if_ref_is_repinned_between_resolve_and_dispatch():
    pinned = replace(EMBEDDER, manifest_digest="exact")
    use_case, runtime = embedder([pinned], POLICY)
    runtime.manifest = "changed-after-gateway-snapshot"
    search = SearchKnowledge(FakeVectorStore(), use_case, RoleAuthorization())
    with pytest.raises(NoAvailableModelError):
        await search.execute(
            PLAIN_USER,
            "question",
            scope=Scope.CHAT_USE,
            expected_identity=embedding_identity(pinned),
        )
    assert not runtime.calls


async def test_indexing_refuses_a_changed_manifest_before_begin_or_vector_publication():
    from tests.unit.manage_knowledge_fixtures import build_ingest, document
    from tests.unit.test_grounding_replay import Epochs

    pinned = replace(EMBEDDER, manifest_digest="exact")
    use_case, runtime = embedder([pinned], POLICY)
    runtime.manifest = "changed-after-gateway-snapshot"
    context = build_ingest(document())
    epochs = Epochs()
    epochs.tenant = replace(epochs.tenant, embedding_identity=embedding_identity(pinned))
    context.use_case._embedder = use_case
    context.use_case._epochs = epochs
    with pytest.raises(NoAvailableModelError):
        await context.use_case._index(document(), "document text", "job")
    assert epochs.tenant.clean and epochs.tenant.epoch == 0
    assert not context.vectors.points and not runtime.calls


@pytest.mark.parametrize("dirty,legacy", [(1, False), (0, True), (2, True)])
async def test_dirty_or_legacy_epochs_do_not_disable_current_search(dirty, legacy):
    from tests.unit.test_grounding_replay import Epochs

    pinned = replace(EMBEDDER, manifest_digest="exact")
    use_case, runtime = embedder([pinned], POLICY)
    epochs = Epochs()
    epochs.tenant = replace(
        epochs.tenant,
        mutations_in_progress=dirty,
        index_requires_rebuild=legacy,
        embedding_identity=embedding_identity(pinned),
    )
    search = SearchKnowledge(FakeVectorStore(), use_case, RoleAuthorization(), epochs)
    await search.execute(PLAIN_USER, "question", scope=Scope.CHAT_USE)
    assert runtime.calls == [["question"]]
    assert runtime.expected == ["exact"]


async def test_unpinned_legacy_index_keeps_pre_upgrade_retrieval():
    from tests.unit.test_grounding_replay import Epochs

    use_case, runtime = embedder([replace(EMBEDDER, manifest_digest="exact")], POLICY)
    epochs = Epochs()
    epochs.tenant = replace(epochs.tenant, index_requires_rebuild=True, embedding_identity=None)
    await SearchKnowledge(FakeVectorStore(), use_case, RoleAuthorization(), epochs).execute(
        PLAIN_USER, "question", scope=Scope.CHAT_USE
    )
    assert runtime.calls == [["question"]]
