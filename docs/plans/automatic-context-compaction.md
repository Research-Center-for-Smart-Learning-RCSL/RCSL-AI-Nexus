# Plan: Automatic Context Compaction, and Two Heavy Users on One Machine

**Status: implemented.** Written 2026-09-03 against `main` at `cb43eb4`; §9 is
a verification written on 2026-09-07 against `bd185eb`, and the work it
describes was done the same day. All three tiers run, the cache is constructed
and can hit, the `api_keys` switch is live, the acceptance instrument exists,
and §3's disclosure now reaches all three surfaces it asked for.

Two items are open and neither is compaction: §8's item 3 — whether
`--context-shift` *is* the `num_ctx / 2` halving, still the largest lead in this
document — and item 4, reconciling the three memory figures.

Every figure below was measured on this deployment on 2026-09-03 and the
measurement is named beside it; where something is a hypothesis rather than
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

Three tiers, cheapest first. A request enters compaction only when the counted
or estimated input exceeds the target, and stops at the first tier that brings
it under. What follows a tier that was not enough is the next one; what follows
the last is the refusal, which is not a tier.

(This sentence read "Four tiers" from the first draft until 2026-09-07, and
§5.1 to §5.3 have only ever described three. The miscount was copied into
`compaction.py`'s own module docstring, where it named three and then said
four.)

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

| # | Item | Cost | State as of 2026-09-07 |
|---|---|---|---|
| 1 | Probe the `num_ctx / 2` rule at `-np 1` (§2.5) | — | **done 2026-09-03**: the rule holds |
| 2 | Raise `queue_wait_seconds` (§2.3) | one value | **done 2026-09-07.** The code default was raised to 1200 on 2026-09-05, but `.env`, `.env.example` and the deployment configuration table all still carried 120, so the raise reached nothing until all four were aligned. Takes effect on restart |
| 3 | Test whether `--context-shift` *is* the halving (§4.1) | one probe | **not done.** Still the largest lead here |
| 3b | If it is: patch or replace the runtime to disable it | large | not started |
| 4 | Reconcile the three memory figures for the incumbent (§2.2) | measurement | **not done** |
| 5 | Group T's cross-turn dependency property (§7) | harness work | **done 2026-09-07**: `recall_across_turns`, described in model-evaluation.md §7.6 |
| 6 | Tier 0 and Tier 1 compaction, with disclosure (§5.1, §5.2, §3) | code | **done**: tiers live, tested, and disclosed (§9.1) |
| 7 | The prefix-hash cache (§5.4) | code + Redis | **constructed 2026-09-07**, and it had never hit — see §9.4 |
| 8 | Make the incumbent countable (§4.3) | investigation | **done**: `gemma4` pre-tokenizer support, then a native Rust GGUF reader |
| 9 | Tier 2 summarisation on `qwen7b`, serialised (§5.3) | code | **wired 2026-09-07 (§9.2)** |
| 10 | The `api_keys` column, defaulting on (§5.5) | migration | **done**, and shipped ahead of the disclosure it was supposed to ship with |

Item 2 is one configuration value and is most of what "two people using this
hard at once" actually needs; it is not compaction. Item 3 is now the largest
single lead in this document rather than a tidy-up, because §2.5 and §4.1
together suggest the deployment may be running at half the context it has paid
for, for a reason that is one flag wide.

## 9. What shipped, verified 2026-09-07

Written after the fact, against `main` at `bd185eb`. Everything below was read
out of the tree; nothing here is a plan.

What is live and correct: `compaction.py` implements Tiers 0 and 1 exactly as
§5.1 and §5.2 describe, stopping at the first tier that brings the prompt under
the ceiling and re-counting on the same basis the guardrail used. The
`api_keys.compaction_enabled` column exists, defaults on, is set on every
existing key by `c1d5f8a3e497`, and is reachable from both API-key dialogs and
from the assistant's proposal path. `usage_records` carries `compaction_tier`,
`tokens_before_compaction` and `tokens_after_compaction`.

