"""Compare the prompt the runtime renders with the one the counter renders.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/render_diff.py \
        --models-root /Users/Shared/ollama/models --i-own-the-window \
        gemma4:31b-it-q8_0=262144 qwen2.5:7b=32768

For each case in `tests/unit/runtime_validation_corpus.py`, the runtime is asked
to render only (`_debug_render_only: true`, `truncate: false`, Ollama 0.33.2)
and its `rendered_template` is compared byte for byte with the counter's own
rendering of the same payload. Equal bytes leave the tokenizer as the only
possible source of disagreement; unequal bytes are a renderer defect whatever
the counts say. Requests carry the model's production context and
`keep_alive: -1`, so a resident model is not reloaded.

Found 2026-10-08 (#24): gemma4 ships no chat template in its GGUF, so the
counter fell back to ChatML while the runtime renders gemma4's own format with
a built-in renderer. The token counts had agreed within +10 on single messages
by coincidence, and tool calls rendered empty, hence 4 tokens short per round.
"""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

import httpx
from _common import Recorder, parser, require_window

from app.adapters.tokenizer.gguf import read_metadata
from app.adapters.tokenizer.gguf_token_counter.adapter import GgufTokenCounter
from app.adapters.tokenizer.ollama_blobs import weights_path
from tests.unit.runtime_validation_corpus import CASES, wire_payload


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("models", nargs="+", help="ref=num_ctx (the production context)")
    p.add_argument("--models-root", type=Path, required=True)
    args = p.parse_args()
    require_window(args)

    with httpx.Client(base_url=args.ollama, timeout=300) as client:
        rec = Recorder(
            "render_diff", args.out, {"version": client.get("/api/version").json()["version"]}
        )
        for spec in args.models:
            ref, _, ctx = spec.partition("=")
            counter = GgufTokenCounter(args.models_root)
            blob = weights_path(args.models_root, ref)
            vocabulary = counter._build_python(ref, blob)  # noqa: SLF001
            # The counter substitutes ChatML when the GGUF carries no template,
            # and `has_template` is then still true, so ask the file itself.
            ships_template = "tokenizer.chat_template" in read_metadata(
                blob, lambda key: key == "tokenizer.chat_template"
            )
            template_source = "gguf" if ships_template else "chatml-fallback"
            for name, case in CASES.items():
                if case.only and ref not in case.only:
                    continue
                body = wire_payload(ref, case, int(ctx))
                reply = client.post(
                    "/api/chat", json={**body, "_debug_render_only": True, "truncate": False}
                )
                if reply.status_code != 200:
                    rec.emit(
                        "rejected",
                        model=ref,
                        case=name,
                        status=reply.status_code,
                        body=reply.text[:160],
                    )
                    continue
                runtime = reply.json()["_debug_info"]["rendered_template"]
                ours = (
                    vocabulary._template.render(  # noqa: SLF001
                        messages=body["messages"],
                        tools=body.get("tools"),
                        add_generation_prompt=True,
                    )
                    if vocabulary
                    else ""
                )
                diff = list(
                    difflib.unified_diff(ours.splitlines(), runtime.splitlines(), lineterm="", n=0)
                )
                rec.emit(
                    "render",
                    model=ref,
                    case=name,
                    counter_template=template_source,
                    equal=ours == runtime,
                    runtime_sha256=hashlib.sha256(runtime.encode()).hexdigest()[:16],
                    counter_sha256=hashlib.sha256(ours.encode()).hexdigest()[:16],
                    runtime_chars=len(runtime),
                    counter_chars=len(ours),
                    first_differences=[line[:160] for line in diff[2:10]],
                )


if __name__ == "__main__":
    main()
