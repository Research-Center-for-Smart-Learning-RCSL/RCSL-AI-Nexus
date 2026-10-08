"""Record the runtime's prompt token counts for the counter's agreement test.

Operator-run, never in CI: it sends one request per corpus text to each named
model, which loads the model if it is not resident. Run it in a window you own.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/record_prompt_counts.py \
        --models-root /Users/Shared/ollama/models --i-own-the-window \
        gemma4:31b-it-q8_0=262144 qwen2.5:7b=32768

Prints a `RECORDED_COUNTS` literal for `tests/unit/runtime_count_corpus.py`,
keyed by weights-blob digest so a re-pulled model cannot inherit counts that
were measured on different weights.

Every request carries `truncate: false`. The runtime then refuses a text that
does not fit (400) instead of returning the count of what it kept, and a
refusal aborts the recording rather than recording a partial count.

The store and the server are separate arguments and could name different
copies of a tag, so before measuring anything this checks that the server
serves the manifest the local store holds: the server reports a manifest's
digest in `/api/tags`, which is the SHA-256 of the manifest file. A mismatch
refuses rather than recording one model's counts under another's weights.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pprint
import sys
from pathlib import Path

import httpx

from app.adapters.tokenizer.ollama_blobs import manifest_path, weights_in_manifest
from tests.unit.runtime_count_corpus import CORPUS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="+", help="ref=num_ctx")
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--i-own-the-window", action="store_true")
    args = parser.parse_args()
    if not args.i_own_the_window:
        print(
            "refusing: this loads models on the runtime; pass --i-own-the-window", file=sys.stderr
        )
        return 2

    recorded: dict[str, dict[str, object]] = {}
    with httpx.Client(base_url=args.ollama, timeout=900) as client:
        version = client.get("/api/version").json()["version"]
        served = {m["name"]: m["digest"] for m in client.get("/api/tags").json()["models"]}
        for spec in args.models:
            ref, _, ctx = spec.partition("=")
            # One read: the blob is resolved from the bytes that were verified
            # against the server, not from a second read (review on #31).
            raw = manifest_path(args.models_root, ref).read_bytes()
            local_manifest = hashlib.sha256(raw).hexdigest()
            if served.get(ref) != local_manifest:
                print(
                    f"refusing: {ref} served as manifest {served.get(ref)} "
                    f"but the local store holds {local_manifest}",
                    file=sys.stderr,
                )
                return 1
            blob = weights_in_manifest(args.models_root, ref, raw)
            digest = blob.name.removeprefix("sha256-")[:12]
            counts: dict[str, int] = {}
            for name, text in CORPUS.items():
                response = client.post(
                    "/api/chat",
                    json={
                        "model": ref,
                        "messages": [{"role": "user", "content": text}],
                        "stream": False,
                        "think": False,
                        "keep_alive": -1,
                        # The runtime refuses a prompt that does not fit
                        # instead of counting only what it kept, so a count
                        # it returns is the whole text's (review on #25).
                        "truncate": False,
                        "options": {"num_ctx": int(ctx), "num_predict": 1},
                    },
                )
                if response.status_code == 400 and "exceed_context" in response.text:
                    print(f"refusing: {ref}/{name} does not fit num_ctx {ctx}", file=sys.stderr)
                    return 1
                response.raise_for_status()
                counts[name] = int(response.json()["prompt_eval_count"])
            recorded[digest] = {
                "ref": ref,
                "manifest": local_manifest[:12],
                "ollama": version,
                "request": {
                    "think": False,
                    "num_ctx": int(ctx),
                    "template": "runtime default",
                    "completeness": "truncate:false accepted",
                },
                "counts": counts,
            }
            print(json.dumps({"ref": ref, "digest": digest}), file=sys.stderr)
    print("RECORDED_COUNTS: dict[str, dict[str, object]] = " + pprint.pformat(recorded, width=96))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
