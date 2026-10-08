"""What the runtime does with work whose client has gone away.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/disconnect.py \
        --i-own-the-window --model qwen2.5:7b --num-ctx 32768 --allow-unload

The final spec (#24 §3, §12) refuses to treat a closed connection as proof that
remote work stopped, because nothing had measured it. Three experiments:

- **generation**: stream a long answer, read a few chunks, close. Then time a
  one-token request to the same model. With NUM_PARALLEL=1 a generation that
  kept running delays it; the slot log shows where the runtime stopped.
- **load**: with the model unloaded, request a load with a client timeout far
  shorter than the load, then watch `/api/ps`. If the model becomes resident
  anyway, an abandoned load still completes.
- **truncated body**: with the model unloaded, send a request whose body is
  shorter than its `Content-Length` and close. If the model becomes resident,
  a partial request was acted on.

`load` and `truncated body` unload the model first (`--allow-unload`), so the
capability it serves is unavailable until the probe reloads it at the end.
"""

from __future__ import annotations

import json
import socket
import time
from urllib.parse import urlsplit

import httpx
from _common import LogTail, Recorder, fingerprint, parser, require_window, runtime


def wait_resident(rt, model: str, seconds: float) -> float | None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + seconds
    started = time.monotonic()
    while time.monotonic() < deadline:
        if any(m["name"] == model for m in rt.resident()):
            return round(time.monotonic() - started, 2)
        time.sleep(0.5)
    return None


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
        rec = Recorder("disconnect", args.out, fingerprint(rt, [args.model]))
        short = [{"role": "user", "content": "Say ok."}]

        rt.load(args.model, args.num_ctx)
        baseline = rt.chat(args.model, short, args.num_ctx)["wall_s"]
        log.mark()
        body = {
            "model": args.model,
            "messages": [{"role": "user", "content": "Count from 1 to 5000, one number per line."}],
            "stream": True,
            "think": False,
            "keep_alive": -1,
            "options": {"num_ctx": args.num_ctx, "num_predict": 4000},
        }
        read = 0
        with httpx.Client(base_url=args.ollama, timeout=60) as streaming:
            with streaming.stream("POST", "/api/chat", json=body) as response:
                for _ in response.iter_lines():
                    read += 1
                    if read >= args.chunks:
                        break
        closed_at = time.monotonic()
        follow_up = rt.chat(args.model, short, args.num_ctx)
        rec.emit(
            "generation",
            model=args.model,
            chunks_read=read,
            baseline_wall_s=baseline,
            follow_up_wall_s=follow_up["wall_s"],
            follow_up_delay_s=round(time.monotonic() - closed_at - follow_up["wall_s"], 2),
            continued_after_close=follow_up["wall_s"] > baseline + 2.0,
            log=log.lines()[-8:],
        )

        if not args.allow_unload:
            rec.emit("skipped", cases=["load", "truncated_body"], reason="--allow-unload not given")
            return

        rt.unload(args.model)
        wait_gone = time.monotonic() + 30
        while any(m["name"] == args.model for m in rt.resident()) and time.monotonic() < wait_gone:
            time.sleep(0.5)
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
            client_outcome = "completed before the timeout"
        except httpx.TimeoutException:
            client_outcome = "client timed out and closed"
        became_resident_after = wait_resident(rt, args.model, 60)
        rec.emit(
            "load",
            model=args.model,
            client=client_outcome,
            resident_after_s=became_resident_after,
            load_completed_after_close=became_resident_after is not None,
            log=log.lines()[-8:],
        )

        rt.unload(args.model)
        wait_gone = time.monotonic() + 30
        while any(m["name"] == args.model for m in rt.resident()) and time.monotonic() < wait_gone:
            time.sleep(0.5)
        payload = json.dumps(
            {
                "model": args.model,
                "prompt": "",
                "keep_alive": -1,
                "options": {"num_ctx": args.num_ctx},
            }
        ).encode()
        url = urlsplit(args.ollama)
        log.mark()
        with socket.create_connection(
            (url.hostname or "127.0.0.1", url.port or 80), timeout=5
        ) as raw:
            raw.sendall(
                b"POST /api/generate HTTP/1.1\r\nHost: probe\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode()
                + payload[: len(payload) // 2]
            )
        acted_after = wait_resident(rt, args.model, 30)
        rec.emit(
            "truncated_body",
            model=args.model,
            sent_bytes=len(payload) // 2,
            declared_bytes=len(payload),
            acted_on=acted_after is not None,
            resident_after_s=acted_after,
            log=log.lines()[-8:],
        )

        rt.load(args.model, args.num_ctx)
        rec.emit("restored", model=args.model, num_ctx=args.num_ctx, resident=rt.resident())


if __name__ == "__main__":
    main()
