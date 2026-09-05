# Plan: Automatic Context Compaction, and Two Heavy Users on One Machine

**Status: planned, not implemented.** Written 2026-09-03 against `main` at
`cb43eb4`. Every figure below was measured on this deployment on that date and
the measurement is named beside it; where something is a hypothesis rather than
a measurement it says so in terms. One hypothesis in the first draft was tested
the same day and refuted; §2.5 keeps it, and the probe that killed it, because
the probe is the most useful thing in this document.

This is a design record rather than a task list. It exists because the request
that produced it — "make compaction automatic, put the switch on the API key,
default it on" — is cheap to ask for and expensive to get wrong on a platform
whose entire context-handling design was built to make truncation *visible*.

## 1. What was asked for

1. **Automatic context compaction**, so a conversation that outgrows the ceiling
   is compacted rather than refused.
2. **The switch lives on the API key**, and **defaults to on**.
3. **How much to cut is deferred.** Not part of this plan beyond §6, which
   records why the answer is currently unavailable rather than merely unchosen.
4. The real objective behind all three: **two people using this machine hard, at
   the same time, continuously**, with compaction firing without stalling them.
   Throughput is explicitly not the priority, and **compaction may be
   serialised** — if two fire at once, one may wait for the other.

### Decisions taken

| Question | Decision |
|---|---|
| Where the switch lives | `api_keys`, one column, **default on** |
| Is compaction allowed to be silent | **No.** Never. See §3 — this is the one place the request is amended rather than implemented |
| What compacts first | **Tool definitions and tool results**, mechanically, at zero inference cost (§5.1, §5.2) |
| When a model summarises | Only after the free tiers, and only against `assist`/`qwen7b`, never the serving model (§5.3) |
| Where a summary is stored | **Redis, keyed by a hash of the exact message prefix it replaces** (§5.4) — without this the stateless gateway recompacts every turn |
| `--context-shift` at the runtime | **Cannot be turned off from configuration** in Ollama 0.33.2 (§4.1). It is already performing the crudest possible compaction, silently, and may be the same mechanism as the `num_ctx / 2` halving — which makes testing that the largest lead here |
| How compaction quality is judged | The multi-turn harness, with the property §7.6 of `model-evaluation.md` already asks for (§7) |
| What blocks two heavy users | **`-np 1`, not memory** (§2). Memory has roughly 22 GiB of headroom |

## 2. The capacity question, measured

The assumption worth killing first is that 64 GiB is the binding constraint on
how much context this deployment can carry. It is not, and the measurement is
not close.

### 2.1 Context is nearly free; weights are not

`gemma4:31b-it-q8_0` was observed resident at two different context lengths in
the same session on 2026-09-03, both read from `/api/ps`:

| `num_ctx` | `size_vram` | |
|---:|---:|---|
| 262144 | 36,023,377,591 B | 33.55 GiB |
| 16384 | 34,099,523,747 B | 31.76 GiB |
| | **1,923,853,844 B** | **1.79 GiB for 245,760 tokens** |

**About 7.8 KB per token of context.** Opening this model from 16K to its full
256K costs under 2 GiB. Two causes, both visible on the runtime's own command
line (§4.1): `OLLAMA_KV_CACHE_TYPE=q8_0` quantises the KV cache, and the model's
`gemma4.attention.sliding_window = 1024` means most of its 60 blocks hold a
window-bounded KV rather than one that grows with the conversation. A model with
ordinary full attention at these dimensions would cost 60 × (512 + 512) = 61 KB
per token, eight times what was measured.

All three deployed models resident at their registered contexts came to
36.02 + 5.71 + 0.37 = **42.1 GiB of 64**. There is roughly 22 GiB unused.

### 2.2 So what did evict everything on 2026-08-07?

