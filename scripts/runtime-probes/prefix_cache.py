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
import time
from typing import Any

from _common import (
    Recorder,
    answered,
    fingerprint,
    parser,
    require_window,
    runtime,
    server_num_parallel,
)

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
                **answered(rt.chat(args.model, messages, args.num_ctx, num_predict=8)),
            )

        # Concurrency: both requests released by one barrier, each timed and
        # each failure kept, so overlap or serialisation is read from the
        # timestamps rather than assumed from starting two threads (review on
        # #26). The server's parallelism comes from its own startup line.
        results: dict[str, Any] = {}
        barrier = threading.Barrier(2)
        epoch = time.monotonic()

        def run(tag: str) -> None:
            try:
                barrier.wait(timeout=30)
                started = time.monotonic() - epoch
                reply = answered(
                    rt.chat(args.model, conversation(tag, args.chars), args.num_ctx, num_predict=8)
                )
                results[tag] = {
                    **reply,
                    "started_s": round(started, 3),
                    "ended_s": round(time.monotonic() - epoch, 3),
                }
            except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                results[tag] = {"error": repr(exc)[:300]}

        threads = [threading.Thread(target=run, args=(t,)) for t in ("C", "D")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        timed = [r for r in results.values() if "ended_s" in r]
        overlap = None
        if len(timed) == 2:
            first, second = sorted(timed, key=lambda r: r["ended_s"])
            # Serialised: the later one's evaluation began only after the
            # earlier ended, so its wall time covers both prefills.
            overlap = round(first["ended_s"] - second["started_s"], 3)
        rec.emit(
            "concurrent_cold",
            model=args.model,
            server_num_parallel=server_num_parallel(args.ollama_log),
            results=results,
            observation={"seconds_both_in_flight": overlap},
        )
        for tag in ("C", "D"):
            rec.emit(
                "turn",
                model=args.model,
                run=f"{tag}_append_after_concurrent",
                **answered(
                    rt.chat(
                        args.model, conversation(tag, args.chars, 1), args.num_ctx, num_predict=8
                    )
                ),
            )


if __name__ == "__main__":
    main()
