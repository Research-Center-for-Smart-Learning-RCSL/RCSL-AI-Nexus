"""The gateway drops the half only for a validated profile (PR2b on #24).

Its view of the runtime's version is the heartbeat's, used only while fresh;
the node agent decides again with the version read live (`test_node_agent_guard`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.node import Node, NodeStatus
from app.domain.exceptions import ContextTooLongError
from app.domain.services import validated_profiles
from app.domain.services.validated_profiles import ValidatedProfile
from tests.unit.streaming_contract_fixtures import FakeCounter, FakeRepo, FakeRuntime, _drain, build

pytest_plugins = ("tests.unit.streaming_contract_fixtures",)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
PROFILE = ValidatedProfile(
    ref="primary:latest",
    node_id="n1",
    runtime="ollama",
    runtime_version="0.33.2",
    manifest="m" * 64,
    encoders=frozenset({"native:e"}),
    renderer="jinja:r",
    tools=False,
    thinking=frozenset({"omitted", "false"}),
    measured_on="2026-10-09",
    cases=(),
)


class MeasuringCounter(FakeCounter):
    def __init__(self, total: int, *, renderer: str | None = "jinja:r") -> None:
        super().__init__(total=total, declared=32768)
        self.renderer = renderer
        self.measured = 0

    async def measure(self, ref, messages, tools) -> Measurement:
        self.measured += 1
        return Measurement(
            identity="m" * 64,
            counted=self._total,
            declared_context=32768,
            encoder="native:e",
            renderer=self.renderer,
        )


def _use_case(counter: FakeCounter, *, observed_ago: timedelta | None = timedelta(minutes=1)):
    use_case, _, _ = build(
        FakeRuntime(chunks=1),
        tokens=counter,
        context_length=32768,
        max_context_tokens=122880,
        ceiling=1024,
    )
    use_case._nodes = FakeRepo(  # noqa: SLF001 - the heartbeat's stamp, which build() omits
        [
            Node(
                id="n1",
                name="n1",
                address="100.64.0.1",
                status=NodeStatus.ONLINE,
                total_memory_gb=64.0,
                runtime_version="0.33.2" if observed_ago is not None else None,
                runtime_version_at=NOW - observed_ago if observed_ago is not None else None,
            )
        ]
    )
    return use_case


MESSAGE = [Message(role=MessageRole.USER, content="x")]


@pytest.fixture(autouse=True)
def _catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validated_profiles, "VALIDATED", (PROFILE,))


async def test_a_validated_profile_is_admitted_past_the_half() -> None:
    """32768 − 1 − 1024 = 31743 rather than 16384."""
    counter = MeasuringCounter(total=31743)

    await _drain(_use_case(counter), MESSAGE, thinking=False)

    assert counter.measured == 1


async def test_the_output_bound_still_holds_when_widened() -> None:
    with pytest.raises(ContextTooLongError) as caught:
        await _drain(_use_case(MeasuringCounter(total=31744)), MESSAGE, thinking=False)
    assert caught.value.limit == 31743


async def test_an_ordinary_request_never_asks_for_the_fingerprint() -> None:
    counter = MeasuringCounter(total=1000)

    await _drain(_use_case(counter), MESSAGE, thinking=False)

    assert counter.measured == 0


@pytest.mark.parametrize(
    ("counter", "observed_ago"),
    [
        (MeasuringCounter(total=20000), timedelta(minutes=10)),  # stale version
        (MeasuringCounter(total=20000), None),  # never observed
        (MeasuringCounter(total=20000, renderer=None), timedelta(minutes=1)),  # ChatML guess
        (FakeCounter(total=20000, declared=32768), timedelta(minutes=1)),  # cannot measure
    ],
)
async def test_anything_short_of_the_whole_fingerprint_keeps_the_half(
    counter: FakeCounter, observed_ago: timedelta | None
) -> None:
    with pytest.raises(ContextTooLongError) as caught:
        await _drain(_use_case(counter, observed_ago=observed_ago), MESSAGE, thinking=False)
    assert caught.value.limit == 16384


def test_a_widened_request_past_the_half_is_not_called_truncated(caplog) -> None:
    """Seen in production on the first widened request: 20045 evaluated of
    20045 counted was reported as reaching num_ctx/2."""
    from app.application.use_cases.route_chat_request.diagnostics import (
        _warn_if_prompt_was_truncated,
    )

    def warned(prompt_tokens: int, *, widened: bool) -> bool:
        caplog.clear()
        _warn_if_prompt_was_truncated(
            prompt_tokens,
            32768,
            estimated=20045,
            basis="tokenizer",
            request_id="r",
            actor="a",
            widened=widened,
        )
        return any("likely truncated" in r.message for r in caplog.records)

    assert not warned(20045, widened=True)
    assert warned(16384, widened=True), "a cut evaluation is still reported"
    assert warned(20045, widened=False), "unchanged where the half applies"
