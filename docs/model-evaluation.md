# Comparing candidate models

**Status: designed 2026-08-14, run 2026-08-15.** The harness is
[`scripts/model-eval/`](../scripts/model-eval/) — committed, unlike the one
behind the previous set — and the results are in [PROGRESS.md](./PROGRESS.md)
2026-08-15. Three candidates, three interleaved rounds, 162 scored samples — 189
written, with a `repair` phase superseding the three tasks it re-ran; the 280 rows
in `results.jsonl` include the two calibration phases, which ran against the
incumbent alone:
`gemma4:31b-it-q8_0` 94.4%, `qwen3.6:35b-a3b-q8_0` 89.8%, `qwen3.6:27b-q8_0`
87.5%. **It separates them, which is the one thing the twelve-task set could not
do**, and the order held across all three rounds.

**Two things below are now known to be wrong, and are left standing with this
note rather than quietly edited.** Section 4's calibration gate failed twice —
the set scored 100% against the incumbent as first written and 94.2% after the
prompts were rewritten to stop signposting their own traps, against a target
band of 40-70%. And section 2's central bet, that a model which pattern-matches
to the canonical algorithm fails where a model that reads passes, held for
exactly one task in eighteen. These models mostly read. A set that lands in the
band is not a better-worded version of this one; see PROGRESS.md 2026-08-15.

This is the instrument, not a conclusion. [ROADMAP.md](./ROADMAP.md) carries the
open decision it is meant to settle.

---

## 1. Why the first set failed

Three candidates were scored on twelve programmatically-checked tasks over three
interleaved rounds:

| | code | exact | total |
|---|---:|---:|---:|
| `gemma4:31b-it-q8_0` | 15/18 | 18/18 | 33/36 (92%) |
| `qwen3.6:27b-q8_0` | 17/18 | 18/18 | 35/36 (97%) |
| `qwen3.6:35b-a3b-q8_0` | 18/18 | 16/18 | 34/36 (94%) |

**Ten of the twelve tasks saturated** — every model passed every round. Two
carried signal: `gemma4` failed the INI parser 0/3, and `35b-a3b` managed the
ordering puzzle 1/3. At 36 samples the totals separate nothing, so the honest
reading was parity, which is the same sentence 2026-08-07 had to write about q4
against q8 and for the same underlying reason: the instrument had no resolution
where the difference lives.

**The diagnosis is not "the tasks were too small".** They were single-step,
fully specified, and shaped like textbook exercises — `merge intervals`,
`topological sort`, `sliding window maximum`. A 27B model of this generation has
seen each of them thousands of times. What was being measured was recall of a
known shape, and recall saturates long before reasoning does.

## 2. What the replacement has to do differently

Six properties, each aimed at a specific way the first set leaked difficulty:

**Deviate from the famous algorithm.** The strongest discriminator available: a
spec that describes a well-known problem and changes exactly one rule. A model
that pattern-matches to the canonical version fails on the one case where they
differ, and a model that reads the spec passes. Nothing about it is obscure, so
a failure is a reading failure rather than a knowledge gap.

**Stack constraints so that dropping one is visible.** Every constraint gets its
own assertion. A task with six requirements and six independent checks produces
a partial score rather than a coin flip, and the constraint most often dropped is
the one stated last.

**Make the plausible answer checkably wrong.** Where a naive approach is correct
but too slow, enforce it with a wall-clock budget in the test. The model is not
being asked to be fast; it is being asked to notice a complexity requirement
that is stated in the prompt.

**Add steps.** A six-step derivation with one unit change in the middle fails if
any single step slips. Error rates compound, which is exactly what a saturating
set lacks.

**Require reading over retrieval.** A five-thousand-token specification with one
internal contradiction is not a needle-in-haystack test — the needle is only
identifiable by holding two distant clauses at once.

**Include tasks whose right answer is a refusal.** A question that cannot be
answered from the data provided, scored by an exact marker. This is the only
category here that measures something the deployment cares about beyond
correctness, and fabrication is invisible to every other task in the set.

## 3. The task set

Sixteen tasks. Every one scores itself: code tasks by running the model's
function against tests it never saw, exact tasks by comparing a normalised final
line against one right answer. Nothing is judged by reading it.

### A — the spec contradicts the famous algorithm

| # | task | the deviation | scored by |
|---|---|---|---|
| 1 | `merge_disjoint` | intervals that merely **touch do not merge**, the opposite of the classic | `(1,3),(3,5)` must stay two intervals |
| 2 | `search_last_rotated` | return the **last** index of a target, in a sorted array **rotated once**, with duplicates | duplicates at the rotation point; absent target returns -1 |

### B — many constraints, one assertion each

| # | task | constraints | the one usually dropped |
|---|---|---|---|
| 3 | `rate_limiter` | sliding window, per key, burst allowance, injected clock, thread safe, **evicts idle keys** | eviction: a correct limiter that leaks memory fails one assertion, not all |
| 4 | `retry_deadline` | exponential backoff, jitter within stated bounds, only listed exceptions, honours a **total deadline** rather than an attempt count, re-raises the last exception, **does not sleep after the final attempt** | the trailing sleep, observable because the clock is injected |

### C — a complexity requirement, enforced

