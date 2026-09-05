# Comparing candidate models

**A third task set replaced this one on 2026-09-03 and is described in section
7; five of its tasks were themselves replaced on 2026-09-04 and that revision,
with the run that reversed section 7's conclusion, is section 8.** Everything
above section 7 is the eighteen-task set: still in the harness, still runnable,
and still the only thing the `full`, `repair` and `qwen38` phases can be read
against. It saturated twice and section 7 says what was done about it.

**Section 7 is left standing with forward notes rather than edited into
agreement with section 8**, for the same reason the two wrong claims further
down this header are left standing: what was concluded from `hard-full`, and on
what evidence, is the thing a reader needs in order to judge whether section 8's
reversal is credible.

**Status: designed 2026-08-14, run 2026-08-15, run again 2026-09-02 against a
fourth candidate in three builds.** The harness is
[`scripts/model-eval/`](../scripts/model-eval/) — committed, unlike the one
behind the previous set — and the results are in [PROGRESS.md](./PROGRESS.md)
2026-08-15. Three candidates, three interleaved rounds, 162 samples of which 159
scored — 189 written, with a `repair` phase superseding the three tasks it re-ran;
the 280 rows in `results.jsonl` include the two calibration phases, which ran
against the incumbent alone:
`gemma4:31b-it-q8_0` 94.4%, `qwen3.6:35b-a3b-q8_0` 89.8%, `qwen3.6:27b-q8_0`
87.5%. **It separates them, which is the one thing the twelve-task set could not
do**, and the order held across all three rounds.

**Three of those figures were re-run rather than kept.** `retry_deadline`,
`rate_limiter` and `range_sum_updates` carried a `def f(...): ...` stub in the
prompt; `qwen3.6:27b-q8_0` copied the stub and indented a body under it in all
three rounds of `retry_deadline`, scoring 0.00 on an `IndentationError` — a
measurement of this repository's prompt formatting, not of the retrying the task
asks about. The stub is gone from all three, and the three were re-run for every
candidate under a `repair` phase which supersedes `full` task by task. Reading
the file any other way restores the defect: `full` alone puts `qwen3.6:27b-q8_0`
at 81.9%, and concatenating both phases without letting the later one win puts it
at 83.5%, against its real 87.5%.

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

**The switch this settled was made on 2026-08-16 and reversed on 2026-08-21**,
and nothing recorded the reversal, so for twelve days this page described a
deployment that had gone back to `gemma4:31b-it-q8_0`. It still serves `chat`
and `code` today. **A fourth candidate was put through this set on 2026-09-02
and did not clear the bar.** Qwen 3.8 27B, released after these three were
scored, was run in three builds with the incumbent re-run as a control — 216
samples, three interleaved rounds, Ollama 0.33.2:

| | score | s/task | gen tok/s |
|---|---:|---:|---:|
| `gemma4:31b-it-q8_0` *(serving)* | **93.4%** | **33.3** | 13.8 |
| `qwen3.8:27b-q4_K_M` | 89.1% | 39.0 | 23.1 |
| `qwen3.8:27b-q8_0` | 89.0% | 60.8 | 15.5 |
| `qwen3.8:27b-mlx` | 84.9% | 16.5 | 65.4 |

The incumbent reproduces its own figure two runtime versions later and is not
beaten by any build. **The q8 arm was run only to satisfy section 5** and is
what makes the result readable: the gap to the MLX build is 4.4 points of model
and 4.1 of quantisation, so the build the stopwatch favoured is the one that
lost the most capability. **And the stopwatch's own argument inverts on this
set**: two of the three candidates take *longer* to reach an answer than the
incumbent despite higher tokens per second, because Qwen 3.8 writes more per
answer — which is the difference between measuring a rate and measuring a task,
and the reason this page exists. The ten agent-loop rungs were not run.
([PROGRESS.md](./PROGRESS.md) 2026-09-02.)

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

