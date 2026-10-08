"""E1/T1: where the runtime stops keeping a prompt whole, and what output overflow does.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/boundary.py \
        --i-own-the-window --model qwen2.5:7b --num-ctx 8192 --size-ctx 32768

For each offset around `num_ctx`, a multi-turn prompt with tools is sized by the
runtime's own count (at `--size-ctx`, so the count is never itself truncated),
then sent at `--num-ctx`. A prompt is "kept" when the evaluated count equals the
full count; otherwise the log says whether it was halved (`truncating input
prompt`) or the API silently evaluated fewer tokens (leading messages
dropped, logged at debug only). The overflow cases leave a little headroom and
force a long answer, then read the slot log for `context shift` or a hard stop.

Measured 2026-10-07 on Ollama 0.33.2 (#24): kept up to `num_ctx - 1`; halved at
`num_ctx`; leading messages dropped well above it; qwen2.5 shifts on output
overflow (system prompt lost), gemma4 stops at `num_ctx - 1` with `length`.
"""

from __future__ import annotations

import sys
from typing import Any

from _common import (
    LogTail,
    Recorder,
    answered,
    fingerprint,
    parser,
    require_window,
    runtime,
    size_to_runtime_count,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }
]
FILLER = (
    "def handler(request):\n    if request.method == 'GET':\n        return render(request)\n"
    "    raise MethodNotAllowed(request.method)  # 不支援的方法\n"
) * 4000


def conversation(chars: int, question: str = "Summarise in one sentence.") -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are a code assistant. Answer tersely."},
        {"role": "user", "content": "Look at the handler and tell me what it does."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "handler.py"}}}
            ],
        },
        {"role": "tool", "content": "MARKER " + FILLER[:chars]},
        {"role": "user", "content": question},
    ]


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--model", required=True)
    p.add_argument("--num-ctx", type=int, required=True)
    p.add_argument(
        "--size-ctx", type=int, required=True, help="a larger context to size prompts at"
    )
    p.add_argument("--offsets", default="-2048,-16,-1,0,1,16,2048")
    p.add_argument("--overflow-headroom", default="64,512")
    p.add_argument(
        "--restore-ctx", type=int, help="reload the model at its production context afterwards"
    )
    args = p.parse_args()
    require_window(args)
    log = LogTail(args.ollama_log)

    with runtime(args) as rt:
        rec = Recorder("boundary", args.out, fingerprint(rt, [args.model]))

        initial = rt.resident()
        try:

            def count(messages: list[dict[str, Any]]) -> int | None:
                # `truncate=False`: a payload too large for the sizing context is
                # refused (None) rather than counted by what was kept (review on #26).
                sized = rt.chat(args.model, messages, args.size_ctx, tools=TOOLS, truncate=False)
                return None if sized is None else int(sized["prompt_eval_count"])

            # Size everything first, then test: switching `num_ctx` reloads the
            # runner, and on a large model a reload can evict its siblings (E2).
            question = (
                "Ignore the file. Count from 1 to 3000 in digits, separated by single spaces."
            )
            sized_boundary = []
            for offset in [int(o) for o in args.offsets.split(",")]:
                target = args.num_ctx + offset
                messages, full = size_to_runtime_count(
                    target, conversation, count, first_guess=int(target * 3.5)
                )
                sized_boundary.append((offset, messages, full))
            sized_overflow = []
            for headroom in [int(h) for h in args.overflow_headroom.split(",")]:
                target = args.num_ctx - headroom
                messages, full = size_to_runtime_count(
                    target,
                    lambda n: conversation(n, question),
                    count,
                    first_guess=int(target * 3.5),
                )
                sized_overflow.append((headroom, messages, full))

            for offset, messages, full in sized_boundary:
                log.mark()
                # Default truncation on purpose: this is the behaviour under test.
                result = answered(rt.chat(args.model, messages, args.num_ctx, tools=TOOLS))
                evaluated = result["prompt_eval_count"]
                lines = log.lines()
                halved = any("truncating input prompt" in line for line in lines)
                if evaluated == full:
                    outcome = "kept"
                elif evaluated < full:
                    # A loss. Halving logs at INFO; leading messages are dropped at
                    # debug level only, so "unlogged" names the observation, not
                    # the mechanism.
                    outcome = "lost_halved" if halved else "lost_unlogged"
                else:
                    outcome = "inconsistent_more_than_full"
                rec.emit(
                    "boundary",
                    model=args.model,
                    num_ctx=args.num_ctx,
                    target_offset=offset,
                    full_prompt=full,
                    evaluated=evaluated,
                    delta=evaluated - full,
                    outcome=outcome,
                    result=result,
                    log=lines[-6:],
                )

            for headroom, messages, full in sized_overflow:
                log.mark()
                result = rt.chat(  # default truncation; the overflow is the subject
                    args.model, messages, args.num_ctx, num_predict=headroom * 4, tools=TOOLS
                )
                result = answered(result)
                lines = log.lines()
                rec.emit(
                    "output_overflow",
                    model=args.model,
                    num_ctx=args.num_ctx,
                    headroom=headroom,
                    prompt=full,
                    generated=result["eval_count"],
                    done_reason=result["done_reason"],
                    context_shift=any("context shift" in line for line in lines),
                    stopped_at_window=any("truncated = 1" in line for line in lines),
                    result=result,
                    log=lines[-6:],
                )

            if args.restore_ctx:
                rt.load(args.model, args.restore_ctx)
                rec.emit(
                    "restored", model=args.model, num_ctx=args.restore_ctx, resident=rt.resident()
                )
        except Exception as exc:
            # The runner was reloaded at other contexts; report rather than
            # issue more lifecycle commands into an uncertain state.
            try:
                found = rt.resident()
            except Exception:  # noqa: BLE001 - the runtime may be what failed
                found = None
            rec.emit(
                "recovery_required",
                error=repr(exc)[:300],
                resident_now=found,
                restore_to=initial,
                order="largest model first, then the rest",
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