### 9.1 The disclosure is one third built, and the code claims otherwise

§3 requires three things of every compacted request: that the response carry
what was dropped and by which tier, that the `usage_records` row record it, and
that it be visible in the admin UI beside the request.

Only the second exists. `CompactionResult.disclosure` is composed by both tiers
and then goes to exactly one place — `logger.info` in `orchestrator.py`. It is
not in `CompletionChunk`, not in any chat or Responses schema, and not in the
admin usage schema, so `compaction_tier` is written to the database and read by
nothing. Neither the gateway's caller nor an administrator can see that
compaction happened.

Two comments in the tree state the opposite and should be read as intent rather
than as description until this is closed:

- `api_key.py`: "it does not control the disclosure, which is always present
  when compaction fires".
- `c1d5f8a3e497`: "it ships together with the disclosure, never before it."

The switch shipped first. That is the ordering §5.5 explicitly ruled out, and
it means a live integration is currently having its prompt silently reduced —
which is the failure §3 was written to prevent, reintroduced by the one part of
the plan that was supposed to prevent it.

**Closed 2026-09-07, and the channel was already decided.** §3 says "in the
response" without saying body or header, and this repository had answered that
question three times before compaction existed: `X-Capability-Defaulted`,
`X-Dropped-Tools` / `X-Dropped-Input-Items`, and `X-Knowledge-Sources`. The
first of those is the same problem exactly — an opt-in per-key setting that
removes a refusal — and the roadmap wrote down the reasoning when it shipped:
announced in a header, and recorded on the usage row *because* the evidence "has
to outlive both a header the client may not read and a log line that rotates".
So `X-Context-Compacted: tier=N`, on both the chat and the Responses paths, in
the same helper module as its three predecessors.

The two alternatives were rejected on the repository's own prior grounds. A body
field or an extra frame is what `routers/chat/route.py` already refuses — "the
envelope is OpenAI's, and an extra frame shape is a protocol error to a strict
client"; the SSE trailer mechanism exists but its only user is `/admin/assistant`,
which is not OpenAI-shaped. Putting the disclosure in a system message prefixed
to the model's output is worse than either: it enters content the caller stores,
replays and sends back, so it would become part of the prompt being compacted on
the next turn.

**What was genuinely uncertain was whether a header could carry it at all**, and
§9.5 is that answer.

The other two surfaces:

- **The admin UI**, which needed a screen that did not exist — §9.6.
- **The transcript**, which was not in §3's list and should have been. It is the
  only place a person reads the prompt itself, and after a compaction that is
  not the prompt the caller composed. `prompt_logs` gained a `compaction_tier`
  column (`a2f7c31b9e84`) and the transcript dialog states, above the
  conversation, that what follows is what the model read rather than what was
  submitted. The frontend's `api-contract.ts` found this omission: the
  transcript response was the one shape that disagreed with its zod schema after
  the summary was widened.

And one channel §3 did not ask for: `nexus_compactions_total`, labelled by
capability, model and tier, beside `nexus_compaction_tokens_removed_total`.
Compaction is invisible in the existing series — a compacted request looks like
an ordinary served one — and "is it firing" and "is it reaching the tier that
costs an inference call" are two questions an operator asks separately.

### 9.2 Tier 2 and the cache are written, tested by nothing, and constructed by nobody

`compaction_tier2.py` and `compaction_cache.py` implement §5.3 and §5.4
faithfully — the `assist` model, the `asyncio.Lock`, the SHA-256 prefix key,
the one-hour TTL. `orchestrator.py` calls `try_tier2` only when
`self._summarise_fn is not None`, and `build_route_chat_request` in
`di/inference_runtime.py` passes none of `summarise_fn`, `compaction_cache` or
`compaction_lock`. **So Tier 2 has never run outside a hand-built orchestrator,
and the cache has never been read.** A conversation that tiers 0 and 1 cannot
bring under the ceiling is refused today, exactly as before this work.