**That rule cuts the other way once deliberation is off, found 2026-09-02.** All
three Qwen 3.8 builds ran out a 4,096-token budget on `spec_contradiction`
without emitting an answer, in two rounds of three each, with `think` off and
`thinking_chars` zero — so the budget went on prose rather than on reasoning,
and failing to reach an answer is the model not following the output
instruction rather than the harness measuring itself. Excluding those samples
credits a candidate for a task it could not finish: scoring them 0 moves the
three builds down 3.3 to 4.9 points and the incumbent, which truncated nothing,
not at all. It also makes `analyse.py` call `spec_contradiction` **SATURATED
high** off the one sample in three that survived. The rule was kept for that run
because changing it after seeing which way it cuts is the worse error, and both
readings were published side by side. What it needs is a third outcome —
truncated-without-answer counted separately from both scored and no-result —
rather than a choice between the two it has.

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

---

## 7. The 2026-09-03 set, and what the eighteen could not be asked

**Designed and run 2026-09-03.** Twelve new tasks in seven groups plus three
carried unchanged from the set above, in `scripts/model-eval/task_families/hard_*.py`;
phases `hard-pilot` (calibration), `hard-full` (four candidates, three
interleaved rounds, 180 samples, 14,824 seconds) and `tutor-pilot`. Fifteen
tasks carrying **110 independent scoring units** against the eighteen-task set's
eighteen. Evidence in [PROGRESS.md](./PROGRESS.md) 2026-09-03.

**It does not re-word section 2's bet, because that bet was measured and lost.**
Section 2 rested on a spec that deviates from a famous algorithm separating a
model that reads from one that pattern-matches; it held for one task in
eighteen. Reading the `qwen38` figures per task rather than in total, the one
mechanism with teeth was dense interacting boundary rules, and the property the
whole set lacked was compounding error — every task was single-shot. This set
builds on the first and adds the second.

### 7.1 What it measures, by §4.4 verdict

**Re-measured 2026-09-04 after five of these tasks were replaced; §8.1 carries
the current verdicts.** Eight of fifteen carry signal there against the seven
below.

| | tasks |
|---|---|
| **carries signal** | `visible_suffix`, `text_wrap_exact`, `vm_implement`, `config_merge`, `duration_grammar`, `search_last_rotated`, `ini_parse` |
| **saturated high** | `count_inversions`, and all four of group N |
| **saturated low** | `vm_trace`, `ledger_replay`, `precedence_chain` |

Seven of fifteen carry signal, against the eighteen-task set's seven of
eighteen. That is the whole of the improvement, and it is a modest one.

### 7.2 A single-model pilot cannot judge a task, and this is the measurement of that

The calibration pilot put the incumbent at **83.3%** with ten of fifteen tasks
at 1.00, which read as a failed set and was reported as one. Four of those ten —
`config_merge`, `visible_suffix`, `vm_implement`, `text_wrap_exact` — separate
the four candidates once they are on the bench. Acting on the pilot's verdict
would have discarded four working tasks on the evidence of the one model that
aces them.

§4.4 already says the replacement test is across candidates, and `analyse.py`
already prints that a single-model phase cannot run it. `ini_parse` is the
standing precedent: 1.00 for the incumbent in both runs and 0.25–0.54 for every
Qwen build, while being the widest discriminator either set has produced. **A
task the incumbent aces is not evidence of anything until the other candidates
have tried it**, and §4.2's pilot is therefore a calibration of difficulty and
never a judgement on a task.

### 7.3 The result, and the reading that does not decide it

**This section's conclusion did not survive replacing the tasks that carried no
signal. See §8.2: on the same four candidates the incumbent finishes last, on
both truncation readings.** What follows is what `hard-full` measured and is
accurate for that set.

| | whole set, excluded | whole set, truncated scored 0 | seven signal tasks |
|---|---:|---:|---:|
| `gemma4:31b-it-q8_0` *(serving)* | 76.5% | **76.5%** | **92.4%** |
| `qwen3.8:27b-mlx` | **85.0%** | 71.8% | 82.4% |
| `qwen3.8:27b-q4_K_M` | 79.2% | 68.6% | 75.6% |
| `qwen3.8:27b-q8_0` | 76.0% | 65.9% | 69.8% |

The two whole-set readings name different winners — §5's exclusion rule was
worth 3.3 to 4.9 points on 2026-09-02 and changed no ordering; here it is worth
13.2 and inverts the result. Nineteen samples returned nothing, all of them on
Qwen builds, the incumbent none in forty-five.

