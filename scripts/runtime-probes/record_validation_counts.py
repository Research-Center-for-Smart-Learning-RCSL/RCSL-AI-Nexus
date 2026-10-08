"""Record the runtime's counts for the profile-validation corpus.

    cd backend && PYTHONPATH=$PWD uv run python \
        ../scripts/runtime-probes/record_validation_counts.py \
        --models-root /Users/Shared/ollama/models --i-own-the-window \
        gemma4:31b-it-q8_0=262144 qwen2.5:7b=32768

Sends each case in `tests/unit/runtime_validation_corpus.py` exactly as the
Ollama adapter would (`wire_payload`: its encoders and its `think` semantics)
and prints a `RECORDED` literal. Before measuring, it checks that the server
serves the manifest the local store holds.

**Completeness comes from the runtime, never from the counter under test.**
The runtime reports only what it kept, so a truncated prompt can return a
small, plausible count (review on #24). Every count is therefore requested
with `truncate: false`: the runtime then refuses a prompt
that does not fit (400, `exceed_context_size_error`) instead of dropping
leading messages, so a count it returns is a count of the whole payload
(verified on Ollama 0.33.2, 2026-10-08). A refusal is a rejected measurement.
Strictly increasing prefix counts are kept only as a diagnostic: they cannot
certify completeness, because the runtime drops leading messages and keeps
the last (review on #24). Each record keeps the payload hash, options and
counting context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pprint
import sys
from pathlib import Path
from typing import Any

import httpx
from _common import prefix_counts_are_complete

from app.adapters.tokenizer.ollama_blobs import manifest_path, weights_in_manifest
from tests.unit.runtime_validation_corpus import CASES, wire_payload


def _count(client: httpx.Client, body: dict[str, Any]) -> int | str:
    # `truncate: false` only. `shift: false` is a runner option: sending it
    # reloaded the runner (num_batch changed), and on gemma4 a reload evicts
    # its siblings (E2). It governs output overflow, which a count with
    # num_predict 1 never reaches (observed 2026-10-08, #24).
    reply = client.post("/api/chat", json={**body, "truncate": False})
    if reply.status_code == 400:
        return reply.text[:160]
    reply.raise_for_status()
    return int(reply.json()["prompt_eval_count"])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("models", nargs="+", help="ref=num_ctx")
    p.add_argument("--models-root", type=Path, required=True)
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--i-own-the-window", action="store_true")
    p.add_argument(
        "--prefix-diagnostic",
        action="store_true",
        help="also count message prefixes (diagnostic only; slow on long loops)",
    )
    args = p.parse_args()
    if not args.i_own_the_window:
        print("refusing: this occupies the runtime; pass --i-own-the-window", file=sys.stderr)
        return 2

    recorded: dict[str, dict[str, object]] = {}
    with httpx.Client(base_url=args.ollama, timeout=1800) as client:
        version = client.get("/api/version").json()["version"]
        served = {m["name"]: m["digest"] for m in client.get("/api/tags").json()["models"]}
        for spec in args.models:
            ref, _, ctx_text = spec.partition("=")
            ctx = int(ctx_text)
            # One read: the blob is resolved from the bytes that were verified
            # against the server, not from a second read (review on #31).
            raw = manifest_path(args.models_root, ref).read_bytes()
            manifest = hashlib.sha256(raw).hexdigest()
            if served.get(ref) != manifest:
                print(
                    f"refusing: {ref} is served as {served.get(ref)}, not {manifest}",
                    file=sys.stderr,
                )
                return 1
            cases: dict[str, dict[str, object]] = {}
            for name, case in CASES.items():
                if case.only and ref not in case.only:
                    continue
                body = wire_payload(ref, case, ctx)
                full = _count(client, body)
                if isinstance(full, str):
                    kind = "overflow, rejected" if "exceed_context" in full else "unsupported"
                    print(f"{kind} {ref}/{name}: {full}", file=sys.stderr)
                    continue
                prefixes: list[int] = []
                if args.prefix_diagnostic:
                    messages = body["messages"]
                    for k in range(1, len(messages)):
                        partial = _count(client, {**body, "messages": messages[:k]})
                        if isinstance(partial, str):
                            break
                        prefixes.append(partial)
                payload_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                cases[name] = {
                    "count": full,
                    "payload_sha256": payload_hash[:16],
                    "think_on_wire": body.get("think", "omitted"),
                    "completeness": "truncate:false accepted",
                    **(
                        {"prefix_diagnostic_monotone": prefix_counts_are_complete(prefixes, full)}
                        if prefixes
                        else {}
                    ),
                }
                print(f"{ref} {name} {full}", file=sys.stderr)
            digest = weights_in_manifest(args.models_root, ref, raw).name.removeprefix("sha256-")[
                :12
            ]
            recorded[digest] = {
                "ref": ref,
                "manifest": manifest[:12],
                "ollama": version,
                "num_ctx": ctx,
                "cases": cases,
            }
    print("RECORDED: dict[str, dict[str, object]] = " + pprint.pformat(recorded, width=96))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
