"""Independent usage and transcript finalization for generation sessions."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence

from app.domain.entities.actor import Actor
from app.domain.entities.attempt import AttemptIdentity
from app.domain.entities.chat import Message
from app.domain.entities.model import Model
from app.domain.entities.usage import UsageRecord
from app.domain.ports.repositories import PromptLogWriterPort, UsageRepositoryPort
from app.domain.ports.request_binding_port import UsageSettlementPort
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
    attempt: AttemptIdentity | None = None,
    settlement: UsageSettlementPort | None = None,
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

    if attempt is not None and settlement is not None:
        await _settle_attempt(settlement, attempt, completed=completed, actor=actor)
    else:
        await _record_usage(
            usage,
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
            ),
            actor,
        )

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
                    compaction_tier=compaction_tier,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to record prompt transcript for actor=%s capability=%s",
                actor.display,
                capability,
            )


async def _record_usage(usage: UsageRepositoryPort, record: UsageRecord, actor: Actor) -> None:
    try:
        await usage.record(record)
    except Exception:  # noqa: BLE001
        logger.exception("failed to record usage for actor=%s", actor.display)


async def _settle_attempt(
    settlement: UsageSettlementPort,
    attempt: AttemptIdentity,
    *,
    completed: bool,
    actor: Actor,
) -> None:
    """An agent-backed attempt: delivery first, then the one usage row.

    No partial row is ever written here (design S6). When the client left
    while the agent drains to `done`, the attempt is not terminal yet and
    `settle` writes nothing; the admin sweeper settles it once it is. A
    failure here loses nothing either: the sweeper finds the attempt
    unsettled and writes the same row.
    """
    try:
        await settlement.mark_delivery(attempt.op_id, completed)
        await settlement.settle(attempt.op_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "failed to settle usage for attempt=%s actor=%s; the sweeper will",
            attempt.op_id,
            actor.display,
        )
