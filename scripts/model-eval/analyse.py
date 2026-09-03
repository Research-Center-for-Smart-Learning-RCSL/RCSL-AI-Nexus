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


def _label(model: str) -> str:
    """A column head that separates two builds of the same model.

    It was `model.split(":")[0][:11]`, the family alone, which is unreadable the
    moment a phase carries more than one build of it: the 2026-09-02 `qwen38`
    read printed `qwen3.8` over three different columns, and `full` before it
    printed `qwen3.6` over two. The tag is what distinguishes them, so the tag is
    what the head shows, keeping enough of the family to say which model it is.
    """
    family, _, tag = model.partition(":")
    return (tag or family)[:12]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def outcome(r: dict) -> str:
    """The sample's third-outcome label, derived for rows written before it existed.

    `sample.py` records `outcome` directly from 2026-09-03. Phases recorded
    before that carry only the `no_result` sentence, so the label is recovered
    from it here rather than leaving every earlier phase unreadable by the
    reports below -- which would defeat the point of separating the outcome at
    all, since the reading it exists to settle is a 2026-09-02 one.
    """
    if r.get("outcome"):
        return r["outcome"]
    if r.get("score") is not None:
        return "scored"
    note = r.get("no_result") or ""
    if note.startswith("truncated"):
        return "truncated_no_answer"
    if note.startswith("empty"):
        return "empty"
    if note.startswith("transport"):
        return "transport_error"
    return "no_result"


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

    # ------------------------------------------------- the two truncation reads
    # Section 5's rule excludes a truncated-without-answer sample from the mean.
    # On 2026-09-02 that rule was found to cut the other way with deliberation
    # off, and both readings had to be published by hand because choosing one
    # after seeing which way it cut is the worse error. Printing them together
    # is what stops that being a hand computation: the left column is the
    # recorded rule, the right column is the same samples scored 0, and the gap
    # between them is exactly how much of a model's figure rests on the choice.
    trunc_rows = [r for r in rows if outcome(r) == "truncated_no_answer"]
    if trunc_rows:
        print(f"\n=== {phase}: truncated without an answer, both readings ===\n")
        print(f"{'model':26s} {'excluded':>10s} {'scored 0':>10s} {'delta':>8s} "
              f"{'samples':>8s}")
        print("-" * 66)
        for m in models:
            rs = [r for r in rows if r["model"] == m]
            kept = [r["score"] for r in rs if r["score"] is not None]
            n_tr = sum(1 for r in rs if outcome(r) == "truncated_no_answer")
            excl = mean(kept)
            zeroed = mean(kept + [0.0] * n_tr)
            if excl is None:
                continue
            print(f"{m:26s} {excl*100:9.1f}% {zeroed*100:9.1f}% "
                  f"{(zeroed-excl)*100:7.1f} {n_tr:8d}")
        worst = defaultdict(int)
        for r in trunc_rows:
            worst[r["task"]] += 1
        ranked = ", ".join(f"{t} ({n})" for t, n in
                           sorted(worst.items(), key=lambda kv: -kv[1]))
        print(f"\nby task: {ranked}")
        # Deliberation off means the budget went on prose rather than on
        # reasoning, which is the model not following the output instruction.
        # With it on, the same rows would be the case section 5 wrote the rule
        # for. The distinction is in the data, so it is reported rather than
        # argued.
        with_think = sum(1 for r in trunc_rows if (r.get("thinking_chars") or 0) > 0)
        print(f"of those, {with_think} had any thinking output and "
              f"{len(trunc_rows)-with_think} had none")

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
    print(f"{'grp':4s} {'task':24s} " + " ".join(f"{_label(m):>12s}" for m in models)
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
    # 4.4 replaces a task that carries no signal *across the candidates*. With one
    # model on the bench that test cannot be run, and calling the result saturation
    # would be the same overreach as reading one model's score as a comparison.
    scope = "every candidate" if len(models) > 1 else f"the one model here ({models[0]})"
    print(f"\nalways 1.00 for {scope}: {', '.join(saturated_high) or 'none'}")
    print(f"always 0.00 for {scope}: {', '.join(saturated_low) or 'none'}")
    print(f"carries signal: {', '.join(discriminating) or 'none'}")
    n_sat = len(saturated_high) + len(saturated_low)
    if len(models) > 1:
        print(f"\n{n_sat} of {len(tasks)} tasks carry no signal and are replaceable under 4.4")
    else:
        print(f"\n{n_sat} of {len(tasks)} tasks were never missed by this model. That is the 4.3 "
              f"band read;\nthe 4.4 replacement test needs the other candidates on the bench.")

    # ------------------------------------------------ what a dialogue lost, and where
    # A single percentage over a conversation cannot be acted on. "Held its system
    # prompt but drifted on formatting" and "was talked into the answer" are
    # different findings with different consequences for a deployment, and they
    # average to the same number. The check names carry the property, so they are
    # aggregated by name across every turn and every round.
    #
    # The turn breakdown beside it is the one that answers whether adherence
    # decays: the same checks are applied at turn 8 as at turn 1, so a falling
    # column is instruction-following wearing off over a conversation rather than
    # a model that never had the rule.
    dialogue_rows = [r for r in rows if r.get("kind") == "dialogue"]
    if dialogue_rows:
        print(f"\n=== {phase}: dialogue, by property (all turns, all rounds) ===\n")
        for m in models:
            per_prop = defaultdict(lambda: [0, 0])
            per_turn = defaultdict(lambda: [0, 0])
            for r in dialogue_rows:
                if r["model"] != m:
                    continue
                for label, ok, _ in r.get("detail", []):
                    turn, _, name = str(label).partition(":")
                    per_prop[name][1] += 1
                    per_turn[turn][1] += 1
                    if ok:
                        per_prop[name][0] += 1
                        per_turn[turn][0] += 1
            if not per_prop:
                continue
            print(f"{m}")
            for name, (ok, n) in sorted(per_prop.items(), key=lambda kv: kv[1][0] / kv[1][1]):
                bar = "#" * int(round(20 * ok / n))
                print(f"    {name:34s} {ok:3d}/{n:3d} {100*ok/n:5.1f}%  {bar}")
            order = sorted(per_turn.items(), key=lambda kv: int(kv[0][1:] or 0))
            shown = "  ".join(f"{t}:{100*ok/n:3.0f}%" for t, (ok, n) in order)
            print(f"    by turn -> {shown}\n")

    # --------------------------------------------------- code that never ran
    # A candidate whose file does not import scores zero on every check, which
    # looks identical to a candidate that answered badly. Counted separately so
    # a syntax slip is not read as an inability to do the task.
    loadfail = defaultdict(list)
    for r in rows:
        for _, passed, msg in r.get("detail", []):
            if not passed and msg.startswith("did not load"):
                loadfail[r["model"]].append((r["task"], r["round"]))
                break
    n_code = sum(1 for r in rows if r["kind"] == "code")
    if loadfail:
        print(f"\n=== {phase}: candidates whose code did not import "
              f"({sum(len(v) for v in loadfail.values())} of {n_code} code samples) ===\n")
        for m, hits in loadfail.items():
            shown = ", ".join(f"{t} r{rd}" for t, rd in hits)
            print(f"  {m:26s} {shown}")

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
