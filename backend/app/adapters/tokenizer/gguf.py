"""Reading a GGUF file's metadata header, and nothing else.

A GGUF file is a header of key/value metadata followed by tensor data. The
vocabulary a model tokenises with lives in that header, which is the first few
megabytes of a file that is tens of gigabytes: `qwen3.6:35b-a3b-q8_0` carries
11.9 MiB of metadata in front of 38.7 GB of weights, and reading it takes 0.13
seconds. Nothing here ever touches a tensor.

**Why the weights file and not the runtime.** Ollama will hand the same
vocabulary out over `/api/show` with `verbose: true`, and that was the shorter
road. It was not taken, because the identity this platform has to bind a
vocabulary to is the registry's `ref`, and the two roads differ in what happens
when that binding is wrong: a manifest lookup that resolves to the wrong blob
fails to open a file, while an HTTP call that resolves to the wrong model
returns a plausible vocabulary and a silently wrong count. This repository has
now recorded that failure twice — a calibration table describing a retired
model, and a throughput figure describing another — and both were invisible
precisely because the wrong answer looked like an answer.

The format is little-endian throughout and versioned; version 3 is what every
file this platform has met carries. An unknown version is refused rather than
guessed at, because the guess would be a vocabulary.

Specification: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"GGUF"
SUPPORTED_VERSIONS = frozenset({2, 3})

_SCALAR = {
    0: ("<B", 1),  # uint8
    1: ("<b", 1),  # int8
    2: ("<H", 2),  # uint16
    3: ("<h", 2),  # int16
    4: ("<I", 4),  # uint32
    5: ("<i", 4),  # int32
    6: ("<f", 4),  # float32
    7: ("<?", 1),  # bool
    10: ("<Q", 8),  # uint64
    11: ("<q", 8),  # int64
    12: ("<d", 8),  # float64
}
_STRING = 8
_ARRAY = 9

MAX_KV_COUNT = 4096
MAX_STRING_BYTES = 8 * 1024 * 1024
MAX_ARRAY_LENGTH = 8_000_000
"""Bounds on what a well-formed header can declare, applied before allocating.

