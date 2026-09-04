"""Drive the task set against candidate models.

  python3 run.py pilot            calibration against the incumbent only (4.2)
  python3 run.py full             three candidates, three interleaved rounds
  python3 run.py qwen38           the Qwen 3.8 27B builds, plus the incumbent
  python3 run.py hard-pilot       the 2026-09-03 set, calibration against the incumbent
  python3 run.py hard-full        the 2026-09-03 set, the four qwen38 candidates
  python3 run.py hard-pilot-2     the set as revised later that day, incumbent only
  python3 run.py hard-full-2      the revised set, the four qwen38 candidates
  python3 run.py restore          put the deployment's model back, pinned

Every sample is appended to results.jsonl as it completes, so an interrupted run
resumes instead of starting over. Model order and task order both rotate per
round (5: "One roll of a sampler is not a capability").
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

from harness import OLLAMA, SEED, TEMPERATURE, TOP_K, TOP_P, sample
from tasks import TASKS

ROUNDS = int(os.environ.get("EVAL_ROUNDS", "5"))

INCUMBENT = "gemma4:31b-it-q8_0"
CANDIDATES = [INCUMBENT, "qwen3.6:27b-q8_0", "qwen3.6:35b-a3b-q8_0"]

# The 2026-09-02 candidate, in three builds, against the incumbent re-run as a
# control rather than compared against its recorded 94.4%.
#
# **Re-running the incumbent is the point of the fourth entry.** Its published
# figure was measured on Ollama 0.32.4 and this runs on 0.33.2, which the
# throughput bench put at +1.8% to +5.4% on generation; a score is not a rate,
# but nothing here has established that a runtime upgrade cannot move one, and
# a control that costs 29 minutes is cheaper than an argument about it later.
#
# **`27b-q8_0` is here because section 5 says quantisation must be matched.**
# The two builds a deployment would actually choose are `q4_K_M` and the MLX
# nvfp4, and comparing either against a q8 incumbent confounds the model with
# its quantisation -- which is exactly how 2026-08-07's "stronger than glm"
# conclusion was invalidated, and section 5 names it as the easiest mistake to
# repeat. The q8 build separates the two questions, and the q8-to-q4 gap it
# exposes is the first measurement this repository has of what q4 costs in
# capability rather than in memory, which decisions.md has carried as open
# since 2026-08-05.
#
# `27b-mtp-q4_K_M` is deliberately absent. Its MTP head has nothing to
# speculate for on the GGUF runner and it measured 10.91 gen tok/s against the
# plain q4's 23.21, so it is the same weights run slower (PROGRESS.md
# 2026-09-02).
CANDIDATES_38 = [
    INCUMBENT,
    "qwen3.8:27b-q8_0",
    "qwen3.8:27b-q4_K_M",
    "qwen3.8:27b-mlx",
]

# Restored at the end: what the deployment is serving, and how.
#
# The num_ctx matters as much as the model does. Ollama keys a loaded instance by
# its options, so restoring at a different context length leaves a model that is
# resident but wrong, and the first real request pays a reload to correct it.
# These are the `context_length` column of the `models` table, which is what
# `ManageModels` sends; Ollama clamps each to the model's own maximum, which is
# why `/api/ps` reads 32768 and 2048 back for the two smaller ones.
#
# **This literal went stale once and nothing here noticed, which is why it is now
# the fallback rather than the source.** It named `qwen3.6:35b-a3b-q8_0` alone,
# correct on 2026-08-16 and wrong from 2026-08-21, when the deployment moved back
# to `gemma4:31b-it-q8_0` (audit_log 07:58:13 and 07:59:36). A `restore` run in
# that window would have evicted what was serving and loaded what was not --
# exactly what the comment standing here warned about and could not detect. It
# was also never complete: the deployment holds three models and this held one,
# so `assist` and `embedding` stayed down after every restore, and the embedding
# model would have 400ed on the generate path in any case. `snapshot()` now
# records residency before a phase evicts anything, and `restore()` prefers it.
DEPLOYED = [
    ("gemma4:31b-it-q8_0", -1, 262144),
    ("qwen2.5:7b", -1, 262144),
    # `:latest` is not decoration. `resident()` reports what `/api/ps` calls the
    # model, which carries the tag, and `restore()` decides what to evict by
    # comparing those names against these. Written without the tag, the
    # embedder never matched itself: every fallback restore evicted
    # `nomic-embed-text:latest` and then loaded `nomic-embed-text` back,
    # which is the same model taking a round trip for a string comparison.
    # Observed 2026-09-03. The snapshot path was never affected -- it records
    # the name the runtime gave it.
    ("nomic-embed-text:latest", -1, 8192),
]

# The hard set. Groups J through Q are the tasks designed for this set; the
# anchor bridge carries tasks from the eighteen-task set to make scores
# comparable across sets — which no longer has the weight it carried when it
# was first written, since pinning the temperature means every figure before
# this phase was measured under conditions that cannot recur.
#
# **`count_inversions` is removed from the bridge.** Its role as a harness
# control — 1.00 everywhere, proving the scorer did not move — was falsified
# on 2026-09-04 when it scored 0.80 in three of four samples
# (`RecursionError` from a genuine edge-case defect). And its role as an
# anchor — linking this set's figures to the eighteen-task set — has no
# remaining value now that every earlier figure was measured without a pinned
# temperature. `range_sum_updates` takes its slot: a complexity task that
# requires a Fenwick tree or segment tree, harder than merge-sort inversions
# and less likely to saturate.
HARD_GROUPS = {"J", "K", "L", "M", "N", "P", "Q", "R", "S"}
ANCHOR_BRIDGE = ["ini_parse", "search_last_rotated", "range_sum_updates"]

# The education-agent set, which is multi-turn and measures something no other
# group here does: whether the model keeps obeying a system prompt it was given
# once, across a conversation in which a student is actively working against it.
# It carries no anchors, because nothing in either earlier set is comparable.
TUTOR_GROUP = "T"

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.jsonl")
SNAPSHOT = os.path.join(HERE, "deployment-snapshot.json")


def hard_set() -> list[str]:
    return [t["id"] for t in TASKS if t["group"] in HARD_GROUPS] + ANCHOR_BRIDGE


def tutor_set() -> list[str]:
    return [t["id"] for t in TASKS if t["group"] == TUTOR_GROUP]


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


def snapshot() -> None:
    """Record residency before this run evicts anything.

    Written once and only once: a phase that is interrupted and resumed would
    otherwise overwrite the deployment's state with the harness's own model,
    which is the failure the file it writes exists to prevent. `restore()`
    removes it on success, so the next run takes a fresh one.
    """
    if os.path.exists(SNAPSHOT):
        print(f"  keeping the existing snapshot ({SNAPSHOT})")
        return
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/ps", timeout=30) as resp:
            models = json.load(resp).get("models", [])
    except Exception as exc:  # noqa: BLE001 - a snapshot that cannot be taken is a run fact
        print(f"  could not snapshot residency: {exc}")
        return
    if not models:
        print("  nothing resident to snapshot; restore will fall back to DEPLOYED")
        return
    # `context_length` here is what Ollama clamped to, not what the registry
    # sent. Restoring the clamped value reproduces the same runner, and asking
    # for more than the model supports is what the clamp exists to absorb.
    #
    # **Sorted largest first, and the first version of this was not.** `/api/ps`
    # returns residency in no useful order, and restoring in that order put the
    # 36 GB model last on 2026-09-02: it was loaded, found the two small ones in
    # its way, and evicted both. The restore reported success with one model
    # resident out of three. The `DEPLOYED` literal had carried this ordering by
    # hand since it was written; the snapshot has to carry it too, which is why
    # `size` is recorded rather than just the name.
    models.sort(key=lambda m: m.get("size") or 0, reverse=True)
    state = [{"model": m["name"], "keep_alive": -1,
              "num_ctx": m.get("context_length") or 0, "size": m.get("size") or 0}
             for m in models]
    with open(SNAPSHOT, "w") as fh:
        json.dump(state, fh, indent=2)
    print(f"  snapshot: {', '.join(m['model'] for m in state)}")


def load_pinned(model: str, keep_alive: int | str, num_ctx: int) -> None:
    """Warm one model, answering an embedding model's refusal of `/api/generate`.

    `backend/.../ollama_adapter/lifecycle.py` does the same thing for the same
    reason: an embedding model answers 400 `does not support generate`, and
    `/api/embed` with an empty input moves the same weights and honours the same
    `keep_alive`. `restore` sent every model down the generate path until this
    existed, so a deployment holding `nomic-embed-text` came back one model short.
    """
    body = {"model": model, "keep_alive": keep_alive}
    if num_ctx > 0:
        body["options"] = {"num_ctx": num_ctx}
    try:
        _post("/api/generate", body)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        _post("/api/embed", {**body, "input": []})


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
          f"= {total} samples, {left} to go")
    print(f"  temperature={TEMPERATURE}  top_k={TOP_K}  top_p={TOP_P}  seed={SEED}\n")

    # Before `ensure_only` evicts anything. A phase that dies half way leaves the
    # file behind, so a later `restore` still knows what the deployment was.
    snapshot()

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
                # The instant the sample *started*, in UTC. `wall_s` gives the
                # duration, so a row now says both when it happened and how long
                # it took, and start + wall_s recovers the end.
                #
                # Added 2026-09-03, and the gap it closes is not a small one: a
                # row could not be placed in time at all, so a harness phase
                # could not be correlated with anything else the deployment
                # recorded. The specific question that could not be answered was
                # whether a gateway request had ever arrived while a phase held
                # the runtime -- `usage_records` has timestamps, this had none,
                # and the two could not be joined. Section 5 asks every figure to
                # carry the conditions it was generated under; when it was
                # generated is one of those conditions.
                rec.update(
                    phase=phase,
                    round=rnd,
                    at=datetime.datetime.fromtimestamp(
                        t0, tz=datetime.UTC
                    ).isoformat(),
                )
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
    """Put back what was resident before the run, largest model first (5)."""
    if os.path.exists(SNAPSHOT):
        with open(SNAPSHOT) as fh:
            recorded = json.load(fh)
        # Sorted here as well as when written, so a snapshot from an older run
        # is put back in the right order rather than in the order it was saved.
        recorded.sort(key=lambda m: m.get("size") or 0, reverse=True)
        wanted = [(m["model"], m.get("keep_alive", -1), m.get("num_ctx", 0))
                  for m in recorded]
        print(f"restoring from {os.path.basename(SNAPSHOT)}")
    else:
        wanted = list(DEPLOYED)
        print("NO SNAPSHOT -- falling back to the DEPLOYED literal, which has gone "
              "stale before. Check it against the deployment before trusting this.")

    for other in resident():
        if other not in [m for m, _, _ in wanted]:
            print(f"  evicting {other}")
            unload(other)
    for model, ka, ctx in wanted:
        print(f"  loading {model} (keep_alive={ka}, num_ctx={ctx}) ...", flush=True)
        t0 = time.time()
        load_pinned(model, ka, ctx)
        print(f"  {model} resident in {time.time()-t0:.1f}s")
    print("resident now:", resident())
    if os.path.exists(SNAPSHOT):
        os.remove(SNAPSHOT)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pilot"
    if cmd == "pilot":
        run("pilot", [INCUMBENT], ROUNDS)
    elif cmd == "pilot2":
        # The same calibration against the task set rewritten to stop signposting
        # its own traps, after the first set came in at 100% against the 40-70%
        # band. Kept as a separate phase so the first read stays on the record.
        run("pilot2", [INCUMBENT], ROUNDS)
    elif cmd == "full":
        run("full", CANDIDATES, ROUNDS)
    elif cmd == "qwen38":
        # A separate phase rather than more rows in `full`, because `full` was
        # measured on Ollama 0.32.4 against three candidates two of which are
        # retired, and `analyse.py` reads one phase at a time. It also needs no
        # `repair`: the three prompts that carried a `def f(...): ...` stub were
        # fixed in `tasks.py` on 2026-08-15, so this phase gets the repaired
        # wording from its first sample. That makes it comparable with `full`
        # overridden by `repair`, which is the published reading, and not with
        # `full` alone.
        run("qwen38", CANDIDATES_38, ROUNDS)
    elif cmd == "repair":
        # The three prompts that carried a `def f(...): ...` stub. qwen3.6:27b
        # copied the stub and indented a body under it in all three rounds of
        # retry_deadline, scoring 0.00 on an IndentationError -- a measurement of
        # the prompt's formatting, not of the retrying it was asked about. The
        # stub is gone from all three; these re-runs replace their `full` figures.
        run("repair", CANDIDATES, ROUNDS,
            only=["retry_deadline", "rate_limiter", "range_sum_updates"])
    elif cmd == "hard-pilot":
        # Section 4.2: calibrate against the incumbent alone before any
        # comparison. The eighteen-task set reached 93.4% here and 16 of its 18
        # tasks were never missed once, so this phase exists to find out whether
        # the replacement lands in the 40-70% band -- and a pilot is the cheap
        # place to find out it does not.
        run("hard-pilot", [INCUMBENT], ROUNDS, only=hard_set())
    elif cmd == "hard-full":
        run("hard-full", CANDIDATES_38, ROUNDS, only=hard_set())
    elif cmd == "hard-pilot-2":
        # Calibration for the set as revised on 2026-09-03: four replacement
        # tasks in group N, `precedence_relief` in place of the five-link
        # `precedence_chain`, and a raised output
        # budget on `vm_trace` and `ledger_replay`. Run against the incumbent
        # alone, which costs no downtime because it is already resident.
        #
        # **This pilot calibrates difficulty and settles nothing about a task**,
        # which is section 7.2's finding and the reason it is worth running
        # anyway: the previous pilot read the set as failed at 83.3% and four of
        # the ten tasks it would have discarded turned out to separate the
        # candidates. What it can still do is catch a prompt that no model
        # answers in the requested form before four candidates spend four hours
        # on it, and say whether the budget raise did what it was raised for.
        run("hard-pilot-2", [INCUMBENT], ROUNDS, only=hard_set())
    elif cmd == "hard-full-2":
        # A separate phase from `hard-full` rather than more rows in it, because
        # the two are not the same set. Five task ids are new -- four in group N,
        # plus `precedence_relief` where `hard-full` ran `precedence_chain` -- so
        # the tasks that changed do not silently line up against the tasks they
        # replaced, and the nine that did not change are directly comparable
        # across the two phases. `analyse.py` reads one phase at a time, which is
        # what makes the separation worth keeping rather than merging.
        run("hard-full-2", CANDIDATES_38, ROUNDS, only=hard_set())
    elif cmd == "hard-pilot-3":
        run("hard-pilot-3", [INCUMBENT], ROUNDS, only=hard_set())
    elif cmd == "hard-full-3":
        run("hard-full-3", CANDIDATES_38, ROUNDS, only=hard_set())
    elif cmd == "tutor-pilot":
        # Group T is a separate phase rather than more tasks in `hard-pilot`,
        # because the 40-70% band is read off one overall percentage and these
        # two sets measure different things. Blending "can it hold a lesson
        # protocol across eight turns" into "can it implement a spec" produces a
        # number that calibrates neither, and the band would then be satisfied by
        # a model that is strong at one and hopeless at the other -- which is the
        # precise failure the band exists to catch.
        run("tutor-pilot", [INCUMBENT], ROUNDS, only=tutor_set())
    elif cmd == "tutor-full":
        run("tutor-full", CANDIDATES_38, ROUNDS, only=tutor_set())
    elif cmd == "restore":
        restore()
    else:
        print(__doc__)
        sys.exit(2)
