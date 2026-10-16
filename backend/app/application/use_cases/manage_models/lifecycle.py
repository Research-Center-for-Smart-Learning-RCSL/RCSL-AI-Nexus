"""Model load/unload lifecycle and tokenizer preparation."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.model import Model, ModelState
from app.domain.exceptions import (
    ModelStateConflictError,
)
from app.domain.ports.model_runtime_port import declared_context_for

from .registry import ModelRegistryMixin
from .state import _with_state

logger = logging.getLogger("app.application.use_cases.manage_models")


class ModelLifecycleMixin(ModelRegistryMixin):
    async def load(self, actor: Actor, model_id: str) -> Model:
        """Refused when the node's memory budget would be exceeded.

        A refusal rather than a warning: on unified memory an over-commit does
        not fail cleanly, it drives the machine into swap and takes every other
        model down with it.
        """
        self._authz.require(actor, Scope.MODEL_WRITE)
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
        self._budget.assert_can_load(
            model,
            node,
            await self._models.list_occupying_memory(node.id),
            live_free_gb=live_free_gb,
        )

        # Committed in its own transaction, not the request's. The request's
        # write would be invisible to a concurrent load until it commits at the
        # end — which is after the runtime call — so the claim has to land now.
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
        self._authz.require(actor, Scope.MODEL_WRITE)
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
