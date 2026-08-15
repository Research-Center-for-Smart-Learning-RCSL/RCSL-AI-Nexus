"""Read results.jsonl and print the tables.

  python3 analyse.py pilot     the calibration read: overall band, saturation
  python3 analyse.py full      the comparison read

Every figure carries its num_ctx and its measured prompt depth (5), because a
generation rate without a depth cannot be compared with another one.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.jsonl")


def load(phase: str) -> list[dict]:
    out = []
    with open(RESULTS) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("phase") == phase:
                out.append(r)
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def main(phase: str) -> None:
    rows = load(phase)
    if not rows:
        print(f"no {phase} samples yet")
        return

    models = sorted({r["model"] for r in rows})
    tasks = []
    for r in rows:
        if r["task"] not in tasks:
            tasks.append(r["task"])
    groups = {r["task"]: r["group"] for r in rows}

    by = defaultdict(list)
    for r in rows:
        by[(r["model"], r["task"])].append(r)

    # ------------------------------------------------------------- headline
    print(f"=== {phase}: overall ===\n")
    print(f"{'model':26s} {'score':>8s} {'scored':>7s} {'no result':>10s} "
          f"{'gen tok/s':>10s} {'depth':>7s} {'s/task':>8s}")
    print("-" * 82)
    for m in models:
        rs = [r for r in rows if r["model"] == m]
        scored = [r for r in rs if r["score"] is not None]
        pct = mean([r["score"] for r in scored])
        gens = [r["gen_tok_s"] for r in rs if r.get("gen_tok_s")]
        depths = [r["prompt_eval_count"] for r in rs if r.get("prompt_eval_count")]
        walls = [r["wall_s"] for r in rs if r.get("wall_s")]
        print(f"{m:26s} {pct*100:7.1f}% {len(scored):7d} {len(rs)-len(scored):10d} "
              f"{mean(gens) or 0:10.1f} {int(mean(depths) or 0):7d} {mean(walls) or 0:8.1f}")

    # ------------------------------------------------------- per round wall
    print(f"\n=== {phase}: wall clock per round (inference only) ===\n")
    for m in models:
        per = defaultdict(float)
        for r in rows:
            if r["model"] == m:
                per[r["round"]] += r.get("wall_s") or 0
        shown = "  ".join(f"r{k}: {v:6.0f}s" for k, v in sorted(per.items()))
        print(f"{m:26s} {shown}")

    # ------------------------------------------------------------- by group
    print(f"\n=== {phase}: by group ===\n")
    gs = sorted({groups[t] for t in tasks})
    print(f"{'model':26s} " + " ".join(f"{g:>7s}" for g in gs))
    print("-" * (26 + 8 * len(gs)))
    for m in models:
        cells = []
        for g in gs:
            vals = [r["score"] for r in rows
                    if r["model"] == m and groups[r["task"]] == g and r["score"] is not None]
            cells.append(f"{mean(vals)*100:6.0f}%" if vals else "     --")
        print(f"{m:26s} " + " ".join(cells))

    # -------------------------------------------------------------- by task
    print(f"\n=== {phase}: by task (mean of samples, and the spread) ===\n")
    print(f"{'grp':4s} {'task':24s} " + " ".join(f"{m.split(':')[0][:11]:>12s}" for m in models)
          + "   verdict")
    print("-" * (30 + 13 * len(models) + 12))
    saturated_high, saturated_low, discriminating = [], [], []
    for t in tasks:
        cells, means = [], []
        for m in models:
            rs = by[(m, t)]
            vals = [r["score"] for r in rs if r["score"] is not None]
            if not vals:
                cells.append("          --")
                means.append(None)
                continue
            means.append(mean(vals))
            cells.append(f"{mean(vals)*100:6.0f}% ({len(vals)})")
        got = [x for x in means if x is not None]
        if got and all(x == 1.0 for x in got):
            verdict = "SATURATED high"
            saturated_high.append(t)
        elif got and all(x == 0.0 for x in got):
            verdict = "SATURATED low"
            saturated_low.append(t)
        elif got and (max(got) - min(got)) >= 0.15:
            verdict = "discriminates"
            discriminating.append(t)
        else:
            verdict = ""
        print(f"{groups[t]:4s} {t:24s} " + " ".join(cells) + f"   {verdict}")

    # ------------------------------------------------------------ calibration
    print(f"\n=== {phase}: calibration (4.3, 4.4) ===\n")
    for m in models:
        scored = [r["score"] for r in rows if r["model"] == m and r["score"] is not None]
        pct = mean(scored) * 100
        band = "in the 40-70% band" if 40 <= pct <= 70 else (
            "ABOVE the band - the set will saturate again" if pct > 70
            else "BELOW the band - differences drown in the failure rate")
        print(f"{m:26s} {pct:5.1f}%  {band}")
    print(f"\nsaturated high (every candidate, every sample): "
          f"{', '.join(saturated_high) or 'none'}")
    print(f"saturated low  (every candidate, every sample): "
          f"{', '.join(saturated_low) or 'none'}")
    print(f"carries signal: {', '.join(discriminating) or 'none'}")
    n_sat = len(saturated_high) + len(saturated_low)
    print(f"\n{n_sat} of {len(tasks)} tasks carry no signal and are replaceable under 4.4")

    # ------------------------------------------------------------ no results
    bad = [r for r in rows if r["score"] is None]
    if bad:
        print(f"\n=== {phase}: samples that returned no result ({len(bad)}) ===\n")
        for r in bad:
            print(f"  {r['model']:26s} {r['task']:24s} r{r['round']}  {r.get('no_result')}")
    trunc = [r for r in rows if r.get("truncated_but_scored")]
    if trunc:
        print(f"\nscored despite hitting num_predict: {len(trunc)}")
        for r in trunc:
            print(f"  {r['model']:26s} {r['task']:24s} r{r['round']}  score={r['score']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pilot")