**The dispute does not reach the ranking, because all nineteen fall on the three
tasks that separate nobody.** The seven signal tasks produced no truncations at
all, and on them the order is unambiguous and the incumbent is ahead by ten
points — the fourth run running, and the first whose conclusion does not rest on
the contested rule. The whole-set figure is an average over eight tasks that
carry nothing.

### 7.4 The anchors, and the bridge both earlier sets recorded losing

`ini_parse`, `search_last_rotated` and `count_inversions` are carried as the same
code, the same prompts and the same checks that produced the `qwen38` figures —
a real carry rather than the reconstruction section 3 had to settle for.
`count_inversions` is 100% for all four models in both runs, which is what makes
it the control on the harness rather than on the model: this phase raised the
output budget, and a task with a known ceiling says the scorer beneath it did
not move. `ini_parse` reproduces exactly where the comparison lives — incumbent
100.0% in both runs, `27b-q8_0` 54.2% in both.

This is the first time a score in one task set here can be compared against a
score in another.

**Both anchor claims in this subsection were falsified on 2026-09-04, and by the
same cause.** `ini_parse` did not reproduce a third time — the incumbent 79.2%
and `27b-q8_0` 33.3%, against the 100.0% and 54.2% recorded twice above — and
`count_inversions` was not 1.00, scoring 0.80 in three of four samples. Neither
is an environmental drift: generation rate is identical across all three phases
to within a decimal, and the Ollama plist predates all of them.

The cause is that **the harness has never pinned a sampling temperature.**
`client.py` sends `num_ctx` and `num_predict` and nothing else, so every sample
is drawn at the model's own Modelfile default — `temperature 1` for the
incumbent. §5's "one roll of a sampler is not a capability" was written against
ordering effects; three rolls at temperature 1 are not a capability either.
"Carried as the same code, the same prompts and the same checks" remains true
and is what makes these tasks a bridge. "The number recurs" does not, and only
the first was ever demonstrated. `count_inversions` in particular cannot serve
as a control on the harness: its failing check is a `RecursionError` from a
genuine empty-list defect in the model's code, which is the scorer working. See
PROGRESS.md 2026-09-04.

### 7.5 Group T: the education agent, which a single prompt cannot ask

Four scripted conversations, 141 checks, `kind: "dialogue"`. The model's own
replies are fed back as history, so a tutor that leaks at turn three answers
turn four with the leak in its context. Scoring stays programmatic: the system
prompt under test requires a `NEXT: <step>` trailer, so "does it still know
which step it is on" is a string comparison rather than a judgement. One turn in
the bypass scenario is a control on which refusing is the failure, for the same
reason group N exists.

**The incumbent scored 100%** — twelve samples, 423 check evaluations, 27
properties, and no decay from turn one to turn ten. It ignored a forged
`SYSTEM:` line, declined a confirmation probe, and still answered the student
who genuinely did not understand the question. That is a saturated instrument
and a real answer to the question the platform has.

### 7.6 What is open

**The first three were acted on 2026-09-04 and §8 records what happened. They
are left as written, because two of the three predictions in them turned out to
be wrong in instructive ways.**

- The five saturated-high tasks are replaceable under §4.4. Group N's clean
  sweep is itself a finding worth keeping: every candidate answered all four
  matched determined/undetermined questions correctly, where the eighteen-task
  set's `insufficient_data` scored 0.00 for seven models across three families.
  The likelier reading is that these undetermined questions are less subtle,
  not that the fabrication finding is overturned.
  → **Right, and now demonstrated.** All four were replaced. The new
  `undetermined_seats` puts the incumbent at 0.00 in all three samples here and
  all three of the calibration phase before it, while `27b-mlx` and `27b-q8_0`
  refuse correctly in all three of theirs each: the fabrication finding
  was hidden, not overturned. Two of the four replacements are themselves
  saturated — §8.3.
- `vm_trace` and `ledger_replay` measure whether an answer fits in 6,144 tokens.
  The incumbent fits and is wrong; no Qwen build fits at all. Real difference,
  confounded with capability. The budget goes up or the tasks get shorter.
  → **The budget went up, per task rather than per phase, to 12,288**, and
  eighteen truncations became two. But "the incumbent fits" was too generous: at
  the raised budget it produced a 7,491-token `vm_trace` sample, above the old
  ceiling. The confound was on both sides of the comparison.
