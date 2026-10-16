"""Long grounded histories fit the HTTP header budget without losing context."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from starlette.responses import StreamingResponse

from app.domain.entities.chat import Message, MessageRole
from app.interfaces.http import sse
from app.interfaces.http.sse import encoding
from tests.unit.test_grounding_replay import ACTOR, Search, conversation, passage, setup


def document(number: int) -> str:
    return f"00000000-0000-0000-0000-{number:012d}"


def test_empty_citations_have_no_headers() -> None:
    assert sse.citation_header([]) == {}


def test_short_header_keeps_order_and_distinct_passages() -> None:
    citations = [(document(0), 0), (document(0), 1), (document(1), 0)]
    assert sse.citation_header(citations) == {
        sse.CITATION_HEADER: ",".join(f"{doc}:{index}" for doc, index in citations)
    }


def test_duplicates_keep_the_latest_occurrence_without_claiming_truncation() -> None:
    first, second = (document(0), 0), (document(1), 0)
    assert sse.citation_header([first, second, first]) == {
        sse.CITATION_HEADER: f"{document(1)}:0,{document(0)}:0"
    }


def test_exact_byte_boundary_includes_separator_and_signals_omission(monkeypatch) -> None:
    # Two UUID:0 entries plus a comma are exactly 77 bytes.
    monkeypatch.setattr(encoding, "MAX_CITATION_HEADER_BYTES", 77)
    citations = [(document(i), 0) for i in range(3)]
    assert sse.citation_header(citations[1:]) == {
        sse.CITATION_HEADER: f"{document(1)}:0,{document(2)}:0"
    }
    assert sse.citation_header(citations) == {
        sse.CITATION_HEADER: f"{document(1)}:0,{document(2)}:0",
        sse.CITATION_TRUNCATED_HEADER: "true",
    }


def test_an_oversized_entry_does_not_hide_other_citations() -> None:
    headers = sse.citation_header([(document(0), 0), ("x" * 2048, 0)])
    assert headers == {
        sse.CITATION_HEADER: f"{document(0)}:0",
        sse.CITATION_TRUNCATED_HEADER: "true",
    }


@pytest.mark.parametrize("distinct_each_turn", [False, True])
async def test_45_grounded_turns_keep_full_context_and_bounded_headers(distinct_each_turn) -> None:
    grounding, search, cache, _ = setup(Search())
    messages = conversation()
    for turn in range(45):
        search.passages = [
            replace(
                passage("short reference passage"),
                document_id=document(turn * 5 + i if distinct_each_turn else i),
                index=i,
            )
            for i in range(5)
        ]
        grounded, citations = await grounding.execute(ACTOR, messages)
        messages += [
            Message(MessageRole.ASSISTANT, "Answer"),
            Message(MessageRole.USER, f"Follow-up {turn}"),
        ]

    assert len(citations) == 225
    assert sum(message.role is MessageRole.SYSTEM for message in grounded) == 46
    chain = json.loads(list(cache._values.values())[-1][0])
    assert len(chain["anchors"]) == 45
    assert sum(len(anchor["citations"]) for anchor in chain["anchors"]) == 225

    headers = sse.citation_header([(p.document_id, p.index) for p in citations])
    value = headers[sse.CITATION_HEADER]
    assert len(value.encode()) <= 2048
    assert len(value.split(",")) == len(set(value.split(",")))
    if distinct_each_turn:
        assert headers[sse.CITATION_TRUNCATED_HEADER] == "true"
        assert f"{document(224)}:4" in value
        assert f"{document(0)}:0" not in value
    else:
        assert len(value.split(",")) == 5
        assert sse.CITATION_TRUNCATED_HEADER not in headers

    # Actual Starlette header encoding, including ordinary SSE headers, stays
    # below the smallest buffer in the documented nginx proxy configuration.
    response = StreamingResponse(iter([]), headers={**sse.STREAM_HEADERS, **headers})
    assert sum(len(name) + len(value) + 4 for name, value in response.raw_headers) < 4096
