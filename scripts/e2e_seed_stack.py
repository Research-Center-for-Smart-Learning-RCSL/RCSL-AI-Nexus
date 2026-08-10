#!/usr/bin/env python3
"""Build the database the browser-to-gateway harness runs against.

Run by `frontend/e2e/support/full-stack.mjs`, which starts the admin entrance
and the gateway against the same Postgres this leaves behind. It prints one JSON
object on stdout -- the API key's plaintext among other things -- because a key
is only ever readable at issue, and the harness has no other way to hold one.

What is seeded is the smallest world in which "the operator edited the policy"
and "the gateway served a different model" are separate observable facts: one
node, two models both loaded and both able to serve `chat`, and a policy naming
one of them. Which model the runtime is asked for is then the whole assertion,
and it can only change because something changed the policy.

The schema is rebuilt from Alembic rather than from the ORM, for the reason
`tests/integration/conftest.py` records: building it from metadata leaves the
migrations unexecuted by anything.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.persistence.repositories import (
    PostgresApiKeyRepository,
    PostgresModelRepository,
    PostgresNodeRepository,
    PostgresRoutingPolicyRepository,
    PostgresUserRepository,
)
from app.domain.entities.actor import Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.model import Model, ModelState, ResourceProfile, RuntimeKind
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import Requirement, RoutingCandidate, RoutingPolicy
from app.domain.entities.user import User
from app.domain.services.api_key_service import ApiKeyService
from tests.integration.conftest import reset_schema

NODE_ID = "node-e2e"
OPERATOR_LOGIN = "dev@localhost"
"""Matches the default `DEV_TAILNET_LOGIN`. In `AUTH_MODE=dev` the tailnet
resolver substitutes this for the header `tailscale serve` would inject, and
everything after that -- the users lookup, the role, the scopes -- runs exactly
as it does in production."""

MODELS = (
    ("model-e2e-alpha", "alpha", "alpha-e2e:latest"),
    ("model-e2e-beta", "beta", "beta-e2e:latest"),
)
"""Two aliases whose refs differ, because the ref is what reaches the runtime.
Aliases that shared a ref would make a policy change invisible at exactly the
point this harness exists to observe."""

INITIAL_ALIAS = "alpha"


async def seed(database_url: str, pepper: str) -> dict[str, object]:
    await asyncio.to_thread(reset_schema, database_url)

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    issued = ApiKeyService(peppers=(pepper.encode(),)).issue()

    async with factory() as session:
        await PostgresUserRepository.unscoped(session).save(
            User(
                id="user-e2e",
                login=OPERATOR_LOGIN,
                display_name="E2E Operator",
                role=Role.ADMIN,
                tailscale_login=OPERATOR_LOGIN,
            )
        )

        await PostgresApiKeyRepository.unscoped(session).save(
            ApiKey(
                id=str(uuid.uuid4()),
                key_id=issued.key_id,
                digest=issued.digest,
                name="browser-to-gateway harness",
                owner_id="user-e2e",
                scopes=frozenset({"chat"}),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )

        await PostgresNodeRepository(session).save(
            Node(
                id=NODE_ID,
                name="e2e-node",
                address="100.64.0.9",
                status=NodeStatus.ONLINE,
                total_memory_gb=64.0,
                runtimes=frozenset({RuntimeKind.OLLAMA}),
            )
        )

        for model_id, alias, ref in MODELS:
            await PostgresModelRepository(session).save(
                Model(
                    id=model_id,
                    alias=alias,
                    ref=ref,
                    runtime=RuntimeKind.OLLAMA,
                    node_id=NODE_ID,
                    state=ModelState.LOADED,
                    capabilities=frozenset({"chat"}),
                    resource_profile=ResourceProfile(memory_gb=8.0, context_length=32768),
                )
            )

        await PostgresRoutingPolicyRepository(session).save(
            RoutingPolicy(
                capability="chat",
                candidates=(
                    RoutingCandidate(
                        model_alias=INITIAL_ALIAS,
                        priority=100,
                        require=Requirement(
                            node_status=frozenset({NodeStatus.ONLINE}),
                            model_state=frozenset({ModelState.LOADED}),
                        ),
                    ),
                ),
            )
        )
        await session.commit()

    await engine.dispose()

    return {
        "gateway_key": issued.plaintext,
        "operator_login": OPERATOR_LOGIN,
        "initial_alias": INITIAL_ALIAS,
        "aliases": [alias for _, alias, _ in MODELS],
        "refs": {alias: ref for _, alias, ref in MODELS},
    }


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    pepper = os.environ.get("API_KEY_PEPPER", "")
    if not database_url or not pepper:
        raise SystemExit("DATABASE_URL and API_KEY_PEPPER must both be set.")

    # stdout carries the harness's only copy of the key, so anything the
    # seeding path wants to say goes to stderr instead of corrupting it.
    result = asyncio.run(seed(database_url, pepper))
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
