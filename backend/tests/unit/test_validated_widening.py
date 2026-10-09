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
from app.domain.services.validated_profiles import ValidatedProfile, WidenedAdmission
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


def _warned(caplog, prompt_tokens: int, widened, *, estimated: int = 20045) -> list[str]:
    from app.application.use_cases.route_chat_request.diagnostics import (
        _warn_if_prompt_was_truncated,
    )

    caplog.clear()
    _warn_if_prompt_was_truncated(
        prompt_tokens,
        32768,
        estimated=estimated,
        basis="tokenizer",
        request_id="r",
        actor="a",
        widened=widened,
    )
    return [r.message for r in caplog.records if r.levelname == "WARNING"]


ADMITTED = WidenedAdmission(profile="qwen2.5:7b", counted=20045, limit=32751)


def test_a_widened_request_past_the_half_is_not_called_truncated(caplog) -> None:
    """Seen in production on the first widened request: 20045 evaluated of
    20045 counted was reported as reaching num_ctx/2."""
    assert _warned(caplog, 20045, ADMITTED) == []
    assert _warned(caplog, 20045, None), "unchanged where the half applies"


def test_a_cut_just_past_the_half_is_caught(caplog) -> None:
    """Review of #43: a 17000-token request cut to 16384 is 96% of its count,
    which a ratio of 0.95 let through."""
    admitted = WidenedAdmission(profile="qwen2.5:7b", counted=17000, limit=32751)

    warnings = _warned(caplog, 16384, admitted, estimated=17000)

    assert len(warnings) == 1 and "truncated" in warnings[0]
    assert "qwen2.5:7b" in warnings[0], "the profile to withdraw is named"


def test_the_runtime_reading_more_than_was_counted_is_reported(caplog) -> None:
    """The direction that breaks the output reserve, silent before."""
    warnings = _warned(caplog, 21000, ADMITTED)

    assert len(warnings) == 1 and "under-counted" in warnings[0] and "qwen2.5:7b" in warnings[0]


def test_the_count_judged_is_the_one_admitted_not_the_gateways_alone(caplog) -> None:
    """Admission compares the larger of the gateway's count and the profile's
    own measure; the backstop must judge against that same figure."""
    admitted = WidenedAdmission(profile="qwen2.5:7b", counted=18000, limit=32751)

    assert _warned(caplog, 16384, admitted, estimated=17000)


async def test_the_guard_hands_on_what_it_judged() -> None:
    use_case = _use_case(MeasuringCounter(total=20000))
    from app.domain.entities.actor import Actor, Role, Scope

    actor = Actor(id="a", display="a", role=Role.ADMIN, source="dev", scopes=frozenset(Scope))
    model = (await use_case._models.list_all())[0]  # noqa: SLF001
    node = (await use_case._nodes.list_all())[0]  # noqa: SLF001
    admitted = await use_case._refuse_what_this_target_would_truncate(  # noqa: SLF001
        20000, "tokenizer", model, actor, MESSAGE, (), 1024, node=node, thinking=False
    )

    assert admitted == WidenedAdmission(profile="primary:latest", counted=20000, limit=31743)
