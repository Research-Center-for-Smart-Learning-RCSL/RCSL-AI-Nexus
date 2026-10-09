"""The agent's own admission check (final spec §1, PR2a contract, design S5)."""

from __future__ import annotations

from dataclasses import replace

from app.adapters.tokenizer.gguf_token_counter.adapter import Measurement
from app.domain.entities.chat import Message, MessageRole
from app.domain.services.validated_profiles import ValidatedProfile
from app.node_agent.guard import GuardPass, GuardRefusal, Registration, check_generation
from app.node_agent.wire import GenerationRequest

REQUEST = GenerationRequest(
    ref="qwen2.5:7b",
    messages=(Message(role=MessageRole.USER, content="hello"),),
    max_tokens=1024,
    thinking=True,
    tools=(),
    tool_choice=None,
    sampling=None,
    context_length=32768,
)
REGISTERED = Registration(context_length=32768, manifest_digest=None, capabilities=("chat",))


def _measured(counted: int | None = 100, declared: int | None = 32768) -> Measurement:
    return Measurement(identity="aaa", counted=counted, declared_context=declared)


def test_a_prompt_within_both_bounds_passes_with_its_provenance() -> None:
    result = check_generation(REQUEST, REGISTERED, _measured())

    assert isinstance(result, GuardPass)
    assert result.provenance["servable"] == 16384
    assert result.provenance["basis"] == "exact_counter"
    assert result.provenance["manifest"] == "aaa"


def test_the_output_reserve_is_the_tighter_bound_when_it_is() -> None:
    """window 32768, output 20000: min(16384, 12767) = 12767 (PR2a)."""
    request = replace(REQUEST, max_tokens=20000)

    assert isinstance(check_generation(request, REGISTERED, _measured(counted=12767)), GuardPass)
    refused = check_generation(request, REGISTERED, _measured(counted=12768))
    assert isinstance(refused, GuardRefusal) and refused.reason == "context_exceeded"


def test_smaller_declared_weights_bound_the_window() -> None:
    refused = check_generation(REQUEST, REGISTERED, _measured(counted=3000, declared=4096))

    assert isinstance(refused, GuardRefusal) and refused.reason == "context_exceeded"
    assert "4096-token window" in refused.detail


def test_without_an_exact_count_the_estimate_decides() -> None:
    result = check_generation(REQUEST, REGISTERED, _measured(counted=None))

    assert isinstance(result, GuardPass) and result.provenance["basis"] == "estimate"


def test_a_model_not_registered_on_this_node_is_refused() -> None:
    refused = check_generation(REQUEST, None, _measured())

    assert isinstance(refused, GuardRefusal) and refused.reason == "model_not_on_node"


def test_a_context_other_than_the_registration_is_refused() -> None:
    refused = check_generation(replace(REQUEST, context_length=8192), REGISTERED, _measured())

    assert isinstance(refused, GuardRefusal) and refused.reason == "context_length_mismatch"


def test_a_pinned_model_must_be_the_measured_revision() -> None:
    pinned = replace(REGISTERED, manifest_digest="bbb")

    refused = check_generation(REQUEST, pinned, _measured())

    assert isinstance(refused, GuardRefusal) and refused.reason == "revision_mismatch"
    assert isinstance(
        check_generation(REQUEST, replace(REGISTERED, manifest_digest="aaa"), _measured()),
        GuardPass,
    )


# -- PR2b: a validated profile drops the half -------------------------------

PROFILE = ValidatedProfile(
    ref="qwen2.5:7b",
    node_id="local",
    runtime="ollama",
    runtime_version="0.33.2",
    manifest="aaa",
    encoders=frozenset({"native:e"}),
    renderer="jinja:r",
    tools=False,
    thinking=frozenset({"omitted", "false"}),
    measured_on="2026-10-09",
    cases=(),
)


def _fingerprinted(counted: int) -> Measurement:
    return Measurement(
        identity="aaa",
        counted=counted,
        declared_context=32768,
        encoder="native:e",
        renderer="jinja:r",
    )


def test_a_validated_profile_admits_up_to_the_window_less_the_output() -> None:
    """32768 − 1 − 1024 = 31743, where the half would have refused at 16384."""
    passed = check_generation(
        REQUEST,
        REGISTERED,
        _fingerprinted(31743),
        node_id="local",
        runtime_version="0.33.2",
        profiles=(PROFILE,),
    )
    refused = check_generation(
        REQUEST,
        REGISTERED,
        _fingerprinted(31744),
        node_id="local",
        runtime_version="0.33.2",
        profiles=(PROFILE,),
    )

    assert isinstance(passed, GuardPass)
    assert passed.provenance["validated_profile"] == "qwen2.5:7b"
    assert passed.provenance["servable"] == 31743
    assert isinstance(refused, GuardRefusal)


def test_without_the_live_version_or_on_another_node_the_half_stays() -> None:
    for node_id, version in (("local", None), ("b", "0.33.2"), ("local", "0.40.2")):
        result = check_generation(
            REQUEST,
            REGISTERED,
            _fingerprinted(20000),
            node_id=node_id,
            runtime_version=version,
            profiles=(PROFILE,),
        )
        assert isinstance(result, GuardRefusal), (node_id, version)


def test_tools_are_another_shape() -> None:
    from app.domain.entities.chat import ToolDefinition

    request = replace(REQUEST, tools=(ToolDefinition(name="f", description="", parameters={}),))
    result = check_generation(
        request,
        REGISTERED,
        _fingerprinted(20000),
        node_id="local",
        runtime_version="0.33.2",
        profiles=(PROFILE,),
    )
    assert isinstance(result, GuardRefusal)