- `precedence_chain` is hard for the right reason: 0.00 for all four with no
  budget involved. A three-link variant would land in the band.
  *(Corrected 2026-09-04: this sentence read "with every answer completed",
  copied from the half of a PROGRESS entry that contradicted its own truncation
  tally. One `27b-mlx` sample truncated; eleven of twelve completed.)*
  → **Direction right, number wrong.** `precedence_relief` sits at 75% across
  candidates rather than inside 40–70%, and separates the incumbent from all
  three challengers, 0% against 100%.
- The set still fails §4.3 at 76–85% for every candidate.
  → Still fails, less badly. The incumbent is now inside the band at 67.7% and
  the three Qwen builds are at 73.8–78.1%.
- Group T needs the property that made the single-turn set work: correctness at
  turn fifteen depending on something established at turn three.
  → **Not done, and now wanted for a second reason**: it is the acceptance test
  for the compaction planned in
  [plans/automatic-context-compaction.md](./plans/automatic-context-compaction.md),
  where the question is whether a fact established before a compaction survives
  it.

## 8. The 2026-09-04 revision, and the conclusion §7 could not have reached

**Designed and run 2026-09-04.** Five of §7's fifteen tasks replaced, a per-task
output budget added, `hard-full-2`: 180 samples, four candidates, three
interleaved rounds, 18,332 seconds, `EVAL_NUM_PREDICT=6144` so the nine
unchanged tasks stay comparable with `hard-full`. Evidence in
[PROGRESS.md](./PROGRESS.md) 2026-09-04.

### 8.1 What it measures, by §4.4 verdict

| | tasks |
|---|---|
| **carries signal** | `config_merge`, `duration_grammar`, `visible_suffix`, `text_wrap_exact`, `determined_seats`, `undetermined_seats`, `precedence_relief`, `ini_parse` |
| **saturated high** | `undetermined_key`, `determined_key` |
| **saturated low** | `vm_trace`, `ledger_replay` |
| **neither** | `search_last_rotated`, `count_inversions`, `vm_implement` — 86–100%, too near the ceiling to separate and no longer flat enough to call saturated |

Eight of fifteen against §7's seven, and four carrying nothing against §7's
eight.

### 8.2 The incumbent is last, and both readings agree

| | whole set | truncated scored 0 | the eight signal tasks |
|---|---:|---:|---:|
| `qwen3.8:27b-mlx` | **78.1%** | 74.6% | **80.2%** |
| `qwen3.8:27b-q8_0` | 76.1% | 76.1% | **80.2%** |
| `qwen3.8:27b-q4_K_M` | 73.8% | 73.8% | 75.8% |
| `gemma4:31b-it-q8_0` *(serving)* | 67.7% | 67.7% | 66.4% |

§7.3 reported the incumbent **ahead by ten points** on the tasks that then
carried signal. Same candidates, same machine, same harness, and the order
inverted when the tasks that separated nobody were replaced.

**§5's contested exclusion rule is, for the first time, not load-bearing.**
Nineteen samples returned nothing in `hard-full` and the choice of rule was
worth 13.2 points and inverted the whole-set winner. Here it is two samples and
3.5 points, both `mlx`, both `vm_trace`, and `mlx` leads the incumbent under
either rule.

**Two tasks account for the reversal**, and the incumbent scored 0.00 on all six
of their samples:

| | 31b-it-q8_0 | 27b-mlx | 27b-q8_0 | 27b-q4_K_M |
|---|---:|---:|---:|---:|
| `undetermined_seats` | **0%** | 100% | 100% | 67% |
| `precedence_relief` | **0%** | 100% | 100% | 100% |

It is not broadly weak. It holds `config_merge`, `visible_suffix` and
`determined_seats` at 100% and takes `ini_parse` at 79.2%, the best figure any
candidate posts there. It is specifically weak at two things, and §7's set could
not see either: the four tasks that would have asked the first were saturated at
1.00 for every candidate, and the one that would have asked the second at 0.00
for every candidate.

**The pair reading `hard_refusal.py` requires.** A pair mean of 0.5 must say
which half was answered, because always-refusing and never-refusing score
identically:

