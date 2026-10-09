"""Record the runtime's own token ids for gemma4, as goldens for the counter.

    cd backend && PYTHONPATH=$PWD uv run python \
        ../scripts/runtime-probes/record_tokenizer_goldens.py \
        --models-root /Users/Shared/ollama/models --runner-port <port> \
        gemma4:31b-it-q8_0 > tests/unit/gemma4_tokenizer_goldens.py

The oracle is the runtime's tokenizer itself: Ollama 0.33.2 serves gemma4
from a llama-server runner, and that runner's `POST /tokenize` returns the ids
llama.cpp produces (`parse_special: true`, `add_special: false`, which is how
the rendered prompt is tokenized apart from the BOS Ollama re-adds). The port
is the `--port` on the gemma4 runner's command line (`ps -o args -p <pid>`);
the runner must be the one serving the reference named here, which the
script checks against `/props`. Read-only: no generation, nothing loaded.

The texts are `tests/unit/gemma4_tokenizer_corpus.py`: edge cases chosen by
hand, a seeded random mix (characters, spaces, newlines, special-token
spellings, scripts, emoji, controls), and whole prompts rendered by
`gemma4_renderer` from the validation corpus with thinking on and off. Each record keeps the count and a SHA-256 of
the id sequence, so a mismatch anywhere in the sequence is caught without
storing the ids.
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

from app.adapters.tokenizer.ollama_blobs import weights_path
from tests.unit.gemma4_tokenizer_corpus import all_texts, rendered_prompts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ref")
    p.add_argument("--models-root", type=Path, required=True)
    p.add_argument("--runner-port", type=int, required=True)
    p.add_argument("--seed", type=int, default=20261009)
    p.add_argument("--random", type=int, default=120)
    args = p.parse_args()

    blob = weights_path(args.models_root, args.ref)
    with httpx.Client(base_url=f"http://127.0.0.1:{args.runner_port}", timeout=120) as runner:
        props = runner.get("/props").json()
        served = str(props.get("model_path", ""))
        if not served.endswith(blob.name):
            print(f"refusing: the runner serves {served}, not {blob.name}", file=sys.stderr)
            return 1

        def ids(text: str) -> list[int]:
            reply = runner.post(
                "/tokenize", json={"content": text, "add_special": False, "parse_special": True}
            )
            reply.raise_for_status()
            return [t if isinstance(t, int) else t["id"] for t in reply.json()["tokens"]]

        def record(text: str) -> tuple[int, str]:
            got = ids(text)
            return len(got), hashlib.sha256(json.dumps(got).encode()).hexdigest()[:16]

        texts = all_texts(args.seed, args.random)
        goldens: dict[str, Any] = {
            "ref": args.ref,
            "weights": blob.name.removeprefix("sha256-"),
            "ollama": httpx.get("http://127.0.0.1:11434/api/version").json()["version"],
            "llama_server_build": props.get("build_info", ""),
            "seed": args.seed,
            "random": args.random,
            "texts": [(i, *record(text)) for i, text in enumerate(texts)],
            "rendered": {name: record(text) for name, text in rendered_prompts(args.ref).items()},
        }
    print('"""The runtime\'s own gemma4 token ids, recorded by')
    print("`scripts/runtime-probes/record_tokenizer_goldens.py` (C6b on #24).")
    print()
    print("`texts` index `gemma4_tokenizer_corpus.all_texts(seed, random)`;")
    print("`rendered` names validation-corpus cases rendered by `gemma4_renderer`. Each")
    print('entry is (count, first 16 hex of SHA-256 over the JSON id list)."""')
    print()
    print("GOLDENS = " + pprint.pformat(goldens, width=96, sort_dicts=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
