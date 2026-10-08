"""What the runtime does with work whose client has gone away.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/disconnect.py \
        --i-own-the-window --model qwen2.5:7b --num-ctx 32768 --allow-unload

The final spec (#24 §3, §12) refuses to treat a closed connection as proof that
remote work stopped, because nothing had measured it. Three experiments, each
of which reports a conclusion only from evidence tied to its own request, and
`None` (inconclusive) otherwise (review on #26):

- **generation**: stream a long answer, read a few chunks, close. The slot log
  must show a cancellation after the close for `cancelled_at_close: true`, or
  the task running far past it for `false`. The timing of a follow-up request
  is recorded as an observation and never decides the outcome: a slow
  follow-up can be a reload or ordinary variance.
- **load**: with the model verified absent, request a load with a client
  timeout far shorter than the load. Only a request that actually timed out
  tests abandonment; one that completed in time is reported as untested.
- **truncated body**: with the model verified absent, send a body shorter than
  its `Content-Length` and close; residency afterwards means it was acted on.

`load` and `truncated body` unload the model first (`--allow-unload`), so its
capability is unavailable until the probe reloads it. If anything fails part
way, the probe issues no further lifecycle commands into an uncertain state: it
records `recovery_required` with the residency it found and the residency to
restore (largest model first), and exits non-zero.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from _common import (
    LogTail,
    Recorder,
    Runtime,
    answered,
    fingerprint,
    parser,
    require_window,
    runtime,
)


def wait_until(rt: Runtime, model: str, *, resident: bool, seconds: float) -> float | None:
    """Seconds until the model's residency equals `resident`, or None."""
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        if any(m["name"] == model for m in rt.resident()) == resident:
            return round(time.monotonic() - started, 2)
        time.sleep(0.5)
    return None


def generation(rt: Runtime, rec: Recorder, log: LogTail, args: Any) -> None:
    short = [{"role": "user", "content": "Say ok."}]
    baseline = answered(rt.chat(args.model, short, args.num_ctx))["wall_s"]
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": "Count from 1 to 5000, one number per line."}],
        "stream": True,
        "think": False,
        "keep_alive": -1,
        "options": {"num_ctx": args.num_ctx, "num_predict": 4000},
    }
    log.mark()
    read = 0
    with httpx.Client(base_url=args.ollama, timeout=60) as streaming:
        with streaming.stream("POST", "/api/chat", json=body) as response:
            for _ in response.iter_lines():
                read += 1
                if read >= args.chunks:
                    break
    follow_up = answered(rt.chat(args.model, short, args.num_ctx))
    lines = log.lines()
    # The streamed task is the first released after the mark; its own cancel or
    # release line is the evidence, never the follow-up's timing.
    cancels = [line for line in lines if "cancel task" in line]
    released = [line for line in lines if "stop processing" in line and "n_tokens =" in line]
    verdict: bool | None = None
    if cancels:
        verdict = True
    elif released:
        tokens = int(released[0].split("n_tokens =")[1].split(",")[0])
        if tokens > 4 * (read + 64):
            verdict = False
    rec.emit(
        "generation",
        model=args.model,
        chunks_read=read,
        cancelled_at_close=verdict,
        evidence=(cancels + released)[:3],
        observation={"baseline_wall_s": baseline, "follow_up_wall_s": follow_up["wall_s"]},
    )


def abandoned_load(rt: Runtime, rec: Recorder, log: LogTail, args: Any) -> None:
    rt.unload(args.model)
    if wait_until(rt, args.model, resident=False, seconds=30) is None:
        rec.emit("load", model=args.model, tested=False, reason="the model never became absent")
        return
    log.mark()
    try:
        with httpx.Client(base_url=args.ollama, timeout=0.3) as impatient:
            impatient.post(
                "/api/generate",
                json={
                    "model": args.model,
                    "prompt": "",
                    "keep_alive": -1,
                    "options": {"num_ctx": args.num_ctx},
                },
            )
        timed_out = False
    except httpx.TimeoutException:
        timed_out = True
    if not timed_out:
        rec.emit(
            "load",
            model=args.model,
            tested=False,
            reason="the load completed before the client timeout; abandonment was not tested",
        )
        return
    after = wait_until(rt, args.model, resident=True, seconds=60)
    rec.emit(
        "load",
        model=args.model,
        tested=True,
        load_completed_after_close=after is not None,
        resident_after_s=after,
        evidence=[ln for ln in log.lines() if "Load failed" in ln or "loading model" in ln][-3:],
    )


def truncated_body(rt: Runtime, rec: Recorder, log: LogTail, args: Any) -> None:
    rt.unload(args.model)
    if wait_until(rt, args.model, resident=False, seconds=30) is None:
        rec.emit(
            "truncated_body", model=args.model, tested=False, reason="the model never became absent"
        )
        return
    payload = json.dumps(
        {"model": args.model, "prompt": "", "keep_alive": -1, "options": {"num_ctx": args.num_ctx}}
    ).encode()
    url = urlsplit(args.ollama)
    log.mark()
    with socket.create_connection((url.hostname or "127.0.0.1", url.port or 80), timeout=5) as raw:
        raw.sendall(
            b"POST /api/generate HTTP/1.1\r\nHost: probe\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(payload)}\r\n\r\n".encode()
            + payload[: len(payload) // 2]
        )
    acted = wait_until(rt, args.model, resident=True, seconds=30)
    rec.emit(
        "truncated_body",
        model=args.model,
        tested=True,
        sent_bytes=len(payload) // 2,
        declared_bytes=len(payload),
        acted_on=acted is not None,
        evidence=log.lines()[-3:],
    )


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--model", required=True)
    p.add_argument("--num-ctx", type=int, required=True)
    p.add_argument(
        "--allow-unload", action="store_true", help="required for the load and truncated-body cases"
    )
    p.add_argument("--chunks", type=int, default=5)
    args = p.parse_args()
    require_window(args)
    log = LogTail(args.ollama_log)

    with runtime(args) as rt:
        before = rt.resident()
        rec = Recorder("disconnect", args.out, fingerprint(rt, [args.model]))
        try:
            rt.load(args.model, args.num_ctx)
            generation(rt, rec, log, args)
            if not args.allow_unload:
                rec.emit(
                    "skipped", cases=["load", "truncated_body"], reason="--allow-unload not given"
                )
                return
            abandoned_load(rt, rec, log, args)
            truncated_body(rt, rec, log, args)
            rt.load(args.model, args.num_ctx)
            rec.emit("restored", model=args.model, num_ctx=args.num_ctx, resident=rt.resident())
        except Exception as exc:
            try:
                found: list[dict[str, Any]] | None = rt.resident()
            except Exception:  # noqa: BLE001 - the runtime may be what failed
                found = None
            rec.emit(
                "recovery_required",
                error=repr(exc)[:300],
                resident_now=found,
                restore_to=before,
                order="largest model first, then the rest",
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
