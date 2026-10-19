"""Model load/unload lifecycle and tokenizer preparation."""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager, nullcontext
from dataclasses import replace

from app.application.audit_subject import reconciler_subject
from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.model import Model, ModelState
from app.domain.exceptions import (
    ModelNotFoundError,
    ModelStateConflictError,
)
from app.domain.ports.model_runtime_port import declared_context_for
from app.domain.services.residency_reconciliation import charges_memory

from .registry import ModelRegistryMixin
from .state import _with_state

logger = logging.getLogger("app.application.use_cases.manage_models")


class ModelLifecycleMixin(ModelRegistryMixin):
    async def load(self, actor: Actor, model_id: str) -> Model:
        """Refused when the node's memory budget would be exceeded.

        A refusal rather than a warning: on unified memory an over-commit does
        not fail cleanly, it drives the machine into swap and takes every other
        model down with it.

        An operator's load is also the wish to keep the model resident, so it
        records that intent (#49 §1), committed on its own once the checks
        have passed and before the runtime is called. A refused load (wrong
        state, over budget) leaves the intent as it was. A load the runtime
        then fails keeps it: the wish outlives one failed attempt, which is
        why intent lives apart from `state`, and the reconciler, when enabled,
        retries it within its backoff (#49 §2, step 5).
        """
        self._authz.require(actor, Scope.MODEL_WRITE)
        model = await self._require(model_id)
        # The reconciler's per-node lock, so this load and a restore (or a
        # second operator's load) never both read the occupying set before
        # either has committed LOADING. Tried, never waited for, and taken on
        # its own idle connection: nothing below needs it again. The
        # reconciler's `restore` runs under the lock its pass already holds.
        async with self._hold_node(model.node_id) as held:
            if not held:
                raise ModelStateConflictError(
                    detail=f"another load is in progress on node {model.node_id}; retry shortly"
                )
            return await self._load(actor, model_id, record_intent=True)

    def _hold_node(self, node_id: str) -> AbstractAsyncContextManager[bool]:
        if self._node_lock is None:
            return nullcontext(True)
        return self._node_lock.hold(node_id)

    async def restore(self, model_id: str) -> Model:
        """The residency reconciler's load: the same checks, budget and
        runtime path as an operator's, under the reconciler's audit subject.
        The caller already holds the node's lock for its pass; taking it
        again here, on another connection, would refuse its own holder.

        Unrouted and unscoped, and it never writes intent: a load already in
        flight must not restore a flag the operator has since withdrawn
        (#49 §3). The reconciler re-reads the intent once this returns.
        """
        return await self._load(reconciler_subject(), model_id)

    async def release(self, model_id: str) -> Model:
        """Unload weights the reconciler restored after their intent was
        withdrawn. Like `restore`, it leaves the intent alone."""
        return await self._unload(reconciler_subject(), model_id)

    async def set_desired_residency(self, actor: Actor, model_id: str, desired: bool) -> Model:
        """Change residency intent without touching the runtime (#49 §3).

        This is the cancellation that does not depend on residency: after a
        runtime restart the model is observed `downloaded`, which `unload`
        refuses, yet the operator must still be able to stop it coming back.
        It commits a new intent version and returns at once; the outcome is
        `accepted`, not done. A restore already in flight is not interrupted,
        but the reconciler re-reads the intent when it returns and unloads the
        weights it just made resident, audited as its own `model.unloaded`.
        Withdrawing intent never unloads a model that is resident now; that is
        what `unload` is for.
        """
        self._authz.require(actor, Scope.MODEL_WRITE)
        await self._require(model_id)
        version = await self._models.set_desired_residency(model_id, desired)
        if version is None:
            raise ModelNotFoundError(detail=f"model {model_id} not found")
        await self._audit.record(
            actor,
            AuditAction.MODEL_RESIDENCY_INTENT_CHANGED,
            target=model_id,
            outcome="accepted",
            detail={"desired_resident": str(desired).lower(), "desired_version": str(version)},
        )
        return await self._require(model_id)

    async def _load(self, actor: Actor, model_id: str, *, record_intent: bool = False) -> Model:
        """Every write to this model's row before the runtime call goes
        through `self._state`, its own transaction. A write through the
        request session would hold the row lock until the request commits,
        and the next independent write to the same row would wait on it for
        ever: the request is waiting for that write to return.
        """
        model = await self._require(model_id)

        node = await self._require_node(model.node_id)
        runtime = self._runtime_on(node, model.runtime)
        declared = await declared_context_for(
            runtime, model.ref, self._tokens, manifest=model.manifest_digest
        )
        model = replace(model, capacity_validated=declared is not None)

        # The observation outranks the intent, the same rule and for the same
        # reason as `RoutingService._satisfies`. Deciding on `state` alone made
        # this method a no-op in exactly the case it exists for: a runtime that
        # has evicted a model the registry still records as LOADED returns 200
        # and `state=loaded` here without the runtime being called at all, so
        # the operator's only recovery action silently does nothing. Observed
        # on 2026-08-07, when Ollama evicted two models to fit a third and
        # pressing Load produced no request in its log.
        effective = model.observed_state or model.state
        if effective is ModelState.LOADED:
            if record_intent:
                await self._commit_intent(model.id, True)
            await self._models.set_capacity_validated(model, model.capacity_validated)
            return await self._require(model.id)
        if effective is not ModelState.DOWNLOADED:
            raise ModelStateConflictError(
                detail=f"model {model.id} is {effective}; it must be downloaded first"
            )

        live_free_gb: float | None = None
        if self._metrics is not None:
            live_free_gb = await self._metrics.free_memory_gb(node.id)
            if live_free_gb is not None:
                logger.info(
                    "live_free_memory node=%s free_gb=%.2f",
                    node.id,
                    live_free_gb,
                )

        # Counts LOADING as well as LOADED, because a model mid-load already
        # holds (or is about to hold) its memory. LOADING is then committed
        # independently below, so a second load started moments later sees it
        # in this same count rather than a budget that ignores it.
        occupying = await self._models.list_occupying_memory(node.id)
        if self._observed_absence_frees_memory:
            now = await self._observation_clock()
            occupying = [m for m in occupying if charges_memory(m, now)]
        self._budget.assert_can_load(model, node, occupying, live_free_gb=live_free_gb)

        # Committed in its own transaction, not the request's. The request's
        # write would be invisible to a concurrent load until it commits at the
        # end — which is after the runtime call — so the claim has to land now.
        if record_intent:
            await self._commit_intent(model.id, True)
        await self._state.commit(model.id, ModelState.LOADING)
        # Before the load and not after it, unlike `_prepare_token_counter`
        # below, because the figure this warns about is the one about to be
        # sent: a warning that arrives after an oversized `num_ctx` has already
        # made the runtime reserve for a context the model cannot hold is a
        # warning about something the operator can no longer choose against.
        self._warn_if_registered_context_overstates(model, declared)
        try:
            await runtime.load(model.ref, context_length=model.resource_profile.context_length)
        except Exception:
            # Independently, because the raise that follows rolls the request
            # transaction back. Writing ERROR through the request session lost
            # it exactly when it mattered: a half-resident model then read as
            # DOWNLOADED and the budget stopped counting its memory.
            await self._state.commit(model.id, ModelState.ERROR)
            await self._audit.record(
                actor, AuditAction.MODEL_LOADED, target=model.id, outcome="failed"
            )
            raise

        # The success transition may ride the request transaction: if that
        # commit fails the load did not durably happen and the state should
        # not claim it did. Reconciliation at the next deploy would move a
        # LOADING left by such a failure to ERROR.
        await self._models.set_state(model.id, ModelState.LOADED)
        await self._models.set_capacity_validated(model, model.capacity_validated)
        model = await self._require(model.id)
        await self._audit.record(actor, AuditAction.MODEL_LOADED, target=model.id)
        await self._prepare_token_counter(model)
        return model

    def _warn_if_registered_context_overstates(self, model: Model, declared: int | None) -> None:
        """Flag legacy registrations that exceed the selected model's declaration.

        New registrations and edits refuse this mismatch. Existing rows can
        still load; agent admission clamps to the declaration and metadata
        resolution remains separate from counting profile validation.
        """
        registered = model.resource_profile.context_length
        if registered <= 0:
            # A row from before the profile was required. `_set_num_ctx`
            # declines to send it and this declines to judge against it.
            return
        if declared is None or registered <= declared:
            return
        logger.warning(
            "%s is registered with context_length=%d but %s declares %d. "
            "Admission uses the smaller declared capacity. Correct the registration to %d.",
            model.alias,
            registered,
            model.ref,
            declared,
            declared,
        )

    async def _prepare_token_counter(self, model: Model) -> None:
        """Read this model's vocabulary now rather than on somebody's request.

        Two things are bought here and neither is the quarter of a second. The
        first is that the cost lands on the operator who pressed Load rather
        than on the first caller after it. The second is the log line: whether a
        model can be counted exactly is decided by files on the host, and
        without this an operator would find out weeks later, from a drift line
        about an estimate, that this model was never counted exactly at all.

        After the audit row, never before it. A failure to read a vocabulary
        must not be able to unwind a load that has already happened, so this
        sits past every write and swallows everything: the model is resident and
        serving whether or not it can be counted exactly.
        """
        if self._tokens is None:
            return
        try:
            prepared = await self._tokens.prepare(model.ref)
        except Exception:  # noqa: BLE001
            logger.exception("failed to read a vocabulary for %s", model.ref)
            return
        if not prepared:
            logger.info(
                "%s will be counted by the character estimate; no vocabulary was resolved "
                "for %s on this host",
                model.alias,
                model.ref,
            )

    async def unload(self, actor: Actor, model_id: str) -> Model:
        """Also withdraws residency intent, committed on its own once the
        unload is accepted and before the runtime is called. A refused unload
        (the model is not loaded) leaves the intent as it was; withdrawing it
        then is what `set_desired_residency` is for. A failed runtime unload
        keeps it withdrawn: the operator asked for the weights to go, and the
        reconciler must not bring them back on that failure."""
        self._authz.require(actor, Scope.MODEL_WRITE)
        await self._require(model_id)
        return await self._unload(actor, model_id, withdraw_intent=True)

    async def _commit_intent(self, model_id: str, desired: bool) -> None:
        if await self._state.commit_intent(model_id, desired) is None:
            raise ModelNotFoundError(detail=f"model {model_id} not found")

    async def _unload(self, actor: Actor, model_id: str, *, withdraw_intent: bool = False) -> Model:
        model = await self._require(model_id)

        # Observation over intent here too, and it is the mirror of the defect
        # in `load`: a model the runtime holds but the registry has recorded as
        # merely downloaded could not be evicted at all, which is the one case
        # where an operator most wants to. Ollama loads on demand, so the
        # registry can fall behind in this direction without anyone asking it to.
        effective = model.observed_state or model.state
        if effective is not ModelState.LOADED:
            raise ModelStateConflictError(detail=f"model {model.id} is {effective}, not loaded")

        runtime = self._runtime_on(await self._require_node(model.node_id), model.runtime)
        if withdraw_intent:
            await self._commit_intent(model.id, False)
        await self._state.commit(model.id, ModelState.UNLOADING)
        try:
            await runtime.unload(model.ref)
        except Exception:
            # Deliberately back to LOADED, not ERROR, and independently. The
            # unload failed, so as far as anyone knows the weights are still
            # resident and the memory budget must keep counting them.
            await self._state.commit(model.id, ModelState.LOADED)
            await self._audit.record(
                actor, AuditAction.MODEL_UNLOADED, target=model.id, outcome="failed"
            )
            raise

        await self._models.set_state(model.id, ModelState.DOWNLOADED)
        await self._audit.record(actor, AuditAction.MODEL_UNLOADED, target=model.id)
        return _with_state(model, ModelState.DOWNLOADED)