`ollama_adapter/encoding.py::_set_num_ctx` records loading `gemma4:31b-it-qat`
at 262144 as **predicted 55.8 GiB**, enough to evict every other resident model
and take `assist` and `embedding` down with it. Against the 1.79 GiB just
measured for a quarter-million tokens, that prediction cannot have been describing
the KV cache.

**The eviction was driven by a prediction, not by consumption**, and the
prediction is the thing that was wrong. That does not make the fix wrong —
sending `num_ctx` explicitly is correct regardless — but it does change what the
incident teaches. It is not evidence that context is expensive here. Three
figures for the same class of model still disagree and none of them has been
reconciled: the `models` row registers `memory_gb = 41`, the runtime predicted
55.8, and `/api/ps` reports 33.55. **Reconciling those three is a prerequisite
for any capacity planning done from the `models` table**, which is where an
operator would naturally look.

### 2.3 The actual constraint is one runtime slot

The `llama-server` process serving `gemma4` on 2026-09-03 was invoked with:

```
-c 16384  -np 1  --context-shift  --keep 4
--cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on  -b 1024 -ub 1024
```

**`-np 1` is one slot.** The gateway's `max_concurrent_inference = 4` is, in its
own docstring's words, "queueing depth, not throughput — it decides whether a
fourth caller waits or is refused". Four gateway slots feed a runtime that
generates for one caller at a time.

For two people working hard at once, that is the whole problem, and the numbers
around it are unforgiving. Measured from `usage_records`:

| | |
|---|---:|
| Deepest prompt ever served (`qwen36-35b-a3b-q8`, `chat`) | 94,901 tokens |
| Deepest on the incumbent (`gemma4-31b-q8`, `code`) | 75,245 tokens |
| Longest single request | 1,311,827 ms (21.9 min) |
| `queue_wait_seconds` before `503 overloaded` | **120** |
| A slot may be held for | `request_timeout_seconds` 1200 + `generation_deadline_seconds` 900 |

So today: user A starts a long `code` turn, user B arrives, waits two minutes,
and is refused with `503 overloaded` while A still has fifteen minutes to run.
**Serialisation is acceptable to the requester; being refused after two minutes
of it is not the same thing.** That gap is the first thing to fix, and it is one
configuration value.

### 2.4 Two routes to two users, and what each costs

**(a) Keep `-np 1`, raise `queue_wait_seconds`.** B genuinely waits for A. Costs
nothing in memory, nothing in context, and no code. The cost is that B produces
zero bytes for up to twenty minutes, which §"queue_wait_seconds" already names
as the failure it was shaped to avoid — a caller waiting in silence is
indistinguishable from a hung deployment. Mitigation is a `Retry-After` that
tells the truth about the queue rather than a longer silence.

**(b) `-np 2`.** Two real slots. Both users generate at once, each at roughly
half the token rate, and **`-c` is divided between the slots** — this is where
`num_ctx / 2` becomes literally and unavoidably true. Memory permits it easily:
`-c 245760` to give each slot the platform's full 122,880-token ceiling costs
about 1.92 GiB of KV on the figures in §2.1, for a total near 36 GiB against 64.

**(a) is the recommendation**, because it matches what was actually asked for
("不用同時做") and because (b) interacts with §2.5 in a way nobody has measured.

### 2.5 The halving is real at `-np 1`, and it was measured

`route_chat_request/diagnostics.py` states the rule this platform's whole input
ceiling is built around:

> Ollama evaluates at most `num_ctx / 2` prompt tokens and drops the rest
> without saying so.

This plan first recorded a hypothesis that the halving was an artefact of
parallelism — `n_ctx / n_parallel` in llama.cpp — and therefore absent at
`-np 1`, which would have meant `max_context_length` was refusing callers at
half of what the runtime could read. **The hypothesis was tested on 2026-09-03
and is wrong.** It is kept here rather than deleted because the measurement that
killed it is the most useful thing in this section.

A prompt of 99,271 characters was sent to `qwen2.5:7b`, resident at
`num_ctx = 32768`, through `/api/generate`:

