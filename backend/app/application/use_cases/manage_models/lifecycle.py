"""Model load/unload lifecycle and tokenizer preparation."""

from __future__ import annotations

import logging

from app.domain.entities.actor import Actor, Scope
from app.domain.entities.audit import AuditAction
from app.domain.entities.model import Model, ModelState
from app.domain.exceptions import (
    ModelStateConflictError,
)

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
            return model
        if effective is not ModelState.DOWNLOADED:
            raise ModelStateConflictError(
                detail=f"model {model.id} is {effective}; it must be downloaded first"
            )

        node = await self._require_node(model.node_id)
        runtime = await self._require_runtime(model.runtime)

        # Counts LOADING as well as LOADED, because a model mid-load already
        # holds (or is about to hold) its memory. LOADING is then committed
        # independently below, so a second load started moments later sees it
        # in this same count rather than a budget that ignores it.
        self._budget.assert_can_load(model, node, await self._models.list_occupying_memory(node.id))

        # Committed in its own transaction, not the request's. The request's
        # write would be invisible to a concurrent load until it commits at the
        # end — which is after the runtime call — so the claim has to land now.
        await self._state.commit(model.id, ModelState.LOADING)
        # Before the load and not after it, unlike `_prepare_token_counter`
        # below, because the figure this warns about is the one about to be
        # sent: a warning that arrives after an oversized `num_ctx` has already
        # made the runtime reserve for a context the model cannot hold is a
        # warning about something the operator can no longer choose against.
        await self._warn_if_registered_context_overstates(model)
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
        await self._audit.record(actor, AuditAction.MODEL_LOADED, target=model.id)
        await self._prepare_token_counter(model)
        return _with_state(model, ModelState.LOADED)

    async def _warn_if_registered_context_overstates(self, model: Model) -> None:
        """Say so when a registration claims more context than the model has.

        The registered figure is a claim an operator typed. The model's own
        header is the fact, and until 2026-09-07 nothing compared them — so
        `qwen7b` sat registered at 262144 against a declared 32768 for as long
        as it took somebody to read `/api/ps` beside the `models` table.

        Both consequences are silent, which is why this is a warning rather
        than a note. `_refuse_what_this_target_would_truncate` refuses at half
        the *registered* figure, so an overstatement holds that guard open by
        the same factor — for `qwen7b` it refused at 131072 against a model
        that cuts anything over 32768 down to 16384, reopening precisely what
        that guard was added on 2026-08-17 to close. And the figure is sent to
        the runtime as `num_ctx`, so the load reserves for a context that
        cannot be used, which is the shape of the 2026-08-07 eviction.

        **Registering below the declared maximum is not warned about**, because
        it is the ordinary deliberate choice: four of this deployment's six
        rows do it, to bound memory or to keep a model inside the platform's
        ceiling. Only the direction that overstates is a defect.

        Warning rather than refusing, and that is a decision rather than
        timidity. A refusal here would make a wrong number in a table unable to
        serve at all, on the strength of a file read that can fail for reasons
        having nothing to do with the number — a missing mount, an unpulled
        reference, an architecture whose header spells the key differently.
        The load is the operator's; this makes sure they are told.

        Swallows everything, for the reason `_prepare_token_counter` does: a
        header that cannot be read must never be what stops a model loading.
        """
        if self._tokens is None:
            return
        registered = model.resource_profile.context_length
        if registered <= 0:
            # A row from before the profile was required. `_set_num_ctx`
            # declines to send it and this declines to judge against it.
            return
        try:
            declared = await self._tokens.native_context_length(model.ref)
        except Exception:  # noqa: BLE001
            logger.exception("failed to read the declared context for %s", model.ref)
            return
        if declared is None or registered <= declared:
            return
        logger.warning(
            "%s is registered with context_length=%d but %s declares %d. The runtime will "
            "silently truncate anything above %d, and the per-model guard refuses at %d "
            "rather than %d, so prompts between those figures are served from a prompt the "
            "model never fully read. Correct the registration to %d.",
            model.alias,
            registered,
            model.ref,
            declared,
            declared,
            registered // 2,
            declared // 2,
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

        runtime = await self._require_runtime(model.runtime)
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
