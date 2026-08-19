"""PromptGuardrails stage."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.domain.entities.actor import Actor
from app.domain.entities.chat import (
    Message,
    ToolDefinition,
)
from app.domain.entities.model import Model, RuntimeKind
from app.domain.exceptions import (
    COUNT_BY_ESTIMATE,
    COUNT_BY_TOKENIZER,
    ContextTooLongError,
)

from .dependencies import RouteChatDependencies
from .estimates import (
    _composition_parts,
    _counted_phrase,
    _describe_prompt_composition,
    _estimated_prompt_tokens,
    _estimated_tokens,
)

logger = logging.getLogger("app.application.use_cases.route_chat_request")


class PromptGuardrailsMixin(RouteChatDependencies):
    async def _count_prompt(
        self, target: Model, messages: Sequence[Message], tools: Sequence[ToolDefinition]
    ) -> tuple[int, str]:
        """What the target will actually read, and how that figure was reached.

        The counter answers `None` for a target whose vocabulary this host
        cannot resolve — an MLX model, a reference registered but not pulled, a
        missing mount — and the character estimate answers instead, which is
        what every request was counted by before 2026-08-17. That fallback is
        not a degraded mode to be alarmed about; it is the previous behaviour,
        and the guardrail must have an answer before hardware is committed.

        The basis travels with the number because three readers need it: the
        caller, who is told a different sentence for a count than for an
        estimate; the drift log, which judges an exact count against a window
        of tokens and an estimate against a band of ratios; and this file's own
        refusal messages, which stopped saying "estimated" about a figure that
        is not one.
        """
        if self._tokens is not None:
            counted = await self._tokens.count_prompt(target.ref, messages, tools)
            if counted is not None:
                return counted, COUNT_BY_TOKENIZER
        estimated, _ = _estimated_prompt_tokens(messages, tools)
        return estimated, COUNT_BY_ESTIMATE

    async def _prompt_composition(
        self,
        target: Model,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        basis: str,
    ) -> str:
        """The breakdown that goes to a refused caller, on the same basis as
        the figure it accompanies.

        **`basis` decides, not the counter's availability**, and the difference
        is not hypothetical: `count_prompt` declines for a payload shape the
        chat template refuses and for tool-call arguments that are not JSON,
        while `count_parts` needs no template and would have answered exactly.
        Asking each independently produced a refusal quoting an estimated total
        beside tokenised shares — the arithmetic this method exists to keep
        consistent, failing in the one direction nobody would look for.
        """
        parts = _composition_parts(messages, tools)
        counts: Sequence[int] | None = None
        if basis == COUNT_BY_TOKENIZER and self._tokens is not None:
            counts = await self._tokens.count_parts(target.ref, parts)
        if counts is None:
            counts = [_estimated_tokens(part) for part in parts]
        return _describe_prompt_composition(messages, tools, counts)

    async def _refuse_what_this_target_would_truncate(
        self,
        counted: int,
        basis: str,
        target: Model,
        actor: Actor,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> None:
        """The input ceiling again, against the model that will actually serve it.

        `max_context_length` is one number for the whole deployment, and its
        docstring asks an operator to keep it below half the registered
        `context_length` of *every* model that serves a capability — by hand,
        across three values that live in three different places. On 2026-08-17
        that invariant was not holding: the global ceiling was 98304 and exactly
        half of `qwen36-35b-a3b-q8`'s registered 196608, so it sat *at* the
        truncation point rather than below it, and `chat` still fell back to
        `qwen7b`, whose 8192 put the same point at 4096 — twenty-four times
        under the ceiling that admitted the request.

        **The capability it actually bit was `assist`,** which routes to
        `qwen7b` alone. The management assistant's own system prompt estimates
        3551 tokens against that 4096, so the first reply longer than roughly
        500 tokens made the second turn refuse — against a 1536-token reply
        budget. Before this check the same conversation was served from a
        prompt Ollama had cut the front off, which is where the instructions
        and the nonce-delimited data boundary live. `qwen7b` was widened to its
        native 32768 the same evening, putting that point at 16384; this check
        is what turned an invisible truncation into a visible one.

        Checked here because this is the first line where the target is known.
        A fallback to a smaller model now refuses rather than answering from a
        prompt whose beginning it never read, which is the failure the global
        ceiling exists to prevent and the one an operator cannot see: the reply
        is fluent, and only wrong.

        **Only Ollama halves.** MLX serves its full registered context (see
        `mlx_adapter.load`), so a target on any other runtime is bounded by the
        global ceiling alone rather than by a rule that does not describe it.

        A zero `context_length` is a row registered before the profile was
        required, not a model that can serve nothing; `_set_num_ctx` declines to
        send it for the same reason, and this declines to judge against it.
        """
        if target.runtime is not RuntimeKind.OLLAMA:
            return
        servable = target.resource_profile.context_length // 2
        if servable <= 0 or counted <= servable:
            return
        # The alias is named to the operator and not to the caller. A refusal
        # that named it would disclose the model inventory to anyone who could
        # provoke one, which is the disclosure `NoAvailableModelError` is
        # careful about a few lines above.
        logger.warning(
            "refusing %s: %s would evaluate at most num_ctx/2=%s of "
            "them and drop the rest request_id=%s actor=%s",
            _counted_phrase(basis, counted),
            target.alias,
            servable,
            self._request_id(),
            actor.display,
        )
        composition = await self._prompt_composition(target, messages, tools, basis)
        # `limit` reaches the caller and is half this model's registered
        # context, so a fallback refusal tells them roughly how large the model
        # standing in is. Weighed and accepted on 2026-08-17 — a number they
        # cannot see is a refusal they cannot act on — and the alias still is
        # not sent. See `ContextTooLongError.__init__`.
        raise ContextTooLongError(
            detail=(
                f"{_counted_phrase(basis, counted)} exceeds the {servable} the model "
                f"serving this capability can read: {composition}"
            ),
            estimated=counted,
            limit=servable,
            composition=composition,
            basis=basis,
        )
