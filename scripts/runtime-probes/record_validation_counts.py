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
small, plausible count (review on #24). Each case is therefore also counted
prefix by prefix; a case is recorded only if every longer prefix counts
strictly more and the full payload counts more than all of them, and the full
count is below `num_ctx - 1` (where the runtime keeps a prompt whole, E1).
A single-message case is cut at 25/50/75% of its content instead.
Each record keeps the payload hash, options and counting context.
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

from app.adapters.tokenizer.ollama_blobs import manifest_path, weights_path
from tests.unit.runtime_validation_corpus import CASES, wire_payload


def _count(client: httpx.Client, body: dict[str, Any]) -> int | str:
    reply = client.post("/api/chat", json=body)
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
            manifest = hashlib.sha256(manifest_path(args.models_root, ref).read_bytes()).hexdigest()
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
                    print(f"unsupported {ref}/{name}: {full}", file=sys.stderr)
                    continue
                messages = body["messages"]
                if len(messages) > 1:
                    partials = [{**body, "messages": messages[:k]} for k in range(1, len(messages))]
                else:
                    # One message has no message prefixes, so its content is
                    # cut instead. A runtime that halved the prompt reports no
                    # more than the 50% cut, which fails the strict check.
                    text = messages[0]["content"]
                    partials = [
                        {
                            **body,
                            "messages": [{**messages[0], "content": text[: len(text) * q // 4]}],
                        }
                        for q in (1, 2, 3)
                    ]
                prefixes: list[int] = []
                for partial_body in partials:
                    partial = _count(client, partial_body)
                    if isinstance(partial, str):
                        break
                    prefixes.append(partial)
                complete = (
                    len(prefixes) == len(partials)
                    and full < ctx - 1
                    and prefix_counts_are_complete(prefixes, full)
                )
                if not complete:
                    print(
                        f"not recorded {ref}/{name}: full {full}, prefixes {prefixes[-3:]}",
                        file=sys.stderr,
                    )
                    continue
                payload_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
                cases[name] = {
                    "count": full,
                    "payload_sha256": payload_hash[:16],
                    "think_on_wire": body.get("think", "omitted"),
                    "completeness": f"{len(prefixes)} strictly increasing prefixes",
                    "prefix_counts": prefixes
                    if len(prefixes) <= 4
                    else [*prefixes[:2], "...", prefixes[-1]],
                }
                print(f"{ref} {name} {full}", file=sys.stderr)
            digest = weights_path(args.models_root, ref).name.removeprefix("sha256-")[:12]
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
