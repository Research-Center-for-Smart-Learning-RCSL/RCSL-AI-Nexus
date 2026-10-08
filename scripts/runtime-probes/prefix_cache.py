"""E3: whether a conversation's prefix survives repeats, appends and interleaving.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/prefix_cache.py \
        --i-own-the-window --model qwen2.5:7b --num-ctx 32768 --chars 24000

Runs A cold, A repeated, A appended, then B cold (interleaved), then A and B
appended again, and finally two cold conversations at once. `prompt_eval_count`
reports the whole prompt even on a hit, so reuse shows up only as a short
`prompt_eval_s`; compare durations within one run, never across models.

Measured 2026-10-07 on Ollama 0.33.2, NUM_PARALLEL=1 (#24): interleaving did not
evict either prefix, even at A + B > num_ctx; concurrent requests serialised.
"""

from __future__ import annotations

import threading
from typing import Any

from _common import Recorder, fingerprint, parser, require_window, runtime

TEXT = ("The scheduler admits work when memory allows and evicts idle runners. " * 2000) + (
    "def route(policy):\n    return min(policy.candidates, key=lambda c: c.priority)\n" * 2000
)


def conversation(tag: str, chars: int, turns: int = 0) -> list[dict[str, Any]]:
    offset = (ord(tag[0]) * 997) % 50_000
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"Conversation {tag}. Answer tersely."},
        {"role": "user", "content": TEXT[offset : offset + chars] + "\nWhat is this about?"},
    ]
    for i in range(turns):
        messages += [
            {"role": "assistant", "content": f"Reply {i}."},
            {"role": "user", "content": f"And {i}?"},
        ]
    return messages


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--model", required=True)
    p.add_argument("--num-ctx", type=int, required=True)
    p.add_argument("--chars", type=int, default=24000)
    args = p.parse_args()
    require_window(args)

    with runtime(args) as rt:
        rec = Recorder("prefix_cache", args.out, fingerprint(rt, [args.model]))
        sequence = [
            ("A_cold", conversation("A", args.chars)),
            ("A_repeat", conversation("A", args.chars)),
            ("A_append", conversation("A", args.chars, 1)),
            ("B_cold_interleaved", conversation("B", args.chars)),
            ("A_append_after_B", conversation("A", args.chars, 2)),
            ("B_append_after_A", conversation("B", args.chars, 1)),
        ]
        for name, messages in sequence:
            rec.emit(
                "turn",
                model=args.model,
                run=name,
                **rt.chat(args.model, messages, args.num_ctx, num_predict=8),
            )

        results: dict[str, Any] = {}

        def run(tag: str) -> None:
            results[tag] = rt.chat(
                args.model, conversation(tag, args.chars), args.num_ctx, num_predict=8
            )

        threads = [threading.Thread(target=run, args=(t,)) for t in ("C", "D")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rec.emit("concurrent_cold", model=args.model, **results)
        for tag in ("C", "D"):
            rec.emit(
                "turn",
                model=args.model,
                run=f"{tag}_append_after_concurrent",
                **rt.chat(
                    args.model, conversation(tag, args.chars, 1), args.num_ctx, num_predict=8
                ),
            )


if __name__ == "__main__":
    main()