```
prompt_eval_count = 16386          ← 32768 / 2, plus two
done_reason       = "stop"
```

**The rule holds at `-np 1`.** `max_context_length = 122880` sits correctly
below the 131072 that a 262144-token registration implies, and nothing in this
plan may assume otherwise.

The second probe is the one worth keeping. The same filler was sent again with
`SECRET-WORD: pomegranate-47` as its **first line**, and a closing question
asking what that word was:

```
prompt_eval_count = 16386
done_reason       = "stop"
answer            = "the"
```

The model never saw the first line, answered anyway, and answered wrongly with
no indication that anything had gone missing. **This is `diagnostics.py`'s
"fluent, and only wrong" reproduced on demand, in one request, on this
deployment.**

It also corrects that docstring in the direction of alarm. The docstring says
`done_reason` comes back `length`, "which is also what a generation that filled
its budget reports, so nothing downstream can tell the two apart". The measured
value is **`stop`** — an ordinary, successful completion. There is nothing to
tell apart: a silently truncated request is indistinguishable from a healthy
one, not merely confusable with a different failure.

Two consequences for this plan. The tiers in §5 are the only thing standing
between a long conversation and this behaviour, which raises their priority. And
§2.4's option (b), `-np 2`, becomes more expensive than it looked: whether the
halving composes with the per-slot division — giving `num_ctx / 4` — is
**unmeasured**, and must be probed the same way before any parallelism change.

## 3. The one place this plan amends the request

The request is for compaction on by default. This plan implements that. What it
does not implement is compaction that is *quiet*, and the reason is that the
rest of this codebase would have to be argued with:

- `_refuse_what_this_target_would_truncate` exists so that a fallback to a
  smaller model refuses rather than answering from a prompt whose beginning it
  never read.
- `ContextTooLongError` carries `estimated`, `limit` and `composition` —
  deliberately breaking the "no internal detail in responses" rule — so a caller
  refused at a ceiling has something to act on.
- `diagnostics.py` describes the failure it is guarding against as: *"The caller
  gets a fluent answer to a conversation whose beginning the model never saw, and
  the only thing wrong with the response is that it is wrong."*

Automatic compaction is deliberate lossy truncation. Default-on compaction that
did not announce itself would reintroduce, as a feature, precisely the failure
those three were built to remove — and would do it to every existing API key at
once, without any of their holders asking.

So: **on by default, and never silent.** Every compacted request must carry, in
the response, what was dropped and by which tier; must record it on the
`usage_records` row; and must be visible in the admin UI beside the request. The
switch turns compaction on and off. It does not turn the disclosure off.

## 4. What is already compacting, and must stop

### 4.1 `--context-shift --keep 4`, which cannot be turned off from configuration

The runtime is invoked with context shifting enabled. When the KV cache fills,
llama.cpp discards the oldest tokens and continues, keeping only the first
`--keep 4`. That is automatic compaction already in production, of the crudest
kind available — it drops by position, it has no idea what a message boundary
is, and **four tokens is not a system prompt**, so the instructions and the
nonce-delimited data boundary are exactly what it throws away first.

**An earlier draft of this plan said to turn it off. It cannot be turned off.**
Checked on 2026-09-03 against Ollama 0.33.2:

- `llama-server` supports `--no-context-shift` and reads `LLAMA_ARG_CONTEXT_SHIFT`.
- The `ollama` binary contains only the string `--context-shift`, which it passes
  unconditionally; `--no-context-shift` does not appear in it at all.
- `ollama serve --help` lists no environment variable for it.
- A command-line argument overrides the environment variable llama.cpp would
  otherwise read, so setting `LLAMA_ARG_CONTEXT_SHIFT` in the LaunchDaemon does
  not reach it either.

Disabling it therefore means patching Ollama or changing runtime, and neither is
in scope here. What is in scope is not pretending it is absent.

