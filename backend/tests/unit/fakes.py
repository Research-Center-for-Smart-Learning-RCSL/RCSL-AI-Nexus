"""Test doubles for the authentication use cases.

These implement the repository and security ports directly rather than
wrapping a mock, because the behaviour under test is mostly about *which*
method is called and in what order: that a dummy hash runs before an unknown
login is refused, that a counter is claimed with a conditional write rather
than a comparison. A mock that answers anything would pass those tests while
the production wiring did nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import datetime
from ipaddress import ip_network

from app.domain.entities.actor import Actor, Role
from app.domain.entities.api_key import ApiKey
from app.domain.entities.invitation import Invitation, InvitationPurpose, RecoveryCode
from app.domain.entities.knowledge import DocumentStatus
from app.domain.entities.model import Model, ModelState, PullProgress
from app.domain.entities.node import Node, NodeStatus
from app.domain.entities.routing_policy import RoutingPolicy
from app.domain.entities.tenant import Tenant
from app.domain.entities.usage import BucketUnit, UsageBucket, UsageRecord
from app.domain.entities.user import User
from app.domain.exceptions import InvalidModelReferenceError, InvalidNodeAddressError
from app.domain.ports.infrastructure_ports import JobStatus


class FakeUsers:
    def __init__(self, users: Sequence[User] = ()) -> None:
        self.rows: dict[str, User] = {u.id: u for u in users}
        self.counter_claims: list[tuple[str, int]] = []

    async def get(self, user_id: str) -> User | None:
        return self.rows.get(user_id)

    async def get_by_login(self, login: str) -> User | None:
        return next((u for u in self.rows.values() if u.login == login), None)

    async def get_by_tailscale_login(self, login: str) -> User | None:
        return next((u for u in self.rows.values() if u.tailscale_login == login), None)

    async def list_all(self) -> list[User]:
        return list(self.rows.values())

    async def display_names(self) -> dict[str, str]:
        return {u.id: u.display_name for u in self.rows.values()}

    async def count(self) -> int:
        return len(self.rows)

    async def save(self, user: User) -> None:
        self.rows[user.id] = user

    async def insert_if_absent(self, user: User) -> User:
        existing = await self.get_by_login(user.login)
        if existing is not None:
            return existing
        self.rows[user.id] = user
        return user

    async def advance_totp_counter(self, user_id: str, counter: int) -> bool:
        """Models the conditional UPDATE, including that it refuses to move
        backwards. A version that always returned True would let every replay
        test pass against a broken implementation."""
        self.counter_claims.append((user_id, counter))
        user = self.rows[user_id]
        if user.totp_last_counter is not None and counter <= user.totp_last_counter:
            return False
        self.rows[user_id] = replace(user, totp_last_counter=counter)
        return True

    async def set_disabled(self, user_id: str, at: datetime | None) -> None:
        self.rows[user_id] = replace(self.rows[user_id], disabled_at=at)

    async def update_profile(self, user_id: str, *, display_name: str, role: str) -> None:
        self.rows[user_id] = replace(self.rows[user_id], display_name=display_name, role=Role(role))

    async def delete(self, user_id: str) -> None:
        self.rows.pop(user_id, None)

    async def count_admins(self) -> int:
        # Enabled administrators only, matching the repository. A disabled one
        # cannot sign in, so counting them would let the last-admin guard pass
        # while leaving nobody able to manage the instance.
        return sum(1 for u in self.rows.values() if u.role is Role.ADMIN and u.disabled_at is None)


class FakeInvitations:
    def __init__(self) -> None:
        self.rows: dict[str, Invitation] = {}
        self.codes: dict[str, RecoveryCode] = {}

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        return next((i for i in self.rows.values() if i.token_hash == token_hash), None)

    async def save(self, invitation: Invitation) -> None:
        self.rows[invitation.id] = invitation

    async def consume(self, invitation_id: str, at: datetime) -> bool:
        invitation = self.rows.get(invitation_id)
        if invitation is None or invitation.consumed_at is not None:
            return False
        self.rows[invitation_id] = replace(invitation, consumed_at=at)
        return True

    async def invalidate_outstanding(self, user_id: str, purpose: InvitationPurpose) -> None:
        self.rows = {
            k: v
            for k, v in self.rows.items()
            if not (v.user_id == user_id and v.purpose == purpose and v.consumed_at is None)
        }

    async def save_recovery_codes(self, codes: list[RecoveryCode]) -> None:
        for code in codes:
            self.codes[code.id] = code

    async def list_recovery_codes(self, user_id: str) -> list[RecoveryCode]:
        return [c for c in self.codes.values() if c.user_id == user_id]

    async def delete_recovery_codes(self, user_id: str) -> None:
        self.codes = {k: v for k, v in self.codes.items() if v.user_id != user_id}

    async def delete_for_user(self, user_id: str) -> None:
        await self.delete_recovery_codes(user_id)
        self.rows = {k: v for k, v in self.rows.items() if v.user_id != user_id}

    async def consume_recovery_code(self, code_id: str, at: datetime) -> bool:
        code = self.codes.get(code_id)
        if code is None or code.used_at is not None:
            return False
        self.codes[code_id] = replace(code, used_at=at)
        return True


class FakeHasher:
    """Reversible on purpose: the tests are about control flow, not argon2.

    `dummy_calls` is what the enumeration tests assert on, since the defence
    is "comparable work happened", not "a particular value was returned".
    """

    def __init__(self) -> None:
        self.dummy_calls = 0

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{password}"

    async def dummy_verify(self) -> None:
        self.dummy_calls += 1


class FakeSecretBox:
    def encrypt(self, plaintext: str) -> str:
        return f"enc:{plaintext}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc:")


class FakeAudit:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str | None, str]] = []

    async def record(
        self,
        actor: Actor,
        action: str,
        *,
        target: str | None = None,
        outcome: str = "success",
        detail: dict[str, str] | None = None,
    ) -> None:
        self.entries.append((action, target, outcome))

    def actions(self) -> list[str]:
        return [action for action, _, _ in self.entries]


class FakeSessions:
    def __init__(self) -> None:
        self.invalidated_all: list[str] = []
        self.invalidated_others: list[tuple[str, str]] = []

    async def invalidate_all(self, user_id: str, now: datetime) -> None:
        self.invalidated_all.append(user_id)

    async def invalidate_others(self, user_id: str, keep_session_id: str, now: datetime) -> None:
        self.invalidated_others.append((user_id, keep_session_id))


class AcceptingPolicy:
    def assert_acceptable(self, password: str, *, user_inputs: Sequence[str] = ()) -> None:
        return None


class FakeModels:
    def __init__(self, models: Sequence[Model] = ()) -> None:
        self.rows: dict[str, Model] = {m.id: m for m in models}

    async def get(self, model_id: str) -> Model | None:
        return self.rows.get(model_id)

    async def get_by_alias(self, alias: str) -> Model | None:
        return next((m for m in self.rows.values() if m.alias == alias), None)

    async def list_all(self) -> list[Model]:
        return list(self.rows.values())

    async def list_loaded(self, node_id: str) -> list[Model]:
        return [
            m for m in self.rows.values() if m.node_id == node_id and m.state is ModelState.LOADED
        ]

    async def save(self, model: Model) -> None:
        self.rows[model.id] = model

    async def set_state(self, model_id: str, state: ModelState) -> None:
        self.rows[model_id] = replace(self.rows[model_id], state=state)

    async def delete(self, model_id: str) -> None:
        self.rows.pop(model_id, None)

    async def list_occupying_memory(self, node_id: str) -> list[Model]:
        return [
            model
            for model in self.rows.values()
            if model.node_id == node_id and model.state in (ModelState.LOADED, ModelState.LOADING)
        ]

    async def reconcile_transient_states(self, mapping: dict[ModelState, ModelState]) -> int:
        moved = 0
        for model in list(self.rows.values()):
            if model.state in mapping:
                self.rows[model.id] = replace(model, state=mapping[model.state])
                moved += 1
        return moved


class FakeStateCommitter:
    """The independent-transaction state writer, which in a fake is just a
    second handle on the same store: the test has no transaction to roll back,
    so the point being modelled is only that these writes are visible to the
    reads the use case makes afterwards."""

    def __init__(self, models: FakeModels) -> None:
        self._models = models

    async def get(self, model_id: str) -> Model | None:
        return self._models.rows.get(model_id)

    async def commit(self, model_id: str, state: ModelState) -> None:
        self._models.rows[model_id] = replace(self._models.rows[model_id], state=state)


class FakeNodes:
    def __init__(self, nodes: Sequence[Node] = ()) -> None:
        self.rows: dict[str, Node] = {n.id: n for n in nodes}

    async def get(self, node_id: str) -> Node | None:
        return self.rows.get(node_id)

    async def list_all(self) -> list[Node]:
        return list(self.rows.values())

    async def save(self, node: Node) -> None:
        self.rows[node.id] = node

    async def set_status(self, node_id: str, status: NodeStatus) -> None:
        self.rows[node_id] = replace(self.rows[node_id], status=status)

    async def delete(self, node_id: str) -> None:
        self.rows.pop(node_id, None)


class FakeTenants:
    def __init__(self, tenants: Sequence[Tenant] = ()) -> None:
        self.rows: dict[str, Tenant] = {t.id: t for t in tenants}

    async def get(self, tenant_id: str) -> Tenant | None:
        return self.rows.get(tenant_id)

    async def get_by_name(self, name: str) -> Tenant | None:
        return next((t for t in self.rows.values() if t.name == name), None)

    async def list_all(self) -> list[Tenant]:
        return list(self.rows.values())

    async def save(self, tenant: Tenant) -> None:
        self.rows[tenant.id] = tenant


class FakeEgressGuard:
    """Records every address checked, and refuses those in `blocked` with the
    domain error the real guard raises. A use case that forgets to run the guard
    before storing an address then fails a test rather than passing silently."""

    def __init__(self, blocked: frozenset[str] = frozenset()) -> None:
        self.checked: list[str] = []
        self._blocked = blocked

    async def assert_node_address_allowed(self, address: str) -> None:
        self.checked.append(address)
        if address in self._blocked:
            raise InvalidNodeAddressError(detail=f"blocked {address}")


class FakeNodeHealth:
    def __init__(self, status: NodeStatus = NodeStatus.ONLINE) -> None:
        self.status = status
        self.probed: list[str] = []

    async def probe(self, node: Node) -> NodeStatus:
        self.probed.append(node.id)
        return self.status


class FakePolicies:
    def __init__(self, policies: Sequence[RoutingPolicy] = ()) -> None:
        self.rows: dict[str, RoutingPolicy] = {p.capability: p for p in policies}

    async def get(self, capability: str) -> RoutingPolicy | None:
        return self.rows.get(capability)

    async def list_all(self) -> list[RoutingPolicy]:
        return list(self.rows.values())

    async def save(self, policy: RoutingPolicy) -> None:
        self.rows[policy.capability] = policy

    async def delete(self, capability: str) -> None:
        self.rows.pop(capability, None)


class FakeApiKeys:
    def __init__(self, keys: Sequence[ApiKey] = ()) -> None:
        self.rows: dict[str, ApiKey] = {k.key_id: k for k in keys}

    async def get_by_key_id(self, key_id: str) -> ApiKey | None:
        return self.rows.get(key_id)

    async def list_for_owner(self, owner_id: str) -> list[ApiKey]:
        return [k for k in self.rows.values() if k.owner_id == owner_id]

    async def list_all(self) -> list[ApiKey]:
        return list(self.rows.values())

    async def save(self, key: ApiKey) -> None:
        self.rows[key.key_id] = key

    async def revoke(self, key_id: str, at: datetime) -> None:
        key = self.rows[key_id]
        if key.revoked_at is None:
            self.rows[key_id] = replace(key, revoked_at=at)

    async def update_settings(self, key_id: str, values: dict[str, object]) -> bool:
        key = self.rows.get(key_id)
        if key is None or key.revoked_at is not None:
            return False
        self.rows[key_id] = replace(
            key,
            name=values["name"],
            scopes=frozenset(values["scopes"]),  # type: ignore[arg-type]
            expires_at=values["expires_at"],
            rate_limit_rpm=values["rate_limit_rpm"],
            quota_tokens_per_day=values["quota_tokens_per_day"],
            allowed_cidrs=tuple(ip_network(c) for c in values["allowed_cidrs"]),  # type: ignore[union-attr]
        )
        return True

    async def delete_for_owner(self, owner_id: str) -> None:
        self.rows = {k: v for k, v in self.rows.items() if v.owner_id != owner_id}


class FakeUsage:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    async def tokens_used_today(self, api_key_id: str) -> int:
        return sum(r.tokens for r in self.records if r.api_key_id == api_key_id)

    async def last_used_by_key(self) -> dict[str, datetime]:
        latest: dict[str, datetime] = {}
        for record in self.records:
            if record.api_key_id is None:
                continue
            current = latest.get(record.api_key_id)
            if current is None or record.at > current:
                latest[record.api_key_id] = record.at
        return latest

    async def totals_since(self, since: datetime) -> tuple[int, int]:
        window = [r for r in self.records if r.at >= since]
        return len(window), sum(r.tokens for r in window)

    async def bucketed_usage(
        self, since: datetime, until: datetime, unit: BucketUnit
    ) -> list[UsageBucket]:
        # A Python stand-in for date_trunc: enough to fold in the tests. The real
        # SQL bucketing is exercised against Postgres, not here.
        buckets: dict[tuple[datetime, str], list[int]] = {}
        for r in self.records:
            if not (since <= r.at < until):
                continue
            if unit == "hour":
                start = r.at.replace(minute=0, second=0, microsecond=0)
            else:
                start = r.at.replace(hour=0, minute=0, second=0, microsecond=0)
            agg = buckets.setdefault((start, r.capability), [0, 0])
            agg[0] += 1
            agg[1] += r.tokens
        return [
            UsageBucket(bucket_start=start, capability=capability, requests=n, tokens=tok)
            for (start, capability), (n, tok) in sorted(buckets.items())
        ]


class FakeJobs:
    def __init__(self) -> None:
        self.rows: dict[str, JobStatus] = {}
        self.history: list[JobStatus] = []

    async def set(self, status: JobStatus, ttl_seconds: int) -> None:
        self.rows[status.job_id] = status
        # Kept so a test can assert the sequence of states, which is what a
        # progress bar actually consumes.
        self.history.append(status)

    async def get(self, job_id: str) -> JobStatus | None:
        return self.rows.get(job_id)


class FakeRuntime:
    """Enough of `ModelRuntimePort` for the registry use cases.

    `pull` is an async generator and `validate_ref` is synchronous, matching
    the port exactly: the distinction is the kind of thing that is silent
    until it breaks at runtime.
    """

    def __init__(
        self,
        *,
        pull_updates: Sequence[PullProgress] = (),
        fail_on: str | None = None,
        invalid_refs: frozenset[str] = frozenset(),
    ) -> None:
        self.loaded: list[str] = []
        self.unloaded: list[str] = []
        self.pull_closed = False
        self._updates = pull_updates
        self._fail_on = fail_on
        self._invalid = invalid_refs

    def validate_ref(self, ref: str) -> None:
        if ref in self._invalid:
            raise InvalidModelReferenceError(detail=f"rejected {ref}")

    async def load(self, ref: str) -> None:
        if self._fail_on == "load":
            raise RuntimeError("runtime refused the load")
        self.loaded.append(ref)

    async def unload(self, ref: str) -> None:
        if self._fail_on == "unload":
            raise RuntimeError("runtime refused the unload")
        self.unloaded.append(ref)

    async def pull(self, ref: str) -> AsyncIterator[PullProgress]:
        try:
            for update in self._updates:
                yield update
            if self._fail_on == "pull":
                raise RuntimeError("the registry hung up")
        finally:
            self.pull_closed = True

    async def health(self) -> bool:
        return True


class FakeKnowledge:
    """In-memory stand-in for `KnowledgeRepositoryPort`.

    It has **no tenant filter**, deliberately, and that is why the isolation
    property is pinned by an integration test against real Postgres instead: a
    fake with no filter cannot prove a filter works. What these fakes are for is
    the use case's own logic, which is the ordering of storage against the row
    and the state refusals.
    """

    def __init__(self, collections=(), documents=()) -> None:
        self.collections = {c.id: c for c in collections}
        self.documents = {d.id: d for d in documents}

    async def get_collection(self, collection_id):
        collection = self.collections.get(collection_id)
        if collection is None:
            return None
        count = sum(1 for d in self.documents.values() if d.collection_id == collection_id)
        return replace(collection, document_count=count)

    async def get_collection_by_name(self, name):
        return next((c for c in self.collections.values() if c.name == name), None)

    async def list_collections(self):
        return sorted(self.collections.values(), key=lambda c: c.name)

    async def save_collection(self, collection) -> None:
        self.collections[collection.id] = collection

    async def delete_collection(self, collection_id) -> None:
        self.collections.pop(collection_id, None)

    async def get_document(self, document_id):
        return self.documents.get(document_id)

    async def list_documents(self, *, collection_id=None, limit, offset):
        found = [
            d
            for d in self.documents.values()
            if collection_id is None or d.collection_id == collection_id
        ]
        return found[offset : offset + limit]

    async def count_documents(self, *, collection_id=None):
        return len(
            [
                d
                for d in self.documents.values()
                if collection_id is None or d.collection_id == collection_id
            ]
        )

    async def save_document(self, document) -> None:
        self.documents[document.id] = document

    async def set_document_status(self, document_id, status, *, chunk_count=None, error=None):
        document = self.documents[document_id]
        self.documents[document_id] = replace(
            document,
            status=status,
            error=error,
            chunk_count=chunk_count if chunk_count is not None else document.chunk_count,
        )

    async def delete_document(self, document_id) -> None:
        self.documents.pop(document_id, None)

    async def reconcile_transient_documents(self, error: str) -> int:
        moved = 0
        for key, document in list(self.documents.items()):
            if document.is_transient:
                self.documents[key] = replace(document, status=DocumentStatus.ERROR, error=error)
                moved += 1
        return moved


class FakeDocumentStorage:
    """`DocumentStoragePort` over two dicts.

    `fail_on_put` exists for the one ordering the use case promises: the bytes
    reach storage before any row claims the document exists.
    """

    def __init__(self, *, fail_on_put: bool = False) -> None:
        self.originals: dict[str, bytes] = {}
        self.texts: dict[str, str] = {}
        self.deleted: list[str] = []
        self._fail_on_put = fail_on_put

    async def put_original(self, document_id: str, data: bytes) -> None:
        if self._fail_on_put:
            raise OSError("no space left on device")
        self.originals[document_id] = data

    async def put_text(self, document_id: str, text: str) -> None:
        self.texts[document_id] = text

    async def read_original(self, document_id: str) -> bytes:
        return self.originals[document_id]

    async def read_text(self, document_id: str) -> str:
        return self.texts[document_id]

    async def delete(self, document_id: str) -> None:
        self.deleted.append(document_id)
        self.originals.pop(document_id, None)
        self.texts.pop(document_id, None)


class FakeParser:
    def __init__(self, text: str = "extracted text", *, raises: Exception | None = None) -> None:
        self.text = text
        self._raises = raises
        self.calls: list[tuple[str, int]] = []

    async def extract_text(self, *, media_type: str, data: bytes) -> str:
        self.calls.append((media_type, len(data)))
        if self._raises is not None:
            raise self._raises
        return self.text


class FakeDocumentState:
    """`DocumentStateCommitterPort` backed by a `FakeKnowledge`, so a test can
    watch the row move through the ingestion states as the task writes them."""

    def __init__(self, knowledge: FakeKnowledge) -> None:
        self._knowledge = knowledge
        self.states: list[str] = []

    async def get(self, document_id: str):
        return await self._knowledge.get_document(document_id)

    async def commit(self, document_id, status, *, chunk_count=None, error=None) -> None:
        self.states.append(status.value)
        await self._knowledge.set_document_status(
            document_id, status, chunk_count=chunk_count, error=error
        )
