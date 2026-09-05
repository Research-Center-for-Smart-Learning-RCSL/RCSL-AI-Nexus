"""Independent usage and transcript finalization for generation sessions."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence

from app.domain.entities.actor import Actor
from app.domain.entities.chat import Message
from app.domain.entities.model import Model
from app.domain.entities.usage import UsageRecord
from app.domain.ports.repositories import PromptLogWriterPort, UsageRepositoryPort
from app.domain.services.prompt_capture import TranscriptBuffer
from app.shared.clock import Clock

from .diagnostics import _warn_if_prompt_was_truncated

logger = logging.getLogger("app.application.use_cases.route_chat_request")


async def finalize_generation(
    *,
    usage: UsageRepositoryPort,
    prompt_logs: PromptLogWriterPort | None,
    request_id: Callable[[], str | None],
    clock: Clock,
    monotonic: Callable[[], float],
    started: float,
    actor: Actor,
    capability: str,
    requested_capability: str | None,
    target: Model,
    messages: Sequence[Message],
    produced: int,
    prompt_tokens: int,
    counted_prompt_tokens: int,
    counted_basis: str,
    completed: bool,
    transcript: TranscriptBuffer | None,
    finish_reason: str | None,
    compaction_tier: int | None = None,
    tokens_before_compaction: int | None = None,
    tokens_after_compaction: int | None = None,
) -> None:
    """Finalize both records without allowing either failure to hide the other."""
    _warn_if_prompt_was_truncated(
        prompt_tokens,
        target.resource_profile.context_length,
        estimated=counted_prompt_tokens,
        basis=counted_basis,
        request_id=request_id(),
        actor=actor.display,
    )

    try:
        await usage.record(
            UsageRecord(
                id=str(uuid.uuid4()),
                actor_id=actor.id,
                api_key_id=actor.api_key_id,
                capability=capability,
                requested_capability=requested_capability,
                model_alias=target.alias,
                tokens=produced,
                prompt_tokens=prompt_tokens,
                latency_ms=int((monotonic() - started) * 1000),
                completed=completed,
                at=clock.now(),
                tenant_id=actor.tenant_id,
                compaction_tier=compaction_tier,
                tokens_before_compaction=tokens_before_compaction,
                tokens_after_compaction=tokens_after_compaction,
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to record usage for actor=%s", actor.display)

    if transcript is not None and prompt_logs is not None:
        try:
            await prompt_logs.record(
                transcript.build(
                    at=clock.now(),
                    actor=actor,
                    capability=capability,
                    model_alias=target.alias,
                    request_id=request_id(),
                    messages=tuple(messages),
                    finish_reason=finish_reason,
                    completed=completed,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to record prompt transcript for actor=%s capability=%s",
                actor.display,
                capability,
            )
