"""The gemma4 port against the bytes the runtime rendered.

The runtime renders gemma4 with a built-in renderer and the GGUF ships no
template, so the counter carries a port (`gemma4_renderer.py`). Counting is only
as right as the rendering, and the rendering is checkable byte for byte: these
cases exercise nested schemas, unions, enums with numbers, nullable fields,
floats in Go's format, several calls in a turn, results with and without call
ids, consecutive assistant turns, a developer role, Go-only whitespace, and
thinking on (field omitted) and off.
"""

from __future__ import annotations

import pytest

from app.adapters.tokenizer.gguf_token_counter.gemma4_renderer import (
    Gemma4Renderer,
    renderer_variant,
)
from tests.unit.gemma4_render_goldens import CASES, RENDERED, TOOLS

_RENDERER = Gemma4Renderer(large=True)


@pytest.mark.parametrize("key", sorted(RENDERED))
def test_the_port_renders_the_runtimes_bytes(key: str) -> None:
    name, _, wire = key.partition("/think=")
    think = None if wire == "omitted" else False

    rendered = _RENDERER.render(messages=CASES[name], tools=TOOLS, think=think)

    assert rendered == RENDERED[key]


def test_an_omitted_think_is_thinking_on() -> None:
    """Measured: the runtime renders `<|think|>` when the field is absent."""
    on = _RENDERER.render(messages=[{"role": "user", "content": "x"}], think=None)
    off = _RENDERER.render(messages=[{"role": "user", "content": "x"}], think=False)

    assert "<|think|>" in on
    assert "<|think|>" not in off


def test_the_variant_follows_the_runtimes_names_and_defaults_large() -> None:
    assert renderer_variant("gemma4:e4b") == "small"
    assert renderer_variant("gemma4:31b-it-q8_0") == "large"
    # Undecided: the runtime picks small; large only adds tokens.
    assert renderer_variant("my-gemma") == "large"
