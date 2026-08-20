"""Dependency providers for inference runtime."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.adapters.metrics.prometheus import MeteredUsageRepository
from app.adapters.persistence.model_state import ModelStateCommitter
from app.adapters.persistence.repositories import (
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresPromptLogWriter,
    PostgresRoutingPolicyRepository,
    PostgresUsageRepository,
)
from app.application.use_cases.assist_operator import AssistOperator
from app.application.use_cases.download_model import DownloadModel
from app.application.use_cases.list_capabilities import ListCapabilities
from app.application.use_cases.manage_models import ManageModels
from app.application.use_cases.manage_routing_policies import ManageRoutingPolicies
from app.application.use_cases.route_chat_request import RouteChatRequest
from app.domain.ports.repositories import UsageRepositoryPort
from app.domain.services.memory_budget_service import MemoryBudgetService
from app.domain.services.routing_service import RoutingService
from app.infrastructure.db import get_session_factory
from app.interfaces.http.request_context import current_request_id
from app.shared.clock import SystemClock

from .shared import SessionDep, SettingsDep


def build_route_chat_request(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> RouteChatRequest:
    # Unscoped: RouteChatRequest stamps the record's tenant from the authenticated
    # actor, so the write lands under the key's tenant. Wrapped to emit inference
    # metrics from the same UsageRecord the streaming path already produces, which
    # is what keeps that generator untouched; see adapters/metrics/prometheus.py.
    usage: UsageRepositoryPort = PostgresUsageRepository.unscoped(session)
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        usage = MeteredUsageRepository(usage, metrics)
    return RouteChatRequest(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        usage=usage,
        runtimes=request.app.state.runtimes,
        routing=RoutingService(),
        concurrency=request.app.state.concurrency,
        authz=request.app.state.authz,
        clock=SystemClock(),
        max_tokens_ceiling=settings.max_tokens_ceiling,
        # From `app.state`, not built here: see `build_token_counter`. A
        # deployment without a model store passes `None`, and the use case
        # falls back to the character estimate it used before this existed.
        tokens=getattr(request.app.state, "token_counter", None),
        # The same use case `GET /v1/models` answers from, so a refusal names
        # exactly the list that endpoint would have returned. Read only when
        # refusing a capability the key was not issued.
        capabilities=ListCapabilities(
            policies=PostgresRoutingPolicyRepository(session),
            authz=request.app.state.authz,
        ),
        # A session *factory*, not the request's session. The transcript is
        # written in a `finally` that runs when the request has failed, and a
        # failed request rolls its session back — which would discard exactly
        # the transcript somebody opened a window to read. Same reason
        # `build_audit` hands `PostgresAudit` a factory. The tenant rides on the
        # entity, from the resolved actor, as it does for usage.
        #
        # Wired on all three entrances, not only the gateway. The user-side
        # debug window exists precisely because the management chat carries no
        # API key (§9.2), and giving the admin apps no writer here would have
        # rebuilt that gap one layer down.
        prompt_logs=PostgresPromptLogWriter(get_session_factory()),
        request_id=current_request_id,
        max_context_tokens=settings.max_context_length,
        generation_deadline_seconds=settings.generation_deadline_seconds,
        thinking_default=settings.ollama_thinking,
    )


def build_list_capabilities(request: Request, session: SessionDep) -> ListCapabilities:
    """Unscoped: routing policies are platform-global, like models and nodes.
    Built for both entrances, since the gateway answers `GET /v1/models` from
    the same use case the management UI reads."""
    return ListCapabilities(
        policies=PostgresRoutingPolicyRepository(session),
        authz=request.app.state.authz,
    )


def build_assist_operator(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> AssistOperator:
    """Built on the admin entrances only; nothing on the gateway reaches it.

    Composed from `build_route_chat_request` rather than from its parts, so the
    assistant inherits the streaming contract and every resource guardrail by
    construction. A second assembly here would be a second place for the
    concurrency slot or the wall-clock deadline to be forgotten, and the
    assistant is inference like any other — it just happens to be about the
    platform rather than for a user.
    """
    return AssistOperator(
        chat=build_route_chat_request(request, session, settings),
        authz=request.app.state.authz,
        clock=SystemClock(),
        gateway_base_url=settings.gateway_base_url,
        # The same figure `build_manage_api_keys` is given, from the same
        # setting. The assistant states this limit to an operator who is about
        # to rely on it, so the two disagreeing would be worse than either being
        # wrong alone.
        max_lifetime_days=settings.api_key_max_lifetime_days,
        max_context_length=settings.max_context_length,
        max_tokens=settings.assistant_max_tokens,
    )


ListCapabilitiesDep = Annotated[ListCapabilities, Depends(build_list_capabilities)]


RouteChatRequestDep = Annotated[RouteChatRequest, Depends(build_route_chat_request)]


AssistOperatorDep = Annotated[AssistOperator, Depends(build_assist_operator)]


MemoryBudgetDep = Annotated[MemoryBudgetService, Depends(MemoryBudgetService)]


def build_manage_models(
    request: Request, session: SessionDep, settings: SettingsDep
) -> ManageModels:
    return ManageModels(
        models=PostgresModelRepository(session),
        nodes=PostgresNodeRepository(session),
        policies=PostgresRoutingPolicyRepository(session),
        runtimes=request.app.state.runtimes,
        budget=MemoryBudgetService(),
        # Its own session factory, so a terminal state write survives the
        # request transaction rolling back when a load or unload raises.
        state_committer=ModelStateCommitter(get_session_factory()),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
        # The same process-wide counter the chat path uses, so a model warmed
        # here is warm for the requests that follow. A per-request instance
        # would build a vocabulary and then throw it away.
        tokens=getattr(request.app.state, "token_counter", None),
    )


def build_download_model(request: Request, session: SessionDep) -> DownloadModel:
    return DownloadModel(
        models=PostgresModelRepository(session),
        runtimes=request.app.state.runtimes,
        jobs=request.app.state.jobs,
        state_committer=ModelStateCommitter(get_session_factory()),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )


def build_manage_routing_policies(request: Request, session: SessionDep) -> ManageRoutingPolicies:
    return ManageRoutingPolicies(
        policies=PostgresRoutingPolicyRepository(session),
        models=PostgresModelRepository(session),
        authz=request.app.state.authz,
        audit=request.app.state.audit,
    )
