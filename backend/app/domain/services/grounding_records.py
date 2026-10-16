"""Canonical, server-keyed identities and bounded rendered anchor chains."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass

from app.domain.entities.chat import Message, MessageRole
from app.domain.entities.knowledge import RetrievedPassage

MAX_GROUNDING_RECORD_BYTES = 256 * 1024
MAX_GROUNDING_LOOKBACK = 256
MAX_GROUNDING_RECORDS_PER_TENANT = 64
MAX_GROUNDING_RECORDS_TOTAL = 256
GROUNDING_RECORD_TTL = 24 * 60 * 60
RETRIEVAL_CONFIG_VERSION = "grounding-v1:query2000:passage4000"


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def keyed_digest(secret: bytes, purpose: str, fields: object) -> str:
    return hmac.new(secret, canonical([purpose, fields]).encode(), hashlib.sha256).hexdigest()


def anchor_hash(messages: list[Message], index: int) -> str:
    return anchor_hashes(messages[: index + 1])[index]


def anchor_hashes(messages: list[Message]) -> dict[int, str]:
    """Hash prefixes in one pass, without quadratic re-serialization."""
    digest = hashlib.sha256(b"[")
    hashes = {}
    for index, message in enumerate(messages):
        if index:
            digest.update(b",")
        digest.update(canonical(asdict(message)).encode())
        if message.role is MessageRole.USER:
            prefix = digest.copy()
            prefix.update(b"]")
            hashes[index] = prefix.hexdigest()
    return hashes


@dataclass(frozen=True, slots=True)
class GroundingAnchor:
    prefix_hash: str
    index: int
    context: str
    citations: tuple[RetrievedPassage, ...]


def encode_chain(anchors: list[GroundingAnchor]) -> str:
    return canonical({"version": 1, "anchors": [asdict(a) for a in anchors]})


def decode_chain(raw: str, messages: list[Message]) -> list[GroundingAnchor]:
    if len(raw.encode()) > MAX_GROUNDING_RECORD_BYTES:
        return []
    try:
        data = json.loads(raw)
        if data["version"] != 1:
            return []
        anchors = []
        previous = -1
        hashes = anchor_hashes(messages)
        for item in data["anchors"]:
            index = item["index"]
            if (
                not isinstance(index, int)
                or index <= previous
                or index >= len(messages)
                or messages[index].role is not MessageRole.USER
                or item["prefix_hash"] != hashes[index]
                or not isinstance(item["context"], str)
            ):
                return []
            citations = tuple(RetrievedPassage(**p) for p in item["citations"])
            anchors.append(GroundingAnchor(item["prefix_hash"], index, item["context"], citations))
            previous = index
        return anchors
    except (KeyError, TypeError, ValueError):
        return []


def replay(
    messages: list[Message], anchors: list[GroundingAnchor]
) -> tuple[list[Message], list[RetrievedPassage]]:
    result = list(messages)
    citations: list[RetrievedPassage] = []
    for anchor in anchors:
        if anchor.context:
            result.insert(
                anchor.index + len(result) - len(messages),
                Message(MessageRole.SYSTEM, anchor.context),
            )
        citations.extend(anchor.citations)
    return result, citations
