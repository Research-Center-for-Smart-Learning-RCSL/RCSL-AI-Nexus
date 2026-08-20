from __future__ import annotations

pytest_plugins = ("tests.unit.error_precision_fixtures",)


def test_each_conflict_names_the_thing_the_operator_was_editing() -> None:
    """Until 2026-08-17 every 409 on the admin surface said "the model".

    `ModelStateConflictError` was the platform's general conflict: 34 raises
    across eleven modules, eleven of them about models. The UI renders
    `public_message` verbatim, so an operator editing an API key was told about
    models while the reason sat in `detail`, which does not leave the process.
    """
    from app.domain.exceptions import (
        ApiKeyStateConflictError,
        CollectionStateConflictError,
        NodeStateConflictError,
        PromptTemplateStateConflictError,
        RoutingPolicyStateConflictError,
        StateConflictError,
        TenantStateConflictError,
        UserStateConflictError,
    )

    for error, noun in (
        (ApiKeyStateConflictError(), "key"),
        (PromptTemplateStateConflictError(), "template"),
        (RoutingPolicyStateConflictError(), "routing policy"),
        (NodeStateConflictError(), "node"),
        (TenantStateConflictError(), "tenant"),
        (UserStateConflictError(), "account"),
        (CollectionStateConflictError(), "collection"),
    ):
        assert noun in error.public_message
        assert "model" not in error.public_message
        assert isinstance(error, StateConflictError)


def test_every_conflict_subject_still_answers_409() -> None:
    """The status is on the base and `_status_for` walks the MRO, so a subject
    added later is a 409 without anybody remembering to map it."""
    from app.domain.exceptions import (
        ApiKeyLifetimeError,
        DebugWindowError,
        ModelStateConflictError,
        NodeStateConflictError,
        StateConflictError,
    )
    from app.interfaces.http.errors import _status_for

    for error in (
        StateConflictError(),
        ModelStateConflictError(),
        NodeStateConflictError(),
        DebugWindowError(),
        ApiKeyLifetimeError(365),
    ):
        assert _status_for(error) == 409


def test_the_key_lifetime_refusal_names_the_number_it_is_holding_you_to() -> None:
    """Seven attempts in three minutes on 2026-08-17, each answered with a
    message about models, the 365 in `detail`. The date the caller typed is
    their own input described back to them, which is the test the `413`
    composition already passes."""
    from app.domain.exceptions import ApiKeyLifetimeError

    error = ApiKeyLifetimeError(365, detail="expiry 2029-11-15 is beyond the 365 day maximum")

    assert "365 days" in error.public_message
    assert "2029-11-15" not in error.public_message  # the operator detail stays behind
    assert error.maximum_days == 365
