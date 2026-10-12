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
    NoAvailableModelError,
)
from app.domain.ports.model_runtime_port import declared_context_for, runtime_for
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

    async def _effective_window(self, target: Model, node: Node | None = None) -> int:
        """The context this target can actually hold: its registration, bounded
        by the context its weights declare.

        A registration above the declared figure is clamped by the runtime
        (the qwen7b row registered at 262144 against 32768, until 2026-09-07),
        so judging against it would admit prompts the runtime then cuts. The
        declared figure comes from the selected node's metadata snapshot.
        Unresolved metadata cannot prove capacity and refuses admission.
        """
        registered = target.resource_profile.context_length
        runtime = runtime_for(self._runtimes, node, target.runtime) if node is not None else None
        declared = await declared_context_for(runtime, target.ref, self._tokens)
        if declared and registered > 0:
            return min(registered, declared)
        raise NoAvailableModelError(detail="capacity unresolved for the selected target")

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

    async def _prompt_budget(
        self,
        counted: int,
        basis: str,
        target: Model,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
        max_tokens: int | None,
        *,
        node: Node | None,
        thinking: bool,
    ) -> tuple[int, int, str | None]:
        """The same limit for compaction and final admission, on the selected node.

        Capacity resolution is independent of exact counting or empirical
        profile validation. An estimate reserves three times its input count.
        """
        window = await self._effective_window(target, node)
        output = effective_max_tokens(max_tokens, self._max_tokens_ceiling)
        servable = validated_profiles.servable(
            window, output, widened=target.runtime is not RuntimeKind.OLLAMA
        )
        if basis != COUNT_BY_TOKENIZER:
            return servable // 3, counted, None
        if counted > servable and target.runtime is RuntimeKind.OLLAMA:
            widened = await self._widened_window(target, node, messages, tools, thinking)
            if widened is not None:
                window_w, counted_w, profile = widened
                return (
                    validated_profiles.servable(window_w, output, widened=True),
                    max(counted, counted_w),
                    profile.ref,
                )
        return servable, counted, None

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
    ) -> validated_profiles.WidenedAdmission | None:
        """Run last, after every transform has been recounted.

        Only empirically validated exact profiles may drop Ollama's legacy
        half-window rule. The caller sees the bound and composition, never
        the selected alias. Widened admission carries the truncation backstop.
        """
        limit, judged, profile = await self._prompt_budget(
            counted, basis, target, messages, tools, max_tokens, node=node, thinking=thinking
        )
        if judged <= limit and limit > 0:
            if profile is not None:
                return validated_profiles.WidenedAdmission(
                    profile=profile, counted=judged, limit=limit
                )
            return None
        logger.warning(
            "refusing %s: target=%s servable=%s request_id=%s actor=%s",
            _counted_phrase(basis, judged),
            target.alias,
            limit,
            self._request_id(),
            actor.display,
        )
        composition = await self._prompt_composition(target, messages, tools, basis)
        output = effective_max_tokens(max_tokens, self._max_tokens_ceiling)
        raise ContextTooLongError(
            detail=(
                f"{_counted_phrase(basis, judged)} exceeds the {limit} the model "
                f"serving this capability can read while leaving room for {output} "
                f"output tokens: {composition}"
            ),
            estimated=judged,
            limit=limit,
            composition=composition,
            basis=basis,
        )
