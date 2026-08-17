"""Finding the weights file Ollama will serve a reference from.

Ollama stores models the way a container registry does: a manifest per
`namespace/name:tag`, listing content-addressed layers that live under
`blobs/`. The layer whose media type is `application/vnd.ollama.image.model`
is the GGUF this reference resolves to.

**This is the binding.** `ManageModels` stores a `ref`, routing selects a model
by that `ref`, and the adapter sends that `ref` to the runtime; resolving the
same string through the same manifest tree is what makes a vocabulary describe
the model that will actually answer. Nothing is vendored, nothing is pinned by
hand, and a reference that names a model this host does not hold resolves to a
missing file rather than to somebody else's vocabulary — which is the failure
mode the roadmap item refused to accept, because it is unmeasurable.

The tree is mounted read-only (`/ollama-models` in the Compose file). Ollama
writes it; this platform only ever reads it, and never inside a request that
holds a concurrency slot.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.runtime.validation import parse_model_ref

MODEL_MEDIA_TYPE = "application/vnd.ollama.image.model"
DEFAULT_REGISTRY = "registry.ollama.ai"
DEFAULT_NAMESPACE = "library"
DEFAULT_TAG = "latest"
MAX_MANIFEST_BYTES = 1024 * 1024


class BlobNotFound(Exception):
    """No weights file could be resolved for this reference on this host.

    Raised for a missing mount, a missing manifest, a manifest with no model
    layer, and a digest whose blob is absent — one exception for all four
    because the caller's answer to every one of them is the same: count
    characters instead, and log which reference it happened for.
    """


def manifest_path(root: Path, ref: str) -> Path:
    """Where Ollama keeps the manifest for `ref`, defaults filled in.

    `parse_model_ref` first, so a reference that reaches this function has
    already been through the grammar that keeps `..` and absolute paths out of
    it. That check exists for the runtime call and the download path; it earns
    its keep a third time here, where the reference becomes a filesystem path.
    """
    reference = parse_model_ref(ref)
    return (
        root
        / "manifests"
        / (reference.registry or DEFAULT_REGISTRY)
        / (reference.namespace or DEFAULT_NAMESPACE)
        / reference.name
        / (reference.tag or DEFAULT_TAG)
    )


def weights_path(root: Path, ref: str) -> Path:
    """The GGUF blob `ref` resolves to, or `BlobNotFound`."""
    manifest = manifest_path(root, ref)
    try:
        raw = manifest.read_bytes()
    except OSError as exc:
        raise BlobNotFound(f"no manifest for {ref} under {root}: {exc}") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BlobNotFound(f"manifest for {ref} is {len(raw)} bytes, which is not a manifest")
    try:
        document = json.loads(raw)
        layers = document["layers"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BlobNotFound(f"manifest for {ref} does not parse as one: {exc}") from exc

    for layer in layers:
        if isinstance(layer, dict) and layer.get("mediaType") == MODEL_MEDIA_TYPE:
            digest = str(layer.get("digest", ""))
            # `sha256:abc…` names the file `sha256-abc…`. Split rather than
            # replaced: a digest carrying a path separator would otherwise
            # reach `Path` intact, and this is a value read from a file on a
            # mount another process writes.
            algorithm, separator, hexadecimal = digest.partition(":")
            if not separator or not hexadecimal.isalnum() or not algorithm.isalnum():
                raise BlobNotFound(f"model layer for {ref} carries no usable digest: {digest!r}")
            blob = root / "blobs" / f"{algorithm}-{hexadecimal}"
            if not blob.is_file():
                raise BlobNotFound(f"{ref} resolves to {blob.name}, which is not on this host")
            return blob
    raise BlobNotFound(f"manifest for {ref} lists no {MODEL_MEDIA_TYPE} layer")
