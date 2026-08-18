"""Embedding through the routing policy, and retrieval over the index.

The point of routing embeddings rather than configuring them is that there is
one mechanism for naming a model. These pin that it really is the same one, and
that the two failure modes which would corrupt a knowledge base silently
(a runtime that cannot embed, and a batch answered with the wrong count) are
refusals rather than approximations.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.runtime.mlx_adapter import MlxAdapter
from app.adapters.runtime.ollama_adapter import OllamaAdapter
from app.application.use_cases.embed_texts import EmbedTexts
from app.application.use_cases.search_knowledge import MAX_TOP_K, SearchKnowledge
from app.domain.entities.actor import Actor, Role, Scope
from app.domain.entities.knowledge import RetrievedPassage
from app.domain.entities.model import Model, ModelState, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.exceptions import (
    NoAvailableModelError,
    NotAuthorizedError,
    RuntimeCapabilityError,
    VectorStoreError,
)
from app.domain.services.routing_service import RoutingService
from tests.unit.fakes import FakeEmbedder, FakeModels, FakeNodes, FakePolicies, FakeVectorStore

TENANT = "11111111-1111-1111-1111-111111111111"
ADMIN = Actor(
    id="a1",
    display="admin",
    role=Role.ADMIN,
    source="tailnet",
    scopes=frozenset(Scope),
    tenant_id=TENANT,
)
PLAIN_USER = Actor(
    id="u2",
    display="user",
    role=Role.USER,
    source="local",
    scopes=frozenset({Scope.CHAT_USE}),
    tenant_id=TENANT,
)

NODE = Node(
    id="node-1",
    name="studio",
    address="100.64.0.1",
    status=NodeStatus.ONLINE,
    total_memory_gb=64.0,
    runtimes=frozenset({RuntimeKind.OLLAMA}),
)
EMBEDDER = Model(
    id="m-embed",
    alias="embedder",
    ref="nomic-embed-text",
    runtime=RuntimeKind.OLLAMA,
    node_id="node-1",
    state=ModelState.LOADED,
    capabilities=frozenset({"embedding"}),
)
POLICY = RoutingPolicy(
    capability="embedding",
    candidates=(
        RoutingCandidate(
            model_alias="embedder",
            priority=1,
            require=Requirement(model_state=frozenset({ModelState.LOADED})),
        ),
    ),
)


class StubRuntime:
    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._vectors = vectors

    async def embed(self, ref: str, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._vectors is not None:
            return self._vectors
        return [[float(len(t))] for t in texts]


def build_embedder(
    *, policies=(POLICY,), runtime: StubRuntime | None = None
) -> tuple[EmbedTexts, StubRuntime]:
    stub = runtime or StubRuntime()
    return (
        EmbedTexts(
            policies=FakePolicies(policies),
            models=FakeModels((EMBEDDER,)),
            nodes=FakeNodes((NODE,)),
            runtimes={RuntimeKind.OLLAMA: stub},  # type: ignore[dict-item]
            routing=RoutingService(),
        ),
        stub,
    )


# --- resolution through the routing policy -------------------------------


async def test_the_embedding_model_comes_from_the_routing_policy() -> None:
    """Not a setting of its own: one registry and one memory budget, so a second
    mechanism cannot disagree with the first about which model is loaded."""
    embedder, _ = build_embedder()
    target, _ = await embedder.resolve()
    assert target.alias == "embedder"


async def test_no_embedding_policy_is_a_named_failure_not_a_default() -> None:
    embedder, _ = build_embedder(policies=())
    with pytest.raises(NoAvailableModelError, match="embedding"):
        await embedder.resolve()


async def test_texts_are_embedded_in_batches() -> None:
    embedder, stub = build_embedder()
    vectors = await embedder.embed([f"passage {i}" for i in range(70)])

    assert len(vectors) == 70
    # 70 texts at a batch of 32: three calls, not seventy round trips and not
    # one payload whose size is set by how large a document someone uploaded.
    assert [len(batch) for batch in stub.calls] == [32, 32, 6]


async def test_a_runtime_returning_the_wrong_number_of_vectors_is_refused() -> None:
    """A silent mismatch pairs passages with the wrong vectors, which is a
    knowledge base that retrieves confidently and wrongly."""
    embedder, _ = build_embedder(runtime=StubRuntime(vectors=[[0.1]]))
    with pytest.raises(NoAvailableModelError, match="vectors"):
        await embedder.embed(["one", "two", "three"])


async def test_embedding_nothing_makes_no_call() -> None:
    embedder, stub = build_embedder()
    assert await embedder.embed([]) == []
    assert stub.calls == []


# --- the adapters --------------------------------------------------------


async def test_ollama_embeds_a_batch_through_the_batching_endpoint(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def post(self: object, path: str, **kwargs: object) -> httpx.Response:
        seen["path"] = path
        seen["json"] = kwargs.get("json")
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    vectors = await OllamaAdapter("http://host:11434").embed("nomic-embed-text", ["a", "b"])

    assert seen["path"] == "/api/embed"
    assert seen["json"] == {
        "model": "nomic-embed-text",
        "input": ["a", "b"],
        "keep_alive": -1,
    }
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_ollama_embedding_does_not_hand_residency_back_to_the_server_default(
    monkeypatch,
) -> None:
    """Omitting `keep_alive` lets Ollama's five-minute timer overrule `load`.

    On the generate path that costs a reload. Here it costs the capability:
    routing requires a `loaded` observation, and nothing on the embedding path
    loads on demand, so the eviction is permanent until somebody warms the
    model by hand.
    """
    seen: dict[str, object] = {}

    async def post(self: object, path: str, **kwargs: object) -> httpx.Response:
        seen["json"] = kwargs.get("json")
        return httpx.Response(200, json={"embeddings": [[0.1]]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await OllamaAdapter("http://host:11434", keep_alive="30m").embed("nomic-embed-text", ["a"])

    assert seen["json"]["keep_alive"] == "30m"  # type: ignore[index]


async def test_ollama_refuses_a_model_that_answers_without_embeddings(monkeypatch) -> None:
    """A chat model answers 200 with no `embeddings` key. Refusing is what stops
    that becoming a knowledge base indexed with nothing."""

    async def post(self: object, path: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"model": "llama3"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(NoAvailableModelError):
        await OllamaAdapter("http://host:11434").embed("llama3", ["a"])


async def test_mlx_refuses_to_embed_rather_than_approximating() -> None:
    """The same judgement its `unload` makes: a plausible value from the wrong
    source would not fail, it would poison the index."""
    with pytest.raises(RuntimeCapabilityError):
        await MlxAdapter("http://host:8080").embed("mlx-community/Model-4bit", ["a"])


# --- search --------------------------------------------------------------


def build_search(
    *, results: list[RetrievedPassage] | None = None, embedder: FakeEmbedder | None = None
) -> tuple[SearchKnowledge, FakeVectorStore]:
    vectors = FakeVectorStore()
    vectors.results = results or []
    return (
        SearchKnowledge(
            vectors=vectors,
            embedder=embedder or FakeEmbedder(),
            authz=RoleAuthorization(),
        ),
        vectors,
    )


async def test_a_plain_user_cannot_search_under_the_knowledge_read_scope() -> None:
    search, _ = build_search()
    with pytest.raises(NotAuthorizedError):
        await search.execute(PLAIN_USER, "anything")


async def test_a_plain_user_can_search_under_the_chat_scope() -> None:
    """The chat path retrieves on behalf of whoever is asking. A `user` may
    never list documents and should still have their question answered from
    them, which is why the scope is a parameter."""
    search, _ = build_search()
    await search.execute(PLAIN_USER, "a question", scope=Scope.CHAT_USE)


async def test_top_k_is_clamped() -> None:
    """Each passage becomes prompt context, so an unbounded top_k is a way to
    turn one small question into a large generation."""
    search, vectors = build_search()
    await search.execute(ADMIN, "q", top_k=10_000)
    assert vectors.searches[0][0] == MAX_TOP_K

    await search.execute(ADMIN, "q", top_k=0)
    assert vectors.searches[1][0] == 1


async def test_an_empty_query_searches_nothing() -> None:
    search, vectors = build_search()
    assert await search.execute(ADMIN, "   ") == []
    assert vectors.searches == []


async def test_the_collection_filter_is_passed_through() -> None:
    search, vectors = build_search()
    await search.execute(ADMIN, "q", collection_id="col-1")
    assert vectors.searches[0][1] == "col-1"


async def test_retrieval_for_chat_degrades_instead_of_failing() -> None:
    """A knowledge base with no embedding policy, or a Qdrant that is down, must
    not turn an ordinary chat into a 503."""
    for failure in (
        VectorStoreError(detail="qdrant down"),
        NoAvailableModelError(detail="no embedding policy"),
    ):
        search, _ = build_search(embedder=FakeEmbedder(raises=failure))
        assert await search.execute_or_empty(ADMIN, "q") == []


async def test_degrading_never_swallows_an_authorization_failure() -> None:
    """That is a decision about who may ask, not an availability problem."""
    search, _ = build_search()
    with pytest.raises(NotAuthorizedError):
        await search.execute_or_empty(PLAIN_USER, "q")