| # | task | input | why the naive answer fails |
|---|---|---|---|
| 5 | `count_inversions` | 200,000 elements | O(n²) is correct and exceeds the test's wall-clock budget |
| 6 | `range_sum_updates` | 10⁵ point updates interleaved with 10⁵ range queries | recomputing per query is correct and times out |

### D — the bug is two levels from the symptom

| # | task | the trap |
|---|---|---|
| 7 | `cache_decorator` | a memoiser that caches raised exceptions and shares one mutable default; the failing test names the caller |
| 8 | `pagination_boundary` | drops the final page when the total is an exact multiple of the page size; given failing output, the source must change and the test must not |

### E — one contradiction across a long specification

| # | task | scored by |
|---|---|---|
| 9 | `spec_contradiction` | ~4,500 tokens of numbered clauses, exactly two of which conflict; answer is the two clause ids, sorted |
| 10 | `spec_precedence` | same document, a described scenario, answer is the single governing clause id |

### F — the right answer is a refusal

| # | task | scored by |
|---|---|---|
| 11 | `insufficient_data` | a question the given data cannot answer; only an exact marker passes, so any confident number fails |
| 12 | `ambiguous_requirement` | a code spec with a genuine ambiguity; naming it with the marker passes, silently picking a reading fails |

### G — multi-hop arithmetic with a unit change

| # | task | the step that breaks it |
|---|---|---|
| 13 | `capacity_chain` | six steps with one GiB/GB conversion in the middle and one percentage taken of a percentage |
| 14 | `retention_window` | a month boundary, a timezone offset and a policy ceiling, in that order |

### H — structured output with interdependent fields

| # | task | scored by |
|---|---|---|
| 15 | `policy_json` | totals must equal the sum of their parts, dates must be ordered, one field required only when another is present |
| 16 | `csv_reconcile` | two small tables joined, with a computed delta, emitted under exact keys |

### Anchors

`ini_parse` and `logic_order` were the only two tasks in the first set that
discriminated, and were meant to make the two sets comparable rather than merely
sequential. **They are not carried over; they are reconstructed.** The twelve-task
harness was never committed, so both were rebuilt from the prose description in
PROGRESS.md and are two more tasks rather than a bridge. The bridge between the
two sets is gone, and this set cannot rebuild it.

## 4. Calibration, before any candidate is compared

The first set was not piloted, which is why its saturation was discovered from
the results rather than before them.

**Run 2026-08-15, and rule 1 was the one that paid.** Validating the scorer in
both directions caught two defects before a model ran: `logic_order` admitted
four orderings with the answer key among none of them, and the naive
`range_sum_updates` answer completed in 1.2 s, so the complexity requirement in
rule C was not being enforced at all. Both would have produced numbers. Rules 3
and 4 were not met and could not be met by editing wording — see the status note
at the head of this document.

1. **Validate the scorer in both directions.** Reference solutions must pass and
   deliberately wrong answers must fail, for every task, before a model runs. A
   scorer that accepts a wrong answer is worse than no measurement.
2. **Pilot against the incumbent only**, three samples per task.
3. **Target band: 40–70% overall for `gemma4:31b-it-q8_0`.** Above it the set
   will saturate again; below it, differences drown in the failure rate.
4. **Replace any task that returns 3/3 or 0/3 for every candidate.** It carries
   no signal whatever its difficulty, and a set of them is what produced the
   92/97/94 that settled nothing.

## 5. Harness requirements

Each of these was paid for by a wrong result, and every one produced numbers that
looked like findings.

**Deliberation off, and stated.** All three candidates emit reasoning into a
separate field. At `num_predict` 900 the reasoning alone exhausted the budget,
`done_reason` came back `length`, and `response` was empty — scoring an empty
string is scoring the budget, and it read as both Qwen candidates failing every
code task. `think: False` matches the `code` policy this deployment already runs.
A second condition with deliberation *on* is worth running separately, and is not
the same experiment.

**Truncation is not a wrong answer.** A response that hit the length cap without
producing an answer must return no result. Without that rule the same defect
reappears as a zero, and a zero looks like a measurement.

**A budget several times the expected answer.** So that a model which ignores the
deliberation flag is not silently truncated instead.

**Quantisation matched.** All candidates at q8. 2026-08-07 recorded a "stronger
than glm" conclusion invalidated by comparing q4 against q8, and it is the
easiest mistake to repeat.

**Order rotated per round, several samples per task.** PROGRESS 2026-08-13
imported the rule: apparent 15–100% swings vanished under interleaved ordering.
One roll of a sampler is not a capability.

**Every figure carries its `num_ctx` and measured prompt depth.** Generation rate
decays with context — `config.py` records 60.8 to 23.5 tok/s across a single
generation — so a number without its depth cannot be compared with another one.
That is what made the 2026-08-07 table's `61.0` and `13.6` incomparable.

**Restore the deployment afterwards, largest model first.** Loading a candidate
evicts what is serving. Restoring smallest-first means the large model evicts
what was just restored, and the embedder must be reloaded through `/api/embed`
rather than `/api/generate`, which is a 400 for an embedding model.

## 6. What this still will not answer

The same boundary the ten-rung agent harness stops at: whether the work is any
good. Eighteen checkable tasks measure whether a model can follow a specification
it has not memorised. They do not measure whether its code is worth reading, and
2026-08-07 already recorded that real work is the only instrument left for that.
