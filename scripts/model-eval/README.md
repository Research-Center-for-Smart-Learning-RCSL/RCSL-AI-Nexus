# Model evaluation harness

The instrument for [docs/model-evaluation.md](../../docs/model-evaluation.md). The original
eighteen-task set was designed 2026-08-14 and is still in the harness; the **hard set** — fifteen
tasks across groups J–Q plus two anchors — is the current measurement set, and `hard-full-3` is
the phase that runs it with pinned sampling parameters.

## Layout

| file | what it holds |
|---|---|
| `tasks.py` | all registered tasks (34 as of the hard set revision): prompt, checks, reference, wrong answer |
| `task_families/` | task source by group: `family_a.py`–`family_h.py` (18-task set), `hard_*.py` + `anchors.py` (hard set) |
| `specdoc.py` | the ~4,500-token policy document group E reads, generated deterministically |
| `harness.py` | the Ollama call, answer extraction, and the subprocess scorer — not a sandbox, see below |
| `harness_parts/` | `client.py` (generation with pinned temperature/top_k/top_p/seed), `sample.py`, `scoring.py`, etc. |
| `validate.py` | section 4.1: the scorer is checked in both directions before any model runs |
| `run.py` | drives a phase; appends every sample to `results.jsonl` as it completes |
| `analyse.py` | tables with bootstrap 95% CI, saturation verdicts, cross-phase comparison, JSON export |
| `bench_throughput.py` | generation and prompt-evaluation rate for one model at a stated depth |

## Running it

**`restore` puts back what was resident when the phase started, not what a literal says.**
`run()` snapshots `/api/ps` before the first eviction and `restore()` prefers that file; the
`DEPLOYED` literal is the fallback and has gone stale once already, naming a model the deployment
had stopped serving five days earlier. See PROGRESS.md 2026-09-02.

```sh
cd scripts/model-eval
python3 validate.py            # must print 34/34 before anything else is worth doing
python3 run.py hard-pilot-3    # calibration against the incumbent only (section 4.2)
python3 analyse.py hard-pilot-3
python3 run.py hard-full-3     # four candidates, five interleaved rounds
python3 analyse.py hard-full-3
python3 run.py tutor-full      # the four education-agent tasks, all candidates
python3 analyse.py tutor-full
python3 run.py restore         # put the deployment's model back, pinned
```

### Environment variables

| variable | default | what it controls |
|---|---|---|
| `EVAL_TEMPERATURE` | `0.3` | Sampling temperature — pinned for reproducibility |
| `EVAL_TOP_K` | `40` | Top-k sampling |
| `EVAL_TOP_P` | `0.9` | Nucleus sampling |
| `EVAL_SEED` | `42` | Random seed for deterministic sampling |
| `EVAL_NUM_CTX` | `16384` | Context window sent to Ollama |
| `EVAL_NUM_PREDICT` | `4096` | Default output budget (tasks may override) |
| `EVAL_ROUNDS` | `5` | Number of interleaved rounds per phase |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama runtime address |

**A `repair` phase supersedes `full` task by task, and nothing here merges them for you.**
`analyse.py` reads one phase, so its `full` tables still carry the figures the re-run replaced;
the published numbers are `full` with `repair` overriding the tasks it covers, which is the rule
`backend/app/infrastructure/import_evaluation.py` implements and the importer takes as
`--phase full --phase repair`. Getting it wrong in either direction restores the defect the
re-run removed: `full` alone puts `qwen3.6:27b-q8_0` at 81.9% against its real 87.5%, and
concatenating both phases without letting the later one win puts it at 83.5%.

**`qwen38` needs no `repair`, and that is what makes it comparable.** The three prompts that
carried a `def f(...): ...` stub were fixed in `tasks.py` on 2026-08-15, so a phase run after that
date gets the repaired wording from its first sample. Its figures line up with `full` overridden by
`repair` — the published reading — and not with `full` alone. It also re-runs the incumbent rather
than citing its recorded 94.4%, because that figure was measured on Ollama 0.32.4 and this runs on
0.33.2. And it carries `qwen3.8:27b-q8_0` alongside the two builds a deployment would actually
pick, because section 5 requires quantisation to be matched and the q4-against-q8 comparison is the
one this repository has already been wrong from once.

No dependencies beyond the standard library. `OLLAMA_HOST` overrides the runtime address.

## Throughput on its own

`analyse.py` reports throughput as a by-product of scoring eighteen tasks, which costs ten to
twenty minutes per model and cannot be pointed at a model the set has never been run against.
`bench_throughput.py` asks only how fast a model is:

```sh
python3 bench_throughput.py gemma4:31b-it-q8_0 --keep-alive -1     # a model the deployment serves
python3 bench_throughput.py qwen3.8:27b-mlx    --keep-alive 0      # a candidate
```

