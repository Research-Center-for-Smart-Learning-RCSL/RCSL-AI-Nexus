"""Record the runtime's counts for the profile-validation corpus.

    cd backend && PYTHONPATH=$PWD uv run python \
        ../scripts/runtime-probes/record_validation_counts.py \
        --models-root /Users/Shared/ollama/models --i-own-the-window \
        gemma4:31b-it-q8_0=262144 qwen2.5:7b=32768

Sends each case in `tests/unit/runtime_validation_corpus.py` exactly as the
Ollama adapter would encode it (`message_payload`, `tool_payload`, `think`)
and prints a `RECORDED` literal. Before measuring, it checks that the server
serves the manifest the local store holds, as `record_prompt_counts.py` does.
A case the runtime may not have kept whole is reported and not recorded, since
its count would validate nothing. The runtime drops leading messages silently
once a prompt exceeds its context, which makes the count *smaller*, so a case
the gateway itself counts at or over `num_ctx` is not recorded. Below that the
runtime keeps the prompt whole, and whatever it counts is recorded, including
counts above the gateway's, the deficit this corpus exists to find.
"""

from __future__ import annotations

import argparse
import hashlib
import pprint
import sys
from pathlib import Path

import httpx

from app.adapters.runtime.ollama_adapter.encoding import message_payload, tool_payload
from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import manifest_path, weights_path
from tests.unit.runtime_validation_corpus import CASES


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
            ref, _, ctx = spec.partition("=")
            manifest = hashlib.sha256(manifest_path(args.models_root, ref).read_bytes()).hexdigest()
            if served.get(ref) != manifest:
                print(
                    f"refusing: {ref} is served as {served.get(ref)}, the store holds {manifest}",
                    file=sys.stderr,
                )
                return 1
            counts: dict[str, int] = {}
            counter = GgufTokenCounter(args.models_root)
            vocabulary = counter._build_python(ref, weights_path(args.models_root, ref))  # noqa: SLF001
            for name, case in CASES.items():
                if case.only and ref not in case.only:
                    continue
                body: dict[str, object] = {
                    "model": ref,
                    "messages": [message_payload(m) for m in case.messages],
                    "stream": False,
                    "think": case.think,
                    "keep_alive": -1,
                    "options": {"num_ctx": int(ctx), "num_predict": 1},
                }
                if case.tools:
                    body["tools"] = tool_payload(case.tools)
                reply = client.post("/api/chat", json=body)
                if reply.status_code == 400:
                    # A shape the model does not support (thinking on a model
                    # without it): not a profile the gateway can route there.
                    print(f"unsupported {ref}/{name}: {reply.text[:120]}", file=sys.stderr)
                    continue
                reply.raise_for_status()
                count = int(reply.json()["prompt_eval_count"])
                ours = (
                    vocabulary.count_prompt(body["messages"], body.get("tools", []))
                    if vocabulary
                    else None
                )
                if count >= int(ctx) - 1 or (ours is not None and ours >= int(ctx)):
                    print(
                        f"skipping {ref}/{name}: evaluated {count}, gateway {ours}, num_ctx {ctx}",
                        file=sys.stderr,
                    )
                    continue
                counts[name] = count
                print(f"{ref} {name} {count}", file=sys.stderr)
            digest = weights_path(args.models_root, ref).name.removeprefix("sha256-")[:12]
            recorded[digest] = {
                "ref": ref,
                "manifest": manifest[:12],
                "ollama": version,
                "num_ctx": int(ctx),
                "counts": counts,
            }
    print("RECORDED: dict[str, dict[str, object]] = " + pprint.pformat(recorded, width=96))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
