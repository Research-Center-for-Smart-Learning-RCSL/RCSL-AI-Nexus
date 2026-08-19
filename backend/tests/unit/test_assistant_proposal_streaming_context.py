from __future__ import annotations

from collections.abc import AsyncIterator

from app.domain.entities.chat import CompletionChunk
from app.interfaces.http.assistant_proposal import (
    NO_PROPOSAL_CONTRACT,
    PROPOSAL_CLOSE,
    PROPOSAL_CONTRACT,
    PROPOSAL_OPEN,
    PROPOSAL_SURFACES,
)
from tests.unit.assistant_proposal_fixtures import (
    block,
    collector,
    drain,
    valid_payload,
)

pytest_plugins = ("tests.unit.assistant_proposal_fixtures",)


def test_the_contract_describes_the_markers_the_reader_searches_for() -> None:
    """The prompt half and the parser half are one agreement. If they drift the
    symptom is silent: a proposal that never appears, with nothing logged
    because nothing was ever found to reject."""
    assert PROPOSAL_OPEN in PROPOSAL_CONTRACT
    assert PROPOSAL_CLOSE in PROPOSAL_CONTRACT


async def test_the_holdback_is_released_before_the_terminal_chunk() -> None:
    """No content may follow the `finish_reason` frame.

    A client is right to stop reading at the terminal frame, so anything after
    it is written to nobody. Releasing the holdback in the flush *after* the
    loop meant every answer lost its last nine characters to any reader that
    did not opt into a trailer — including `readChatStream` without
    `onTrailer`. The same mistake is recorded against `RouteChatRequest` in
    docs/PROGRESS.md, 2026-07-27.
    """
    c = collector()

    async def generation() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="A narrow key is best here.")
        yield CompletionChunk(delta="", finish_reason="stop")

    seen: list[tuple[str, str | None]] = []
    async for chunk in c.wrap(generation()):
        seen.append((chunk.delta, chunk.finish_reason))

    assert "".join(delta for delta, _ in seen) == "A narrow key is best here."
    terminal = next(i for i, (_, reason) in enumerate(seen) if reason)
    assert all(not delta for delta, _ in seen[terminal + 1 :])


async def test_a_truncated_marker_at_the_end_is_not_shown_as_text() -> None:
    """The other half of releasing the holdback. Once the generation is over
    there is nothing left to disambiguate, but a tail that is a prefix of the
    marker is a block the model began and did not finish — dropping it beats
    printing `<propo` at the end of the answer."""
    c = collector()

    async def generation() -> AsyncIterator[CompletionChunk]:
        yield CompletionChunk(delta="Use a narrow key.<propo")
        yield CompletionChunk(delta="", finish_reason="length")

    visible = "".join([chunk.delta async for chunk in c.wrap(generation())])

    assert visible == "Use a narrow key."
    assert await c.trailer() is None


def test_the_proposal_format_is_withheld_where_no_form_exists() -> None:
    """A model cannot misuse a format it was never shown.

    Every field a proposal carries is an API key field, so off the two key forms
    the card has nowhere to land. `PROPOSAL_CONTRACT` already ends by saying to
    write no block when answering a question, and on 2026-08-07 a 7B model
    answering "how do I connect Codex" emitted one regardless — offering
    `name: "code"` against no form at all.

    Withholding beats instructing. Asserted as a property of the surface set
    rather than of one screen, so a surface added later has to be classified
    deliberately.
    """
    assert PROPOSAL_SURFACES == {"api_keys.create", "api_keys.edit"}
    assert PROPOSAL_OPEN not in NO_PROPOSAL_CONTRACT, (
        "the alternative must not spell the marker it exists to withhold"
    )
    assert NO_PROPOSAL_CONTRACT.strip(), (
        "an empty ending let the model fall back on a block seen earlier in the "
        "conversation; the replacement has to say what this screen wants instead"
    )


async def test_a_default_outside_the_capabilities_beside_it_is_not_offered() -> None:
    """`_within_policy` exists so the operator is never handed a card that
    errors the moment they apply it and submit. `ManageApiKeys` refuses this
    pair with a 409, which is exactly that class of rule."""
    c = collector()

    await drain(
        c,
        [
            block(
                valid_payload(
                    fields={"scopes": ["chat"], "default_capability": "code"},
                )
            )
        ],
    )

    assert await c.trailer() is None


async def test_a_default_among_them_is_offered() -> None:
    c = collector()

    await drain(
        c,
        [
            block(
                valid_payload(
                    fields={"scopes": ["chat", "code"], "default_capability": "code"},
                )
            )
        ],
    )

    trailer = await c.trailer()
    assert trailer is not None
    assert trailer["proposal"]["fields"]["default_capability"] == "code"


async def test_a_default_with_no_capabilities_beside_it_is_left_to_the_form() -> None:
    """Nothing here knows the key's stored capability list, so this proposal
    cannot be decided against it. Refusing every such card would drop advice
    that is usually right; the form validates it against the values the
    operator is looking at and puts the message on the field."""
    c = collector()

    await drain(
        c,
        [block(valid_payload(action="update", key_id="k1", fields={"default_capability": "chat"}))],
    )

    assert await c.trailer() is not None


async def test_clearing_the_default_travels_as_null() -> None:
    """`null` is a value on this field rather than an omission, and the card
    that says "stop substituting" is the one it has to be able to carry."""
    c = collector()

    await drain(
        c,
        [block(valid_payload(action="update", key_id="k1", fields={"default_capability": None}))],
    )

    trailer = await c.trailer()
    assert trailer is not None
    assert trailer["proposal"]["fields"]["default_capability"] is None
