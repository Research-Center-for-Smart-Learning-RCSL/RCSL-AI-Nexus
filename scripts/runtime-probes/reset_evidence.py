"""Record the evidence a runtime restart leaves, before and after one.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/reset_evidence.py \
        --i-own-the-window --wait-seconds 300

The final spec (#24 §3) resolves an uncertain operation by a *verified runtime
reset after its sender is gone*. This probe establishes what "verified" can rest
on: it records the serving process's PID and start time and the API's view,
then waits for the operator to restart the runtime (launchd or
`brew services restart ollama`) and records them again. It does not restart
anything itself, and it does not reload models afterwards; restore residency
in production order (largest first) when it finishes.
"""

from __future__ import annotations

import time

from _common import Recorder, parser, require_window, runtime, runtime_process


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--wait-seconds", type=int, default=300)
    args = p.parse_args()
    require_window(args)

    with runtime(args) as rt:
        before = runtime_process()
        rec = Recorder(
            "reset_evidence", args.out, {"runtime_process": before, "version": rt.version()}
        )
        rec.emit("before", process=before, resident=rt.resident())
        print("restart the runtime now; waiting for a new process", flush=True)
        deadline = time.monotonic() + args.wait_seconds
        after = before
        while time.monotonic() < deadline:
            time.sleep(1)
            after = runtime_process()
            if (
                after
                and before
                and (after["pid"], after["started"]) != (before["pid"], before["started"])
            ):
                break
        changed = bool(
            after
            and before
            and (after["pid"], after["started"]) != (before["pid"], before["started"])
        )
        api = None
        for _ in range(60):
            try:
                api = {"version": rt.version(), "resident": rt.resident()}
                break
            except Exception:  # noqa: BLE001 - the runtime is coming back up
                time.sleep(1)
        rec.emit("after", process=after, restarted=changed, api=api)


if __name__ == "__main__":
    main()
