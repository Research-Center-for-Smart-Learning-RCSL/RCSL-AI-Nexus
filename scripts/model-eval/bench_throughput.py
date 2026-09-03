"""Generation and prompt-evaluation rate for one model, at a stated depth.

`analyse.py` reports throughput as a by-product of scoring eighteen tasks, which
takes a round of ten to twenty minutes per model and cannot be pointed at a
model the task set has never been run against. This asks the narrower question
on its own: how fast does this model produce tokens on this machine, and how
fast does it read them.

**The figure it has to agree with.** `results.jsonl` puts `gemma4:31b-it-q8_0`
between 13.57 and 13.83 gen tok/s on every one of the sixteen tasks whose depth
is under 400, and at 12.71-12.78 on the two near 4400 — flat within a task and
flat across depth, which is what a memory-bandwidth-bound dense model looks
like. The `depth ~710` in `analyse.py`'s table is the mean depth over all
eighteen, not a depth any prompt actually had, so it is not a target to
reproduce; 13.65 at shallow depth is. A bench that cannot recover that number
against the incumbent is not measuring what it claims to.

**`keep_alive` is sent on every call, and that is not a detail.** Ollama applies
its own five-minute default to any request that omits the field, so benchmarking
a resident model without it silently replaces the `-1` that the platform's load
asked for — the deployment's pin would survive this script by five minutes.
`.env` states the same rule for `OLLAMA_KEEP_ALIVE`. Pass `--keep-alive -1` for
a model the deployment is serving and `--keep-alive 0` for a candidate, which
unloads it as the last generation ends rather than leaving 18 GB resident.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

from harness_parts.client import OLLAMA

# One paragraph of prose with no structure a model would want to continue,
# repeated to depth. Deterministic, so two runs of this script send the same
# bytes; the achieved depth is reported rather than assumed, because the token
# count of the same text differs per vocabulary.
FILLER = (
    "The maintenance record for the northern substation lists the transformer "
    "inspections carried out during the quarter, the readings taken at each "
    "visit, and the name of the technician who signed the entry. Readings are "
    "recorded in the order they were taken rather than sorted, and a blank "
    "field means the gauge was unreachable that day rather than that the value "
    "was zero. "
)

QUESTION = (
    "\n\nIgnore the record above; it is padding. Write a short paragraph "
    "explaining, in plain prose, why a queue that drops its oldest entry under "
    "load behaves differently from one that refuses its newest. Do not use "
    "lists or code."
)


def post(path: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def build_prompt(target_depth: int, nonce: int, tokens_per_word: float = 1.09) -> str:
    """Roughly `target_depth` tokens of filler, at `tokens_per_word` per word.

    The default is measured rather than assumed: on this filler against gemma4's
    vocabulary, 5,866 words came to 6,407 tokens and 163,840 words to about
    179,200. The 0.75 this started at undershot by 45%, which at a target of
    122,880 built a prompt of ~179,000 -- past Ollama's num_ctx/2 truncation
    point, so it measured a case the platform refuses rather than the ceiling it
    allows. The ratio is a property of the vocabulary, so the achieved depth is
    always reported and the target never trusted.

    **The nonce leads, and that is the whole reason it exists.** Ollama caches
    the evaluated prefix of a prompt, so sending the same text twice makes the
    second call skip prompt evaluation and report a `prompt_eval_duration` near
    zero: three repetitions of one prompt measured 2110, then 69500 prompt tok/s
    on a machine whose real figure is three digits. A prefix that differs per
    repetition costs nothing and makes every repetition a cache miss, which is
    the case the deployment's worst-case arithmetic is about — an agent sending
    a conversation it has extended is not re-sending a prefix unchanged either.
    """
    words_needed = int(target_depth / tokens_per_word)
    words = FILLER.split()
    repeats = max(1, words_needed // len(words) + 1)
    body = " ".join((words * repeats)[:words_needed])
    return f"Record {nonce:d}-{nonce * 7919:d}. {body}{QUESTION}"


def failure_detail(exc: Exception) -> str:
    """What an Ollama refusal actually said, when it said anything."""
    if hasattr(exc, "read"):
        return exc.read()[:400].decode("utf-8", "replace")
    return str(exc)


def parse_keep_alive(raw: str) -> int | str:
    """`-1` and `0` must reach Ollama as JSON numbers, not strings.

    Ollama parses a string `keep_alive` as a Go duration, where `"-1"` is
    `time: missing unit in duration "-1"` and the request fails before it
    generates. A bare number is seconds, with -1 meaning until something says
    otherwise. Durations such as `45m` are still strings and still work.
    """
    try:
        return int(raw)
    except ValueError:
        return raw


def one(model: str, prompt: str, num_ctx: int, num_predict: int,
        keep_alive: int | str, timeout: int) -> dict:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict},
    }
    t0 = time.time()
    data = post("/api/generate", body, timeout)
    gen_ns = data.get("eval_duration") or 0
    pe_ns = data.get("prompt_eval_duration") or 0
    return {
        "depth": data.get("prompt_eval_count") or 0,
        "out": data.get("eval_count") or 0,
        "gen_tok_s": (data.get("eval_count") or 0) / (gen_ns / 1e9) if gen_ns else None,
        "prompt_tok_s": (data.get("prompt_eval_count") or 0) / (pe_ns / 1e9) if pe_ns else None,
        "wall_s": time.time() - t0,
        "done_reason": data.get("done_reason"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--depths", default="300,4400",
                    help="comma-separated target prompt depths in tokens")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--num-ctx", type=int, default=16384,
                    help="matches harness_parts/client.py, so figures compare")
    ap.add_argument("--num-predict", type=int, default=256)
    ap.add_argument("--keep-alive", default="0",
                    help="-1 for a model the deployment is serving, 0 for a candidate")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--tokens-per-word", type=float, default=1.09,
                    help="filler-to-token ratio; per vocabulary, see build_prompt")
    ap.add_argument("--skip-depth-warm", action="store_true",
                    help="skip the discarded call per depth. Safe only when the "
                         "model is already resident at this num_ctx, and worth it "
                         "when one call costs ten minutes")
    ap.add_argument("--warmup", action="store_true",
                    help="one discarded call first, so a cold load is not timed")
    args = ap.parse_args()

    depths = [int(d) for d in args.depths.split(",")]
    keep_alive = parse_keep_alive(args.keep_alive)
    print(f"model={args.model} num_ctx={args.num_ctx} num_predict={args.num_predict} "
          f"keep_alive={keep_alive!r} reps={args.reps}")

    if args.warmup:
        print("  warmup ...", end="", flush=True)
        t0 = time.time()
        try:
            one(args.model, "ok", args.num_ctx, 8, keep_alive, args.timeout)
        except (urllib.error.HTTPError, OSError) as exc:
            detail = failure_detail(exc)
            print(f" FAILED: {detail}")
            return 1
        print(f" {time.time()-t0:.1f}s")

    print(f"\n{'depth':>7s} {'gen tok/s':>11s} {'prompt tok/s':>13s} {'out':>6s} {'wall s':>8s}")
    summary = []
    for target in depths:
        # One discarded call at this depth first. Ollama keys a loaded instance
        # by its options, so the first call at a num_ctx the model is not
        # resident at pays a reload -- 195 prompt tok/s against a real 2100 in
        # the run that found this. The reload belongs to the bench, not to the
        # model.
        if not args.skip_depth_warm:
            try:
                one(args.model, build_prompt(target, 0, args.tokens_per_word),
                    args.num_ctx, 8, keep_alive, args.timeout)
            except (urllib.error.HTTPError, OSError) as exc:
                detail = failure_detail(exc)
                print(f"  FAILED warming target depth {target}: {detail}")
                return 1
        runs = []
        for rep in range(args.reps):
            prompt = build_prompt(target, rep + 1, args.tokens_per_word)
            try:
                r = one(args.model, prompt, args.num_ctx, args.num_predict,
                        keep_alive, args.timeout)
            except (urllib.error.HTTPError, OSError) as exc:
                detail = failure_detail(exc)
                print(f"  FAILED at target depth {target}: {detail}")
                return 1
            runs.append(r)
            print(f"{r['depth']:7d} {r['gen_tok_s'] or 0:11.2f} "
                  f"{r['prompt_tok_s'] or 0:13.1f} {r['out']:6d} {r['wall_s']:8.1f}")
        med_gen = statistics.median(r["gen_tok_s"] or 0 for r in runs)
        med_pe = statistics.median(r["prompt_tok_s"] or 0 for r in runs)
        summary.append((runs[0]["depth"], med_gen, med_pe))
        print(f"  -> median {med_gen:.2f} gen tok/s, {med_pe:.1f} prompt tok/s "
              f"at depth {runs[0]['depth']}")

    print(f"\n{args.model}")
    for depth, gen, pe in summary:
        print(f"  depth {depth:5d}: {gen:7.2f} gen tok/s  {pe:9.1f} prompt tok/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
