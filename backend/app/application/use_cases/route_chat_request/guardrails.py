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
from app.domain.entities.node import Node
from app.domain.exceptions import (
    COUNT_BY_ESTIMATE,
    COUNT_BY_TOKENIZER,
    ContextTooLongError,
)
from app.domain.services import validated_profiles

from .dependencies import RouteChatDependencies
from .estimates import (
    _composition_parts,
    _counted_phrase,
    _describe_prompt_composition,
    _estimated_prompt_tokens,
    _estimated_tokens,
    effective_max_tokens,
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

    async def _effective_window(self, target: Model) -> int:
        """The context this target can actually hold: its registration, bounded
        by the context its weights declare.

        A registration above the declared figure is clamped by the runtime
        (the qwen7b row registered at 262144 against 32768, until 2026-09-07),
        so judging against it would admit prompts the runtime then cuts. The
        declared figure is read from the GGUF the counter already resolved;
        where it is unavailable the registration stands, as before.
        """
        registered = target.resource_profile.context_length
        declared = None
        if self._tokens is not None:
            try:
                declared = await self._tokens.native_context_length(target.ref)
            except Exception:  # noqa: BLE001 - an unreadable header is not a refusal
                declared = None
        if declared and registered > 0:
            return min(registered, declared)
        return registered

    async def _widened_window(
        self,
        target: Model,
        node: Node | None,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        thinking: bool,
    ) -> tuple[int, int, validated_profiles.ValidatedProfile] | None:
        """The window, the count and the profile, all from one snapshot, when
        this request's whole fingerprint is validated; None otherwise."""
        measure = getattr(self._tokens, "measure", None)
        if node is None or not callable(measure):
            return None
        version = validated_profiles.fresh_version(
            node.runtime_version, node.runtime_version_at, self._clock.now()
        )
        if version is None:
            return None
        measured = await measure(target.ref, messages, tools)
        if None in (measured.identity, measured.counted, measured.encoder, measured.renderer):
            return None
        key = validated_profiles.ProfileKey(
            node_id=node.id,
            runtime=target.runtime.value,
            runtime_version=version,
            manifest=measured.identity,
            encoder=measured.encoder,
            renderer=measured.renderer,
            tools=bool(tools),
            thinking=validated_profiles.wire_thinking(thinking),
        )
        profile = validated_profiles.is_validated(key)
        if profile is None:
            return None
        window = target.resource_profile.context_length
        if measured.declared_context:
            window = (
                min(window, measured.declared_context) if window > 0 else measured.declared_context
            )
        return window, int(measured.counted), profile

    async def _refuse_what_this_target_would_truncate(
        self,
        counted: int,
        basis: str,
        target: Model,
        actor: Actor,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        max_tokens: int | None = None,
        *,
        node: Node | None = None,
        thinking: bool = True,
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
        window = await self._effective_window(target)
        if window <= 0:
            return
        output = effective_max_tokens(max_tokens, self._max_tokens_ceiling)
        # Two bounds, and the tighter one decides (#24 final spec §6, PR2a).
        # Half the window is the legacy rule, kept until a profile is shown to
        # be counted exactly enough to drop it (PR2b). The second is new and is
        # what the runtime actually does (E1/T1, 2026-10-07): a prompt is kept
        # whole only below the window, and output that reaches the window
        # shifts the context on qwen2.5, discarding the system prompt. So the
        # prompt and the output this request may generate must both fit, one
        # token short of the window.
        servable = validated_profiles.servable(window, output, widened=False)
        if counted <= servable:
            return
        # PR2b: the half is dropped, the output bound kept, only for a profile
        # shown to be counted at least as high as the runtime evaluates it.
        # Asked only here, where the legacy rule would refuse, so an ordinary
        # request pays nothing for it. The node agent decides again with the
        # runtime's version read live; this is the gateway's own view of it.
        if basis == COUNT_BY_TOKENIZER:
            widened = await self._widened_window(target, node, messages, tools, thinking)
            if widened is not None:
                window_w, counted_w, profile = widened
                limit = validated_profiles.servable(window_w, output, widened=True)
                if max(counted, counted_w) <= limit:
                    logger.info(
                        "admitting %s to %s under validated profile %s (%s of %s) request_id=%s",
                        _counted_phrase(basis, counted),
                        target.alias,
                        profile.ref,
                        max(counted, counted_w),
                        limit,
                        self._request_id(),
                    )
                    return
                servable = limit
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
                f"serving this capability can read while leaving room for {output} "
                f"output tokens: {composition}"
            ),
            estimated=counted,
            limit=servable,
            composition=composition,
            basis=basis,
        )
