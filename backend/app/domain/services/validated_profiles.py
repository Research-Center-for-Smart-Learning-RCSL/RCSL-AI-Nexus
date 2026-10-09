"""Which counting profiles may use the whole window (PR2b on #24).

The guard's legacy rule admits a prompt only up to half the model's window;
PR2a added "and leave room for the output" (`window − 1 − output`). PR2b drops
the half, keeping the output bound, **only** for a profile shown to be counted
at least as high as the runtime evaluates it. This file is that evidence's
catalogue, reviewed like code (design adopted on #24, review points 1–4):

- **The key is the whole measured fingerprint.** The node, the runtime and its
  version, the model manifest (full SHA-256), the counting code (encoder and
  renderer digests, `gguf_token_counter/fingerprint.py`), and the request
  shape: whether tools are sent, and how thinking appears on the wire. Any
  part that differs falls back to the legacy rule, so an Ollama upgrade, a
  re-pull, an edit to the encoder or a second node withdraws widening with no
  step for anyone to remember.
- **Thinking modes are listed, not inferred.** A record names the wire forms
  it was measured with (`omitted`, `false`, `true`); anything else falls back.
- **Tools are a separate shape.** qwen2.5's tool definitions are rendered as
  a Go struct by Ollama (#27); the maintainer kept that model, so its tool
  shape stays unvalidated.
- **What a record is not.** Finite-corpus evidence that the count bounds the
  runtime on these shapes, recorded with the runtime's own counts
  (`runtime_validation_corpus.RECORDED`) and held by
  `test_validated_profiles.py`. The global `MAX_CONTEXT_LENGTH` still applies.

A runtime version the caller observed too long ago is no version: the gateway
reads the heartbeat's observation and requires it fresh, and the node agent,
which sends, reads the runtime's version itself before it decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

VERSION_FRESHNESS = timedelta(minutes=5)
"""How old a heartbeat's runtime version may be and still key a profile."""

WIRE_THINKING = ("omitted", "false", "true")


@dataclass(frozen=True, slots=True)
class ProfileKey:
    node_id: str
    runtime: str
    runtime_version: str
    manifest: str
    encoder: str
    renderer: str
    tools: bool
    thinking: str
    """How `think` appears on the wire: `omitted`, `false` or `true`."""


@dataclass(frozen=True, slots=True)
class ValidatedProfile:
    ref: str
    """For people; matching never uses it, the manifest is what was measured."""
    node_id: str
    runtime: str
    runtime_version: str
    manifest: str
    encoders: frozenset[str]
    """Each backend measured equal: native and Python count the same."""
    renderer: str
    tools: bool
    thinking: frozenset[str]
    measured_on: str
    cases: tuple[str, ...]
    """The validation-corpus cases the record stands on; each one must have a
    recorded runtime count no greater than the count."""

    def covers(self, key: ProfileKey) -> bool:
        return (
            key.node_id == self.node_id
            and key.runtime == self.runtime
            and key.runtime_version == self.runtime_version
            and key.manifest == self.manifest
            and key.encoder in self.encoders
            and key.renderer == self.renderer
            and key.tools == self.tools
            and key.thinking in self.thinking
        )


VALIDATED: tuple[ValidatedProfile, ...] = (
    # qwen2.5:7b, which serves `assist` and stands in for `chat`, without
    # tools. Its encoder gives the runtime's own token ids on 3,036 random
    # texts and 203 recorded goldens (`qwen_tokenizer_goldens`), and its GGUF
    # template renders tool-less prompts as the runtime does: U − P = 0 on
    # every case below. With tools it is not validated (#27).
    ValidatedProfile(
        ref="qwen2.5:7b",
        node_id="local",
        runtime="ollama",
        runtime_version="0.33.2",
        manifest="845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
        encoders=frozenset({"native:7b26ae0075c9cf07", "python:0ca0ada64166ed40"}),
        renderer="jinja:2c9abc88aee670e3",
        tools=False,
        thinking=frozenset({"false", "omitted"}),
        measured_on="2026-10-09",
        cases=(
            "system_multiturn",
            "thinking_gateway",
            "repeat_short_words",
            "repeat_arrows",
            "repeat_cjk_pairs",
            "repeat_indent_runs",
            "near_boundary_qwen_16k",
            "near_boundary_qwen_32k",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class WidenedAdmission:
    """What the guard judged when it admitted a request under a profile: the
    profile, the count it compared (the larger of its two), and the limit.
    The truncation backstop judges the runtime's figure against this count."""

    profile: str
    counted: int
    limit: int


def is_validated(
    key: ProfileKey, profiles: tuple[ValidatedProfile, ...] | None = None
) -> ValidatedProfile | None:
    catalogue = VALIDATED if profiles is None else profiles
    return next((p for p in catalogue if p.covers(key)), None)


def wire_thinking(thinking: bool) -> str:
    """The wire form the Ollama encoder gives a thinking flag: on is the field
    omitted, off is `false` (`ollama_adapter/encoding.py`)."""
    return "omitted" if thinking else "false"


def fresh_version(version: str | None, observed_at: datetime | None, now: datetime) -> str | None:
    if version is None or observed_at is None or now - observed_at > VERSION_FRESHNESS:
        return None
    return version


def servable(window: int, output: int, *, widened: bool) -> int:
    """The largest prompt a target may be sent (PR2a's rule, and PR2b's)."""
    full = window - 1 - output
    return full if widened else min(window // 2, full)
