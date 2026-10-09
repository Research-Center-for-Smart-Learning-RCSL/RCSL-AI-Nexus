"""How the agent's relay classifies what the runtime did (design Q5, R5, U2)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from app.node_agent.dispatch import Completed, NotSent, RuntimeRefused, Uncertain
from app.node_agent.relay import OllamaRelay

PAYLOAD = {"model": "qwen2.5:7b", "messages": [{"role": "user", "content": "hi"}], "stream": True}


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def checkpoint(self, observed: dict[str, Any]) -> None:
        self.checkpoints.append(observed)


def _line(content: str = "", *, done: bool = False, **extra: Any) -> bytes:
    event: dict[str, Any] = {"message": {"role": "assistant", "content": content}, "done": done}
    event.update(extra)
    return (json.dumps(event) + "\n").encode()


def _stream(*parts: bytes, then: Exception | None = None) -> AsyncIterator[bytes]:
    async def body() -> AsyncIterator[bytes]:
        for part in parts:
            yield part
        if then is not None:
            raise then

    return body()


def _relay(
    handler: Callable[[httpx.Request], httpx.Response], **kw: Any
) -> tuple[OllamaRelay, list[str]]:
    seen: list[str] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return handler(request)

    relay = OllamaRelay(
        "http://runtime", timeout_s=5, transport=httpx.MockTransport(recording), **kw
    )
    return relay, seen


async def test_done_gives_the_runtimes_raw_totals_not_the_chunk_count() -> None:
    """Review on #24 (U2): two chunks, then `done` reporting eval_count=1. The
    total is the runtime's 1; the chunk count is kept as an observation."""
    relay, _ = _relay(
        lambda r: httpx.Response(
            200,
            content=_stream(
                _line("Hel"),
                _line("lo"),
                _line(done=True, eval_count=1, prompt_eval_count=9, done_reason="stop"),
            ),
        )
    )
    sink = RecordingSink()

    outcome = await relay.chat(PAYLOAD, store_output=True, expected_identity=None)(sink)

    assert isinstance(outcome, Completed)
    assert outcome.terminal["eval_count"] == 1
    assert outcome.terminal["prompt_eval_count"] == 9
    assert outcome.terminal["observed_chunk_count"] == 2
    assert outcome.result is not None and outcome.result["content"] == "Hello"
    assert len(sink.events) == 3


async def test_eof_without_done_is_uncertain() -> None:
    relay, _ = _relay(lambda r: httpx.Response(200, content=_stream(_line("a"), _line("b"))))

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, Uncertain) and outcome.reason == "eof_without_done"
    assert outcome.observed["observed_chunk_count"] == 2


async def test_a_read_error_mid_stream_is_uncertain() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(
            200, content=_stream(_line("a"), then=httpx.ReadError("connection reset"))
        )
    )

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, Uncertain) and outcome.reason == "transport:ReadError"


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow")])
async def test_a_connection_failure_before_sending_is_not_sent(error: Exception) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise error

    relay, _ = _relay(refuse)

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, NotSent)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.WriteError("broken")])
async def test_a_timeout_or_write_failure_is_never_proof_of_no_send(error: Exception) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error

    relay, _ = _relay(fail)

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, Uncertain)


async def test_overflow_then_done_completes_without_a_replay() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(
            200,
            content=_stream(*[_line("x" * 100) for _ in range(5)], _line(done=True, eval_count=5)),
        ),
        replay_cap_bytes=250,
    )

    outcome = await relay.chat(PAYLOAD, store_output=True, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, Completed)
    assert outcome.replay_unavailable and outcome.result is None
    assert outcome.terminal["eval_count"] == 5


async def test_overflow_then_eof_is_still_uncertain() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(200, content=_stream(*[_line("x" * 100) for _ in range(5)])),
        replay_cap_bytes=250,
    )

    outcome = await relay.chat(PAYLOAD, store_output=True, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, Uncertain)


async def test_an_error_status_is_a_runtime_refusal() -> None:
    relay, _ = _relay(lambda r: httpx.Response(400, json={"error": "exceed_context_size_error"}))

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, RuntimeRefused) and outcome.reason == "http_400"
    assert "exceed_context_size_error" in outcome.terminal["error"]


async def test_an_error_line_is_a_runtime_refusal() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(200, content=_stream(_line("a"), b'{"error":"model unloaded"}\n'))
    )

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(RecordingSink())

    assert isinstance(outcome, RuntimeRefused) and outcome.reason == "runtime_error"


async def test_checkpoints_record_observations_while_streaming() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(
            200, content=_stream(_line("a"), _line("b"), _line(done=True, eval_count=2))
        ),
        checkpoint_s=0.0,
    )
    sink = RecordingSink()

    await relay.chat(PAYLOAD, store_output=False, expected_identity=None)(sink)

    assert [c["observed_chunk_count"] for c in sink.checkpoints] == [1, 2]
    assert all("tokens" not in key for c in sink.checkpoints for key in c)


def _tags_then(chat: Callable[[httpx.Request], httpx.Response], digest: str):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b", "digest": digest}]})
        return chat(request)

    return handler