The three parameters are also typed `Callable[..., Any] | None` and
`Any | None`, which is the one place in this use case where a dependency
arrives untyped. The port discipline the rest of the file argues for
(`TokenCounterPort | None`, `PromptLogWriterPort | None`) says what these
should look like when they are wired.

There are **no tests** for any of the 591 lines across the three modules. The
sixteen references to "compaction" under `backend/tests` are all the API-key
switch. Tiers 0 and 1 are live in production with no test asserting what they
drop.

**Closed 2026-09-07.** `build_route_chat_request` now passes all three, and the
untyped parameters are `SummariseFn | None` and `CompactionCache | None`. The
lock is built once per process on `app.state` in both composition roots, since
that dependency is per-request and a lock built there would serialise nothing.
The summariser is a closure that resolves the `assist` capability through
`RoutingService` **per call**, not per request: resolving at build time would
put a routing read on the front of every chat request to prepare a collaborator
Tier 2 rarely reaches, and it would pin the policy until the next restart.

There is deliberately no fallback to the serving model when `assist` cannot be
routed. §5.3 chose `assist` precisely so a summary never competes for the slot
the caller is waiting on, and a fallback would undo that silently on the day the
policy is missing. A summariser that raises leaves `compaction_result` at None,
so the request meets the same `ContextTooLongError` it would have met with
compaction switched off — a refusal that names the ceiling, which is the
disclosure an oversized prompt is owed. `tests/unit/test_context_compaction.py`
holds twenty-two tests, and the last two are about this wiring rather than about
compaction: the modules were correct and unreachable, so a test of the modules
would have passed throughout.

### 9.3 The instrument still does not exist, and now the feature is ahead of it

§7 argued that Group T's cross-turn dependency property is the acceptance test
for compaction, and that building the instrument before the feature is the
order this repository has twice recorded regretting getting backwards. The
feature shipped first anyway. `model-evaluation.md` §7.6 still lists the
property as missing and `scripts/model-eval/task_families` has no set that
asks for it.

This is the cheapest thing on the list to be wrong about, because Tiers 0 and 1
are mechanical: what they drop is decidable by reading the code. It becomes
load-bearing the moment §9.2 is closed, since a summary's quality is exactly
what no amount of reading settles.

**Built 2026-09-07, and §9.2 was closed the same day, so the order this
repository twice regretted getting backwards was very nearly repeated.**
`recall_across_turns` is fifteen turns with two figures given once at turn
three, asked back separately at turns twelve and thirteen and as their product
at turn fifteen, with a control at turn fourteen on which inventing a figure is
the failure. Asking for the parts before the product is the part that earns its
keep against compaction: it separates a summary that kept one figure from one
that lost the turn. model-evaluation.md §7.6 has the detail. It is validated in
both directions and **not calibrated** — no model has answered it yet.

### 9.4 The cache could not have hit, and the first test written found it

The cache was not merely unconstructed. It was ineffective by construction, and
this is the one thing in §9 that no amount of reading the modules would have
turned up — it took the second test.

`try_tier2` chose the summarised prefix as `len(messages) - _KEEP_RECENT`. That
boundary is measured from the *end* of a conversation which, by §4.2, grows by
two messages every turn: the client replays everything and appends. So every
turn hashed a different prefix, every turn missed, and every turn summarised.
§5.4 says a naive implementation "would summarise the same history on every
turn" and that on a one-slot runtime this "is not a slow feature, it is an
outage" — the cache written to prevent exactly that would have delivered
exactly that.

The fix is the behaviour §5.4 already describes in words: "a conversation is
summarised once and reused **until it grows past the next threshold**". The
boundary is floored to a multiple of `_PREFIX_STEP` (ten messages), so it holds
still across the turns between two thresholds and the same prefix hashes the
same. Erring towards summarising *less* also keeps more of the conversation
verbatim, which is the safe direction for a boundary that has to be stable.