**`--keep-alive` is not optional and the two values are not interchangeable.** Ollama applies its
own five-minute default to any request that omits the field, so benchmarking a resident model
without it replaces the `-1` the platform's load asked for. Pass `-1` for anything the deployment
is serving and `0` for a candidate, which unloads it as the last generation ends rather than
leaving 17 GiB resident. It must reach Ollama as a JSON number: `"-1"` as a string is parsed as a
Go duration and fails with `time: missing unit in duration "-1"`.

**It has to recover a known figure before it is worth anything.** `results.jsonl` puts
`gemma4:31b-it-q8_0` between 13.57 and 13.83 gen tok/s on every task under depth 400; the bench
measures 13.65 at depth 500 on the same runtime. Two things it does are what make that possible: a
distinct leading nonce per repetition, because Ollama caches the evaluated prefix and three
repetitions of one prompt otherwise report four-digit prompt throughput; and one discarded call per
depth, because Ollama keys a loaded instance by its options and the first call at a new `num_ctx`
pays a reload. `--skip-depth-warm` turns the second off when a call costs ten minutes and the model
is already resident at that `num_ctx`.

`--tokens-per-word` sizes the filler. The default is measured against this filler on a `qwen35`
vocabulary; the achieved depth is always reported, because the ratio is a property of the
vocabulary and a wrong one silently measures a different question.

`run.py` appends to `results.jsonl` and skips `(phase, model, task, round)` combinations already
there, so an interrupted run resumes rather than starting over. Delete the file to start clean;
rename the phase to keep an old read on the record beside a new one.

## Three things to know before running it

**It takes the deployment down.** Loading a candidate evicts what is serving, and on 64 GiB only
one 30 GB-class model is resident at a time. `chat` and `code` return 503 for the duration —
roughly 30 minutes for a pilot, two hours for a full run. `run.py restore` puts back the three
models `snapshot()` recorded before the phase evicted anything, largest first and each at the
`num_ctx` Ollama had clamped it to.

**This paragraph told you to check a constant, and said so until 2026-09-02.** It described a
one-model restore pinned to `qwen3.6:35b-a3b-q8_0` and warned against setting it back to
`INCUMBENT` — advice that inverted on 2026-08-21, when the deployment went back to
`gemma4:31b-it-q8_0`, which is what `INCUMBENT` names. So the warning was pointing at the model
that serves and away from one that has not served since. That is the failure the snapshot was
built to remove: `DEPLOYED` is now the fallback rather than the source, it carries all three
models rather than one, and the sentence *"nothing here can detect that it has gone stale"* is no
longer true of the mechanism, only of the fallback. The same 2026-09-02 fix that corrected the
code did not reach this file. `curl -s 127.0.0.1:11434/api/ps` is still worth running first,
because a snapshot taken while the deployment is already down records the wrong thing.

**It executes model-generated Python.** Code tasks are scored by running what the model wrote, in
a subprocess with a per-check alarm and a temporary working directory — but not in a sandbox. It
has the privileges of whoever runs it. This is the usual bargain for a self-scoring code
evaluation; it is written down here rather than discovered later.

**The calibration gate is not decoration.** Section 4.3 wants the incumbent between 40% and 70%.
The first version of this task set scored **100%, thirty-seven samples, every one of them 1.00**,
and the cause was not the checks — the deliberately wrong answers scored 0.57 to 0.88 against
them. The cause was that the prompts announced their own traps: `merge_disjoint` supplied the
worked example of the deviation, the complexity tasks named the required asymptotics, and
`cache_decorator` listed the three properties to fix. A signposted trap is a reading
comprehension exercise, and these models read well. The rewrite states the same requirements
without flagging which one is load-bearing.

## What this still does not measure

**Group F can be passed by a model that always refuses.** `insufficient_data` and
`ambiguous_requirement` are the only two tasks whose right answer is a refusal marker, and
nothing here pairs them with a question that *is* answerable from the same data. **Group N
addresses this for the hard set** — its four tasks are two matched pairs, each pairing a
determined half with an undetermined half — but group F in the eighteen-task set remains open.

**A truncated answer is scored as nothing, and that is not neutral.** `sample.py` labels
truncated-without-answer samples as a third outcome (`truncated_no_answer`), and `analyse.py`
prints both readings — excluded and scored-0 — side by side. The third outcome was added
2026-09-03 and the reading rule applies: check the no-result list before reading any score.

**Whether the work is any good.** The boundary docs/model-evaluation.md section 6 already draws,
and the ten-rung agent harness before it. Checkable tasks measure whether a model can follow a
specification it has not memorised. Real work remains the only instrument for the rest.