**And it is probably the same mechanism as §2.5's halving.** llama.cpp's shift
keeps `n_keep` tokens and discards half of what remains — `n_left / 2` — which
is exactly the ratio measured, to within the two tokens of `--keep 4`. That
would make the platform's central context rule and this flag one phenomenon
rather than two. **Unverified**, and worth verifying, because if it is true then
disabling context shift would both remove the silent truncation *and* return the
other half of the context — which is the single largest capacity item available
to this deployment, larger than anything else in §8.

### 4.2 The runtime already has no conversation to compact

Worth stating because it constrains everything in §5: **the gateway is
stateless, and the client replays the entire conversation on every turn.** That
is why agent clients drove `max_context_length` from 32768 to 122880 across
three raises. There is no server-side conversation object to compact — there is
a `messages` array, arriving whole, every turn.

Every consequence in §5.4 follows from this one fact.

### 4.3 The token counter cannot currently measure the incumbent

`gemma4:31b-it-q8_0` declares `tokenizer.ggml.pre = gemma4`, which is not in
`KNOWN_PRE_TOKENIZERS`, so `chat` and `code` are **estimated rather than
counted**. The measured drift band is `(0.9, 1.65)`, and dense ASCII has been
measured at **0.34x** — under-counting by a factor of three.

This is why §6 defers "how much to cut" rather than merely postponing it.

## 5. The design

Four tiers, cheapest first. A request enters compaction only when the counted or
estimated input exceeds the target, and stops at the first tier that brings it
under.

### 5.1 Tier 0 — tool definitions

Tool definitions are resent verbatim on every turn and are frequently the
largest single block in agent traffic; `_warn_if_tools_dominate` already exists
with `TOOL_SHARE_WARNING = 0.5` because of it. They are also the one part of a
payload that is mechanically reducible without judgement: descriptions can be
trimmed to a bound, and identical definitions repeated across turns collapse to
one.

Zero inference cost. Lossless with respect to the conversation.

### 5.2 Tier 1 — tool results, oldest first

In agent traffic the bulk is tool *output*: file contents, command output,
search results. These are the natural first thing to drop, because a result from
twenty turns ago has usually already been acted on, and because a truncated tool
result can be replaced by a marker that says what it was and how long it was —
which is information the model can act on, unlike an absence.

Zero inference cost. Lossy, and announced.

### 5.3 Tier 2 — summarise the oldest turns

Only if tiers 0 and 1 are not enough.

**On `assist`/`qwen7b`, not on the serving model.** Summarising on the model
that is serving means a second prefill on a runtime with one slot, behind or in
front of the user's own request. `qwen7b` is 5.71 GiB, is already resident, has
a native 32768 context, and its `assist` traffic peaks at 3,997 tokens — it has
room and it is not on the critical path.

**Serialised.** The requester explicitly allowed this: if two compactions fire
at once, one waits. One lock, held for the duration, so compaction can never
consume more than one of the four gateway slots.

### 5.4 The cache, without which none of this works

Because the gateway is stateless (§4.2), a naive implementation would summarise
the same history **on every turn** — the client resends it, so the gateway sees
an over-long conversation again and compacts again. On a one-slot runtime that
is not a slow feature, it is an outage.

So compaction must be **content-addressed and cached**:

- The key is a hash of the exact message prefix being replaced, plus the tier
  and the parameters used.
- The value is the compacted replacement.
- Redis is already in the deployment and is the right home; the entry is a
  cache, so losing it costs a recomputation and never a wrong answer.

The property that makes this work is that an agent's replayed history is
**stable in its prefix** — turn 15 carries turns 1–14 unchanged. The same prefix
hashes the same on every subsequent turn, so a conversation is summarised once
and reused until it grows past the next threshold.

**This is the single most important implementation detail in the plan.** A
correct tiering with no cache is worse than no compaction at all.