async def test_a_revision_other_than_the_measured_one_is_never_sent() -> None:
    relay, seen = _relay(
        _tags_then(lambda r: httpx.Response(200, content=_stream(_line(done=True))), "bbb")
    )

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity="aaa")(
        RecordingSink()
    )

    assert isinstance(outcome, NotSent) and outcome.reason == "revision_mismatch"
    assert seen == ["GET /api/tags"], "no chat request was made"


async def test_the_measured_revision_is_sent() -> None:
    relay, seen = _relay(
        _tags_then(
            lambda r: httpx.Response(200, content=_stream(_line(done=True, eval_count=0))), "aaa"
        )
    )

    outcome = await relay.chat(PAYLOAD, store_output=False, expected_identity="aaa")(
        RecordingSink()
    )

    assert isinstance(outcome, Completed)
    assert seen == ["GET /api/tags", "POST /api/chat"]


async def test_an_embedding_batch_completes_on_its_response() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(
            200, json={"embeddings": [[0.1, 0.2]], "prompt_eval_count": 3, "total_duration": 9}
        )
    )
    sink = RecordingSink()

    outcome = await relay.embed(
        {"model": "nomic-embed-text", "input": ["a"]}, store_output=False, expected_identity=None
    )(sink)

    assert isinstance(outcome, Completed) and outcome.result is None
    assert outcome.terminal["prompt_eval_count"] == 3
    assert sink.events == [{"type": "embeddings", "data": [[0.1, 0.2]]}]


async def test_an_embedding_without_vectors_is_refused() -> None:
    relay, _ = _relay(lambda r: httpx.Response(200, json={}))

    outcome = await relay.embed(
        {"model": "qwen2.5:7b", "input": ["a"]}, store_output=False, expected_identity=None
    )(RecordingSink())

    assert isinstance(outcome, RuntimeRefused) and outcome.reason == "no_embeddings"


# -- lifecycle (PR4b) ---------------------------------------------------------


async def test_a_load_carries_the_registered_context_and_falls_back_to_embed() -> None:
    """The same requests the direct adapter made: an embedding model refuses
    generate with a 400, and an empty embed moves its weights."""
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(400 if request.url.path == "/api/generate" else 200, json={})

    relay, seen = _relay(handler)
    outcome = await relay.load("nomic-embed-text", keep_alive=-1, context_length=2048)(
        RecordingSink()
    )

    assert seen == ["POST /api/generate", "POST /api/embed"]
    assert bodies[1] == {
        "model": "nomic-embed-text",
        "keep_alive": -1,
        "options": {"num_ctx": 2048},
        "input": [],
    }
    assert isinstance(outcome, Completed) and outcome.terminal["endpoint"] == "embed"


async def test_an_unload_sends_keep_alive_zero_and_sizes_nothing() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={})

    relay, _ = _relay(handler)
    assert isinstance(await relay.unload("qwen2.5:7b")(RecordingSink()), Completed)
    assert bodies == [{"model": "qwen2.5:7b", "keep_alive": 0}]


async def test_a_missing_model_is_a_refusal_named_not_found() -> None:
    relay, _ = _relay(lambda r: httpx.Response(404, json={"error": "not found"}))
    outcome = await relay.unload("nope:1b")(RecordingSink())
    assert isinstance(outcome, RuntimeRefused) and outcome.reason == "not_found"


async def test_a_lifecycle_call_that_never_connected_was_not_sent() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    relay, _ = _relay(refuse)
    assert isinstance(await relay.unload("qwen2.5:7b")(RecordingSink()), NotSent)


async def test_a_pull_reports_progress_and_completes_only_on_success() -> None:
    lines = [{"status": "pulling manifest"}, {"status": "x", "completed": 1, "total": 2}]
    finished = [*lines, {"status": "success"}]
    sink = RecordingSink()

    relay, _ = _relay(
        lambda r: httpx.Response(200, content="".join(json.dumps(x) + "\n" for x in finished))
    )
    done = await relay.pull("qwen2.5:7b")(sink)
    relay, _ = _relay(
        lambda r: httpx.Response(200, content="".join(json.dumps(x) + "\n" for x in lines))
    )
    cut = await relay.pull("qwen2.5:7b")(RecordingSink())

    assert isinstance(done, Completed)
    assert [e["status"] for e in sink.events] == ["pulling manifest", "x", "success"]
    assert sink.events[1] == {"type": "progress", "status": "x", "completed": 1, "total": 2}
    assert isinstance(cut, Uncertain) and cut.reason == "eof_without_success"


async def test_a_pull_error_line_is_a_refusal() -> None:
    relay, _ = _relay(
        lambda r: httpx.Response(200, content=json.dumps({"error": "manifest unknown"}) + "\n")
    )
    outcome = await relay.pull("nope:1b")(RecordingSink())
    assert isinstance(outcome, RuntimeRefused) and outcome.reason == "runtime_error"


async def test_residency_is_none_when_the_runtime_cannot_be_asked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "a:1"}]})
        return httpx.Response(500)

    relay, _ = _relay(handler)
    assert await relay.residency() is None
