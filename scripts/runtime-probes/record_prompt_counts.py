"""Record the runtime's prompt token counts for the counter's agreement test.

Operator-run, never in CI: it sends one request per corpus text to each named
model, which loads the model if it is not resident. Run it in a window you own.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/record_prompt_counts.py \
        --models-root /Users/Shared/ollama/models --i-own-the-window \
        gemma4:31b-it-q8_0=262144 qwen2.5:7b=32768

Prints a `RECORDED_COUNTS` literal for `tests/unit/runtime_count_corpus.py`,
keyed by weights-blob digest so a re-pulled model cannot inherit counts that
were measured on different weights.
"""

from __future__ import annotations

import argparse
import json
import pprint
import sys
from pathlib import Path

import httpx

from app.adapters.tokenizer.ollama_blobs import weights_path
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
        for spec in args.models:
            ref, _, ctx = spec.partition("=")
            digest = weights_path(args.models_root, ref).name.removeprefix("sha256-")[:12]
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
                        "options": {"num_ctx": int(ctx), "num_predict": 1},
                    },
                )
                response.raise_for_status()
                counts[name] = int(response.json()["prompt_eval_count"])
            recorded[digest] = {"ref": ref, "ollama": version, "counts": counts}
            print(json.dumps({"ref": ref, "digest": digest}), file=sys.stderr)
    print("RECORDED_COUNTS: dict[str, dict[str, object]] = " + pprint.pformat(recorded, width=96))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