Not validation for its own sake. Every one of these lengths is read from the
file and then used to size a read, so a truncated or corrupt blob otherwise
asks this process for an arbitrary allocation — and the file being parsed is
tens of gigabytes on a host whose free memory is the constraint the whole
deployment is designed around. The values sit an order of magnitude above the
largest real header measured here: 57 keys, a 248320-entry vocabulary, and a
13 KiB chat template.
"""


class GgufError(Exception):
    """The file is not a GGUF header this reader can parse.

    One exception for every malformation, because every caller does the same
    thing with it: fall back to counting characters and say so in a log line.
    A file that cannot be read is not a different outcome from a file that is
    not a GGUF at all.
    """


class _Reader:
    """Sequential reads over the header, with every length checked first."""

    def __init__(self, handle: BinaryIO) -> None:
        self._handle = handle

    def raw(self, count: int) -> bytes:
        data = self._handle.read(count)
        if len(data) != count:
            raise GgufError(f"header ends after {len(data)} of {count} expected bytes")
        return data

    def skip(self, count: int) -> None:
        self._handle.seek(count, 1)

    def scalar(self, type_id: int) -> Any:
        fmt, size = _SCALAR[type_id]
        return struct.unpack(fmt, self.raw(size))[0]

    def length(self, limit: int, what: str) -> int:
        value = struct.unpack("<Q", self.raw(8))[0]
        if value > limit:
            raise GgufError(f"{what} declares {value}, above the {limit} this reader accepts")
        return int(value)

    def string(self) -> str:
        size = self.length(MAX_STRING_BYTES, "string")
        # `replace` rather than `strict`: a vocabulary entry is a byte sequence
        # that need not be valid UTF-8 on its own, and refusing the whole file
        # over one such entry would cost the exact counting this exists for.
        return self.raw(size).decode("utf-8", "replace")

    def skip_string(self) -> None:
        self.skip(self.length(MAX_STRING_BYTES, "string"))

    def _assert_scalar(self, type_id: int, what: str) -> None:
        """Refuse a type this reader has no size for, as a `GgufError`.

        One method rather than a guard at each of the four sites, because the
        four had drifted: the two array branches indexed `_SCALAR` *before*
        checking membership, so a corrupt element type left as a bare
        `KeyError`. Nothing above catches that — `_build` catches `GgufError`
        and `OSError` — so it escaped the counter, escaped the use case, and
        became a 500 on every request routed to that model, re-reading the
        header each time because a failure that raises caches nothing.

        A nested array gets the same treatment: it is a shape the format
        permits and this reader does not, which is still "cannot read this
        file" rather than a different kind of outcome.
        """
        if type_id == _ARRAY:
            raise GgufError("nested arrays are not part of the format this reader accepts")
        if type_id not in _SCALAR:
            raise GgufError(f"unknown {what} type {type_id}")

    def value(self, type_id: int) -> Any:
        if type_id == _STRING:
            return self.string()
        if type_id == _ARRAY:
            element_type = self.scalar(4)
            count = self.length(MAX_ARRAY_LENGTH, "array")
            if element_type == _STRING:
                return [self.string() for _ in range(count)]
            self._assert_scalar(element_type, "array element")
            fmt, size = _SCALAR[element_type]
            return list(struct.unpack(f"<{fmt[1] * count}", self.raw(size * count)))
        self._assert_scalar(type_id, "metadata value")
        return self.scalar(type_id)

    def skip_value(self, type_id: int) -> None:
        """Walk past a value without building it.

        The saving is the point of having this at all: the two arrays a
        vocabulary does *not* need — `tokenizer.ggml.scores` and
        `tokenizer.ggml.token_type` — are 248320 entries each on the model
        serving `code`, and materialising them as Python lists costs more
        memory than the tokeniser they would have been discarded for.
        """
        if type_id == _STRING:
            self.skip_string()
            return
        if type_id == _ARRAY:
            element_type = self.scalar(4)
            count = self.length(MAX_ARRAY_LENGTH, "array")
            if element_type == _STRING:
                for _ in range(count):
                    self.skip_string()
                return
            self._assert_scalar(element_type, "array element")
            _, size = _SCALAR[element_type]
            self.skip(size * count)
            return
        self._assert_scalar(type_id, "metadata value")
        _, size = _SCALAR[type_id]
        self.skip(size)


def read_metadata(path: Path, wanted: Callable[[str], bool]) -> dict[str, Any]:
    """The header's key/value pairs, keeping only the keys `wanted` accepts.

    A predicate rather than a set of names, because the caller wants a prefix
    (`tokenizer.`) and one exact key, and because what is skipped matters as
    much as what is kept: see `_Reader.skip_value`.

    Raises `GgufError` for anything malformed, including a file that is not a
    GGUF. Callers treat that identically to the file being absent.
    """
    with path.open("rb") as handle:
        reader = _Reader(handle)
        if reader.raw(4) != MAGIC:
            raise GgufError(f"{path.name} does not begin with the GGUF magic")
        version = reader.scalar(4)
        if version not in SUPPORTED_VERSIONS:
            raise GgufError(f"GGUF version {version} is not one this reader has been checked on")
        reader.length(2**32, "tensor count")
        pairs = reader.length(MAX_KV_COUNT, "metadata pair count")
        found: dict[str, Any] = {}
        for _ in range(pairs):
            key = reader.string()
            type_id = reader.scalar(4)
            if wanted(key):
                found[key] = reader.value(type_id)
            else:
                reader.skip_value(type_id)
        return found


def iter_merges(raw: list[str]) -> Iterator[tuple[str, str]]:
    """`tokenizer.ggml.merges` holds each pair as one space-separated string.

    Split on the *first* space only. A merge whose left half is the byte-level
    spelling of a space is written `"Ġ Ġ"`, and splitting on every space turns
    the commonest merge in the file into a three-part row that the tokeniser
    would then not have.
    """
    for entry in raw:
        left, separator, right = entry.partition(" ")
        if not separator:
            raise GgufError(f"merge entry has no pair separator: {entry!r}")
        yield left, right
