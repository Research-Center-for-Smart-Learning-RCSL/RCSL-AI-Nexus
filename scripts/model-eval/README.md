# Model evaluation harness

The instrument for [docs/model-evaluation.md](../../docs/model-evaluation.md), which designed
sixteen tasks plus two anchors and was never run until 2026-08-15.

**This exists because the previous one did not.** The twelve-task harness behind the
[PROGRESS.md](../../docs/PROGRESS.md) 2026-08-14 table was never committed, so its numbers cannot
be reproduced and its two anchor tasks cannot be carried forward — see *Anchors* below for what
that cost. Anything that produces a figure this repository will later reason from belongs here.

## Layout

| file | what it holds |
|---|---|
| `tasks.py` | the eighteen tasks: prompt, checks, a reference answer, a deliberately wrong answer |
| `specdoc.py` | the ~4,500-token policy document group E reads, generated deterministically |
| `harness.py` | the Ollama call, answer extraction, and the sandboxed scorer |
| `validate.py` | section 4.1: the scorer is checked in both directions before any model runs |
| `run.py` | drives a phase; appends every sample to `results.jsonl` as it completes |
| `analyse.py` | the tables, including the saturation verdict section 4.4 asks for |

## Running it

```sh
cd scripts/model-eval
python3 validate.py        # must print 18/18 before anything else is worth doing
python3 run.py pilot2      # calibration against the incumbent only (section 4.2)
python3 analyse.py pilot2  # reports whether the incumbent is inside the 40-70% band
python3 run.py full        # three candidates, three interleaved rounds
python3 analyse.py full
python3 run.py restore     # put the deployment's model back, pinned
```

No dependencies beyond the standard library. `OLLAMA_HOST` overrides the runtime address.

`run.py` appends to `results.jsonl` and skips `(phase, model, task, round)` combinations already
there, so an interrupted run resumes rather than starting over. Delete the file to start clean;
rename the phase to keep an old read on the record beside a new one.

## Three things to know before running it

**It takes the deployment down.** Loading a candidate evicts what is serving, and on 64 GiB only
one 30 GB-class model is resident at a time. `chat` and `code` return 503 for the duration —
roughly 30 minutes for a pilot, two hours for a full run. `run.py restore` puts
`gemma4:31b-it-q8_0` back with `keep_alive: -1`, which is how the deployment pins it. Check with
`curl -s 127.0.0.1:11434/api/ps`.

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

**The anchors are reconstructed, not carried over.** `ini_parse` and `logic_order` exist to make
this set comparable with the twelve-task set rather than merely sequential. That is not what they
do here: the original harness was never committed, so both were rebuilt from the prose
description in PROGRESS.md. They are two more tasks. The bridge between the two sets is gone and
this one cannot rebuild it.

**Group F can be passed by a model that always refuses.** `insufficient_data` and
`ambiguous_requirement` are the only two tasks whose right answer is a refusal marker, and
nothing here pairs them with a question that *is* answerable from the same data. A model that
emits the marker whenever it sees the instruction scores 2/2 without the property being measured.
Closing this needs a matched control task, which the design does not include.

**Whether the work is any good.** The boundary docs/model-evaluation.md section 6 already draws,
and the ten-rung agent harness before it. Eighteen checkable tasks measure whether a model can
follow a specification it has not memorised. Real work remains the only instrument for the rest.