Worth keeping for its own sake: the plan asserted prefix stability as a property
of the client's behaviour, and it is one. It is not automatically a property of
a boundary computed from the length.

### 9.5 The header window, which is why this was a question at all

The doubt was never which header. It was whether a header could carry the fact
on the streaming path, since compaction happens inside the concurrency slot —
after routing, after counting — and headers are gone once the body starts.

They are not, and the reason is already written down for a different purpose.
Both routes call `sse.prime(generation)` before constructing the response, and
the Responses route says why: "Primed before the response object exists, so a
routing failure is a status code rather than a 200 carrying an error event."
Priming pulls the first chunk, and the first chunk is downstream of the slot, of
routing, of counting and of compaction. So there is a window in which the fact
is known and the headers are not yet written, and it exists because of a
decision taken about error handling.

`compaction_header()` is therefore read *after* priming while
`capability_defaulted_header()` beside it is read before, and the asymmetry is
commented at both call sites: one is derivable from the actor before anything
runs, the other is not knowable until the prompt has been counted. The
non-streaming path has no such constraint — FastAPI merges the `Response`
object's headers when the handler returns — but it uses the same helper, because
`route.py`'s existing rule is that both paths carry the same headers "so the two
cannot answer differently about the same request".

Getting the fact out of the use case is a callback, `report_compaction`, passed
in by the composition root exactly as `request_id` already was. The application
layer keeps not knowing it is behind HTTP. What crosses the boundary is
`CompactionDisclosure` — three integers — rather than `CompactionResult`, which
holds the compacted messages and tools: handing those to the HTTP layer so it
could render a header would put the whole prompt somewhere that needs a number.

The contextvar is reset at the start of every request rather than on the way
out, unlike the request id beside it. It is read to decide whether to *add*
something, so a leftover value announces a compaction that did not happen.

### 9.6 The admin UI needed a screen that did not exist

§3 asks for the disclosure to be "visible in the admin UI beside the request",
and that sentence assumed a surface the platform did not have. `/admin/usage`
is aggregate: counts per hour per capability. The only per-request view was
`prompt_logs`, which exists solely while a debug window is open. **So there was
nowhere to put it**, and `usage_records.compaction_tier` was written by the
gateway and read by nothing at all.

`usage_records` had in fact never had a reader that returned a row. Every
consumer since the first migration was an aggregate — dashboard totals, chart
buckets, a quota sum — so the platform recorded what each request did and could
show nobody a single one of them. "Which request was the 413 the integrator is
quoting?" was answerable only from a log line that rotates.

Three things now carry it, in ascending cost:

1. **A compaction card on the usage screen**, from one extra grouped query. It
   is a ratio rather than a count, because eleven compactions is unremarkable
   against forty thousand requests and alarming against twelve; the denominator
   was already on that response. It renders at zero, because an operator who has
   just enabled the setting is asking whether it does anything and a card that
   vanishes on "no" cannot be told from a screen that never had one.
2. **`GET /admin/usage/records`**, one page of individual requests, with a
   `compacted` filter. One path rather than the `/usage` and `/usage/me` pair
   beside it: a chart is a claim about a population so who it counts belongs in
   its name, while a row is the same object whoever reads it, and the reader who
   may see only their own still wants the filters to work. That is the shape
   `read_refusals.py` settled first.
3. **The transcript marker**, above.

**Making that table readable is a new disclosure, not a new query**, and it is
audited accordingly. `usage.read_any` fires when somebody lists an account that
is not their own, on the same line `refusal.read_any` draws: aggregate charts
describe a tenant, while one row per request with a timestamp describes how a
person works. Reading your own is not recorded, for the reason `prompt_log.list`
is not.

One detail recurs at every layer and is the same mistake each time: **tier 0 is
a compaction.** The SQL filter is `is_not(None)`, the Prometheus branch is
`is not None`, the React conditions are `!== null`, and the zod schema keeps the
zero. A truth test anywhere in that chain would have hidden the cheapest tier —
the one a reader is least likely to expect and most likely to meet.
