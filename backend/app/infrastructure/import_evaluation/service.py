"""Evaluation actor resolution and import service."""

from __future__ import annotations

import argparse
import logging
import sys

from app.adapters.audit.postgres_audit import PostgresAudit
from app.adapters.authz.role_authorization import RoleAuthorization
from app.adapters.persistence.repositories import (
    PostgresEvaluationRepository,
    PostgresUserRepository,
)
from app.application.use_cases.manage_evaluations import ManageEvaluations
from app.domain.entities.actor import Actor
from app.infrastructure.config import get_settings
from app.infrastructure.db import (
    dispose_engine,
    get_session_factory,
    init_engine,
    session_scope,
)
from app.shared.clock import SystemClock

from .parsing import _parse_ran_at, parse_samples

logger = logging.getLogger("app.infrastructure.import_evaluation")


async def _resolve_actor(login: str) -> Actor:
    """The administrator this import is performed as.

    Unscoped repository, like every other identity lookup in this codebase: the
    tenant is not known until the account is found. The actor's scopes come
    from the role table rather than from anything stored, so an account whose
    role does not carry `model:write` is refused by the use case.
    """
    authz = RoleAuthorization()
    async with session_scope() as session:
        user = await PostgresUserRepository.unscoped(session).get_by_login(login)
    if user is None:
        raise SystemExit(f"no account with login {login!r}")
    return Actor(
        id=user.id,
        display=user.login,
        role=user.role,
        # The importer runs as a person, through the same use case a browser
        # would reach; `local` is what that identity is called everywhere else.
        source="local",
        scopes=authz.scopes_for(user.role.value),
        tenant_id=user.tenant_id,
    )


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    init_engine(settings)
    try:
        # The harness writes every phase into the same file. `pilot` and
        # `full` answer different questions — one calibrates the task set, the
        # other compares candidates — and a repair phase re-runs tasks whose
        # earlier result measured something other than the model. Both are
        # reasons to name the phases rather than take the file whole.
        samples = parse_samples(sys.stdin.readlines(), phases=args.phase)
        if not samples:
            raise SystemExit("no samples on stdin")

        actor = await _resolve_actor(args.actor)
        async with session_scope() as session:
            use_case = ManageEvaluations(
                evaluations=PostgresEvaluationRepository(session),
                authz=RoleAuthorization(),
                audit=PostgresAudit(get_session_factory(), SystemClock()),
                clock=SystemClock(),
            )
            stored = await use_case.import_run(
                actor,
                samples,
                label=args.label,
                # The last phase named is what the run is filed under, since it
                # is the one whose numbers survive superseding.
                phase=args.phase[-1] if args.phase else "full",
                ran_at=_parse_ran_at(args.ran_at),
                harness_ref=args.harness_ref,
                caveats=args.caveat,
                note=args.note,
            )

        logger.info(
            "imported %s: %s samples, %s model(s), as %s",
            stored.run.label,
            stored.run.sample_count,
            len(stored.models),
            actor.display,
        )
        for model in stored.models:
            logger.info(
                "  %-28s %s scored, %s no result",
                model.model_ref,
                model.scored_samples,
                model.no_result_samples,
            )
        return 0
    finally:
        await dispose_engine()