| | determined | undetermined | pair | which failure |
|---|---:|---:|---:|---|
| `gemma4:31b-it-q8_0` | 100.0% | **0.0%** | 50.0% | **fabricates** |
| `qwen3.8:27b-mlx` | 100.0% | 100.0% | 100.0% | — |
| `qwen3.8:27b-q8_0` | 66.7% | 100.0% | 83.3% | over-refuses |
| `qwen3.8:27b-q4_K_M` | 100.0% | 66.7% | 83.3% | fabricates, sometimes |

In all three samples the incumbent returned a number where the data determines
none, usually 15.28 — net seats over net tenants, which is the answer only if no
tenant left, and nothing in the table says none did.

### 8.3 Two of the four replacements are saturated, and the difference is the lesson

`undetermined_key` and `determined_key` are 1.00 for every candidate in every
round. They rest on a distinctness guarantee that covers the wrong key — "no two
pairs carry the same `offset`" settles nothing when the ordering is on distance
from zero, since `[(-4, …), (4, …)]` is valid under every word and both labels
satisfy it. Twelve samples, twelve models seeing it.

Set against pair 1, which works, the difference is what a replacement has to
have. Both were written the same morning against the same diagnosis. Pair 1
offers a **division whose two operands are both in the table and whose result is
clean**, so a model has to notice what taking it assumed. Pair 2 offers a
logical observation, and a logical observation is either made or not. **The
inviting wrong arithmetic is the mechanism, not the depth of the inference.**

### 8.4 The budget, and what it revealed on the side it was not aimed at

`num_predict=12288` on `vm_trace` and `ledger_replay` alone, so the thirteen
tasks that were never budget-bound keep their basis.

| | `hard-full` | `hard-full-2` |
|---|---|---|
| `vm_trace` | 9 truncated / 3 scored | 2 truncated / 10 scored |
| `ledger_replay` | 9 truncated / 3 scored | 0 truncated / 12 scored |

`27b-q8_0` used 11,507 tokens on `ledger_replay`: 8,192 would not have been
enough. Both tasks are still 0.00 for all four candidates and still §4.4
replacements — the difference is that they are now honestly saturated rather
than measuring the ceiling.

**The remaining two truncations are a property of a build.** `27b-mlx` hit
12,288 on `vm_trace` in two of three rounds with `thinking_chars` zero. It
writes more per answer than either GGUF build and is over four times faster —
61.3 tok/s against 15.6 — and on a task needing sustained mechanical working
that trade costs it the answer.

### 8.5 Three samples are not a measurement, and this run is the proof

§7.4's two anchors both failed to reproduce (see the note there), and
`ledger_replay` scored 1.00 in one calibration sample and 0.00 in the next two.
All three are one draw differing from another: **the harness has never pinned a
sampling temperature**, so every figure it has ever reported is a three-sample
mean over draws at `temperature 1`.

Not changed in this phase, deliberately: pinning it would make every figure in
`full`, `qwen38`, `hard-full` and `hard-pilot-2` incomparable with everything
after, and doing that alongside five task replacements and a budget change would
confound two experiments. It needs its own phase against an unchanged set.

The reading rule that follows applies to this section too. **A §4.4 verdict from
three samples is provisional**, and §8.2's ranking — the best measurement this
repository has produced — is still three rolls per cell.

### 8.6 What is open

- `undetermined_key` and `determined_key` are replaceable under §4.4, on the
  evidence of §8.3 about what a replacement needs.
- `vm_trace` and `ledger_replay` are replaceable, now on honest grounds.
- **Pin the temperature, in a phase of its own** (§8.5). Until then no figure
  here supports a claim about reproducing.
- **The incumbent losing is not yet a recommendation to change what serves.**
  Three of four candidates sit above §4.3's band at 73.8–78.1%, so the set is
  still too easy for the challengers; `text_wrap_exact` and `duration_grammar`
  swing across 23–94% and 47–96%; and `27b-mlx`, the leader, is the build that
  cannot finish `vm_trace` at twice the budget. What the run establishes is that
  §7's conclusion rested on tasks that measured nothing, not that the ranking is
  settled.
- Group T's cross-turn dependency, unchanged from §7.6 and now wanted twice over.
