"""Drive the task set against candidate models.

  python3 run.py pilot            calibration against the incumbent only (4.2)
  python3 run.py full             three candidates, three interleaved rounds
  python3 run.py restore          put the deployment's model back, pinned

Every sample is appended to results.jsonl as it completes, so an interrupted run
resumes instead of starting over. Model order and task order both rotate per
round (5: "One roll of a sampler is not a capability").
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from harness import OLLAMA, sample
from tasks import TASKS

INCUMBENT = "gemma4:31b-it-q8_0"
CANDIDATES = [INCUMBENT, "qwen3.6:27b-q8_0", "qwen3.6:35b-a3b-q8_0"]

# Restored at the end: what the deployment was serving before this run, and how.
# The num_ctx matters as much as the model does. Ollama keys a loaded instance by
# its options, so restoring at a different context length leaves a model that is
# resident but wrong, and the first real request pays a reload to correct it.
# 196608 is what `gemma4-31b-q8` is registered with (deployment.md, MAX_CONTEXT_LENGTH).
DEPLOYED = [(INCUMBENT, -1, 196608)]

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.jsonl")


def _post(path: str, payload: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def resident() -> list[str]:
    with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=30) as resp:
        return [m["name"] for m in json.load(resp).get("models", [])]


def unload(model: str) -> None:
    try:
        _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=300)
    except Exception as exc:  # noqa: BLE001
        print(f"    unload {model}: {exc}")


def ensure_only(model: str, keep_alive="45m") -> float:
    """Evict everything else, then load `model`. Returns the load wall clock."""
    for other in resident():
        if other != model:
            print(f"    evicting {other}")
            unload(other)
    if model in resident():
        return 0.0
    print(f"    loading {model} ...", flush=True)
    t0 = time.time()
    _post("/api/generate", {"model": model, "prompt": "ok", "stream": False,
                            "think": False, "keep_alive": keep_alive,
                            "options": {"num_ctx": 16384, "num_predict": 8}})
    dt = time.time() - t0
    print(f"    loaded in {dt:.1f}s")
    return dt


def done_keys() -> set:
    if not os.path.exists(RESULTS):
        return set()
    keys = set()
    with open(RESULTS) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            keys.add((r["phase"], r["model"], r["task"], r["round"]))
    return keys


def append(rec: dict) -> None:
    with open(RESULTS, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def rotate(seq: list, n: int) -> list:
    n %= max(len(seq), 1)
    return seq[n:] + seq[:n]


def run(phase: str, models: list[str], rounds: int, only: list[str] | None = None) -> None:
    global TASKS
    if only:
        TASKS = [t for t in TASKS if t["id"] in only]
    already = done_keys()
    total = len(models) * rounds * len(TASKS)
    left = total - sum(1 for k in already if k[0] == phase)
    print(f"{phase}: {len(models)} models x {rounds} rounds x {len(TASKS)} tasks "
          f"= {total} samples, {left} to go\n")

    started = time.time()
    n = 0
    for rnd in range(rounds):
        for model in rotate(models, rnd):
            todo = [t for t in rotate(TASKS, rnd * 5)
                    if (phase, model, t["id"], rnd) not in already]
            if not todo:
                continue
            print(f"round {rnd}  {model}  ({len(todo)} tasks)")
            ensure_only(model)
            for t in todo:
                t0 = time.time()
                rec = sample(model, t)
                rec.update(phase=phase, round=rnd)
                append(rec)
                n += 1
                s = rec["score"]
                shown = "  --  " if s is None else f"{s:5.2f} "
                note = rec.get("no_result", "")
                print(f"   {t['id']:24s} {shown} "
                      f"{rec.get('eval_count') or 0:5d}tok "
                      f"depth={rec.get('prompt_eval_count') or 0:5d} "
                      f"{time.time()-t0:6.1f}s {note}")
            print(f"   -- round {rnd} {model} done, {time.time()-started:.0f}s elapsed\n",
                  flush=True)
    print(f"{phase} complete: {n} new samples in {time.time()-started:.0f}s")


def restore() -> None:
    print("restoring the deployment, largest model first (5)")
    for other in resident():
        if other not in [m for m, _, _ in DEPLOYED]:
            print(f"  evicting {other}")
            unload(other)
    for model, ka, ctx in DEPLOYED:
        print(f"  loading {model} (keep_alive={ka}, num_ctx={ctx}) ...", flush=True)
        t0 = time.time()
        _post("/api/generate", {"model": model, "prompt": "ok", "stream": False,
                                "think": False, "keep_alive": ka,
                                "options": {"num_predict": 8, "num_ctx": ctx}})
        print(f"  {model} resident in {time.time()-t0:.1f}s")
    print("resident now:", resident())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    if cmd == "pilot":
        run("pilot", [INCUMBENT], 3)
    elif cmd == "pilot2":
        # The same calibration against the task set rewritten to stop signposting
        # its own traps, after the first set came in at 100% against the 40-70%
        # band. Kept as a separate phase so the first read stays on the record.
        run("pilot2", [INCUMBENT], 3)
    elif cmd == "full":
        run("full", CANDIDATES, 3)
    elif cmd == "repair":
        # The three prompts that carried a `def f(...): ...` stub. qwen3.6:27b
        # copied the stub and indented a body under it in all three rounds of
        # retry_deadline, scoring 0.00 on an IndentationError -- a measurement of
        # the prompt's formatting, not of the retrying it was asked about. The
        # stub is gone from all three; these re-runs replace their `full` figures.
        run("repair", CANDIDATES, 3,
            only=["retry_deadline", "rate_limiter", "range_sum_updates"])
    elif cmd == "restore":
        restore()
    else:
        print(__doc__)
        sys.exit(2)
