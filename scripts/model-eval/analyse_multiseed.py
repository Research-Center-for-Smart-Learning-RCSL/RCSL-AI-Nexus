"""Analyse the seed-probe phases: aggregate across seeds to see whether the
q8_0-vs-q4_K_M gap holds or was a fixed-seed artifact."""

from __future__ import annotations

import json
import statistics
import sys

PHASES = [f"seed-probe-{i}" for i in range(1, 6)]
TASKS = ["visible_suffix", "text_wrap_exact", "csv_pipe"]

def main() -> None:
    with open("results.jsonl") as fh:
        rows = [json.loads(line) for line in fh]

    rows = [r for r in rows if r.get("phase") in PHASES]
    if not rows:
        print("No seed-probe rows found in results.jsonl")
        sys.exit(1)

    by: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        key = (r["model"], r["task"])
        by.setdefault(key, []).append(r["score"])

    print(f"{'task':<22} {'model':<28} {'n':>3}  {'mean':>6}  {'stdev':>6}  scores")
    print("-" * 95)

    for task in TASKS:
        for model in sorted({r["model"] for r in rows}):
            scores = by.get((model, task), [])
            if not scores:
                continue
            mean = statistics.mean(scores)
            sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
            vals = " ".join(f"{s:.2f}" for s in scores)
            print(f"{task:<22} {model:<28} {len(scores):>3}  {mean:>6.3f}  {sd:>6.3f}  {vals}")
        print()


if __name__ == "__main__":
    main()