### 5.5 The switch

One column on `api_keys`, defaulting to on. Because it defaults on, the
migration turns it on for every key that already exists, which is a behaviour
change to live integrations — so it ships together with the disclosure in §3,
never before it, and the rollout note belongs in PROGRESS on the day it lands.

## 6. Why "how much to cut" is deferred, and what unblocks it

Deferred by request, and there is a technical reason to be glad of it.

Compaction needs a target: cut until the input is under *N* tokens. On `chat`
and `code` the only available measurement of the input is an **estimate** whose
measured error reaches 0.34x on dense ASCII (§4.3). Dense ASCII is exactly what
agent traffic is made of — source code, diffs, command output.

Cutting to a target computed from a ruler that can under-count by three times
means either cutting too little, in which case the prompt is still over the
ceiling and something downstream truncates it silently, or cutting far too much,
which burns context the caller is paying for. **Any automatic compaction built
before the incumbent can be counted exactly is a ruler that is known to be
crooked being used to decide what to throw away.**

So the ordering is:

1. Settle §2.5's `-np 1` hypothesis. One probe. It may double the usable ceiling
   and it changes every threshold below it.
2. Make `gemma4:31b-it-q8_0` countable — add its pre-tokenizer to
   `KNOWN_PRE_TOKENIZERS` if its vocabulary permits, or register a countable
   model for `chat` and `code`.
3. Then choose the target, with a measurement rather than a guess.

Tiers 0 and 1 are safe to build before any of this, because they reduce input
without needing to know precisely how much they reduced it by.

## 7. How this gets judged

The rule this repository runs on is that **nothing is judged by reading it**,
and compaction is exactly the material where that rule is tempting to break —
"is this summary good?" invites an opinion.

It does not have to. §7.6 of `model-evaluation.md` already records the property
the multi-turn set is missing:

> Group T needs the property that made the single-turn set work: correctness at
> turn fifteen depending on something established at turn three.

**That property is the acceptance test for compaction.** Establish a fact at
turn three, compact past it, ask a question at turn fifteen whose answer depends
on it, and score the answer programmatically. A compaction that drops the fact
fails a string comparison; no judgement is involved.

This is worth building for its own sake — it is already on the record as
something group T lacks — and it means the instrument for measuring compaction
exists before the feature does, which is the order this repository has twice
recorded regretting getting backwards.

## 8. Ordered work

| # | Item | Cost | Blocks |
|---|---|---|---|
| 1 | ~~Probe the `num_ctx / 2` rule at `-np 1`~~ **done 2026-09-03: the rule holds** (§2.5) | — | — |
| 2 | Raise `queue_wait_seconds` so a second heavy user waits rather than being refused (§2.3) | one value | two-user working |
| 3 | Test whether `--context-shift` *is* the halving (§4.1) | one probe | possibly 2x context |
| 3b | If it is: patch or replace the runtime to disable it | large | honest overflow, 2x context |
| 4 | Reconcile the three memory figures for the incumbent (§2.2) | measurement | capacity planning |
| 5 | Group T's cross-turn dependency property (§7) | harness work | judging compaction |
| 6 | Tier 0 and Tier 1 compaction, with disclosure (§5.1, §5.2, §3) | code | — |
| 7 | The prefix-hash cache (§5.4) | code + Redis | Tier 2 |
| 8 | Make the incumbent countable (§4.3) | investigation | choosing the target |
| 9 | Tier 2 summarisation on `qwen7b`, serialised (§5.3) | code | — |
| 10 | The `api_keys` column, defaulting on (§5.5) | migration | ships last |

Item 2 is one configuration value and is most of what "two people using this
hard at once" actually needs; it is not compaction. Item 1 is done. Item 3 is now
the largest single lead in this document rather than a tidy-up, because §2.5 and
§4.1 together suggest the deployment may be running at half the context it has
paid for, for a reason that is one flag wide.
