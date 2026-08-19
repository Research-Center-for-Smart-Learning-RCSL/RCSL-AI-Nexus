"""Sandboxed chat-template compilation."""

from __future__ import annotations

import json
from typing import Any


def _build_template(source: str) -> Any:
    """The model's own chat template, rendered in a sandbox with Ollama's
    spelling of `tojson`.

    **The sandbox is not about the template**, which ships inside the weights an
    operator registered and is as trusted as they are. It is about what is
    rendered *through* it: message content is caller text, and a sandboxed
    environment is the difference between a template bug and a template bug that
    can reach an attribute of a Python object.

    **`tojson` is overridden because Jinja's own sorts keys**, and that showed
    up as a real error rather than a stylistic one: with sorted keys the count
    drifted by one token per tool definition — 12 low on 12 definitions, 58 low
    on 60 — so a 286-definition client would have been under-counted by about
    300 tokens, in the direction that ends in a silent truncation. Serialised in
    insertion order the same payloads are a constant +12 regardless of how many
    definitions there are.
    """
    from jinja2.exceptions import TemplateError
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def _raise(message: str) -> Any:
        raise TemplateError(message)

    environment = ImmutableSandboxedEnvironment(keep_trailing_newline=True)
    environment.globals["raise_exception"] = _raise
    # A plain string, not `Markup`: this environment does not escape, because
    # what it renders is counted and never served, so marking the JSON safe
    # would only be a claim about HTML that nothing here makes.
    environment.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
    return environment.from_string(source)
