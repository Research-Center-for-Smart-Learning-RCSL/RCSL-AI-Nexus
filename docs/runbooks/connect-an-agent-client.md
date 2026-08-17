# Runbook: Point a Coding Agent at This Deployment

For connecting Codex, or any other OpenAI-compatible agent client, to the
gateway. Written for Codex because that is what it was built for; nothing here
is specific to it beyond the configuration file in section 3.

**The direction of the connection is the thing to get straight first.** The
agent is the client and this platform is the server. Nothing is installed here
for the agent's benefit: the gateway gained tool calling, and any client that
speaks the OpenAI chat API can now use it. You configure the agent to point at
the gateway, not the other way round.

```
Codex CLI / IDE extension
      |
      |  POST https://<gateway>/v1/chat/completions
      |  Authorization: Bearer nx_live_...
      v
  Nexus gateway  ->  routing policy  ->  Ollama or MLX on the Mac Studio
```

Related: [`architecture/backend.md`](../architecture/backend.md) section 6 for
the streaming and tool-calling contract, and the `/api-docs` page in the
management UI for the wire reference an integrator reads.

> **Working as of 2026-08-07, and the configuration below changed that day.**
> Two things were fixed. The inference host was serving from a duplicate NPM
> server block that discarded the correct one, so the perimeter headers written
> in August had never taken effect; NPM's proxy host for that name was disabled
> and the hand-written block took over. And **`wire_api = "chat"`, which this
> runbook told you to set, has been impossible since February 2026** — Codex
> removed Chat Completions support six months before this file recommended it.
> The gateway now serves `/v1/responses` as well, and section 3 says
> `wire_api = "responses"`. Verified end to end the same day: real Codex, real
> public entrance, a tool call executed and answered.
>
> **Amended 2026-08-09, from a real session rather than a harness.** Three
> things this file got wrong survived that verification, because each was
> something nobody had tried rather than something that had failed: replies
> were being cut off mid-sentence and reported as complete (section 5.1),
> Codex in the ChatGPT desktop app was described as impossible when it works
> and needs no separate setup (section 3), and there was nothing anywhere
> about how to undo any of it (section 3.1).

---

## 1. Choose and prepare the capability

An agent should not share a capability with the chat UI. They want opposite
settings, and the capability is the unit both are configured at.

1. In the management UI, **Routing policies**, create or edit a policy for
   `code`.
2. Point it at a model that **supports function calling**. This is the
   constraint that decides whether any of this works: not every model Ollama
   can run emits tool calls, and one that cannot will answer an agent with
   prose forever. Check the model's own documentation rather than assuming.
3. Set **Deliberation** to *Answer directly*.

Step 3 is not a preference. An agent pays the deliberation cost again on every
tool round trip, so a ten-step task reasons ten times over, and a thinking model
on this hardware has been measured spending an entire 16384-token budget without
producing an answer at all. The setting is per capability precisely so that
`chat` can keep deliberating while `code` does not.

**On this deployment steps 1–3 are already done**, and there are measured
numbers under step 3 rather than an argument. The `code` policy points at
`gemma4-31b` with deliberation off (`glm47-flash` until 2026-08-07). Running the same
five-tool-call debugging task three times each way:

| on `gemma4-31b` (2026-08-07) | wall clock | output tokens |
|---|---|---|
| deliberating | 23.0 / 18.2 / 22.1 s | 404 / 314 / 399 |
| answering directly | 13.6 / 11.5 / 13.0 s | 177 / 167 / 185 |

**Answering directly takes 60% of the wall clock on 47% of the output —
reductions of 40% and 53% — and solved the task 6 times out of 6 either way.**
Stated both ways because an earlier version of this line said "40% of the
clock", directly under the table, where it reads as the ratio between the rows
rather than the saving. The same measurement on `glm-4.7-flash` gave 42% and
46%; two different models agreeing that closely suggests this is a property of
the task rather than of either model. Reproduce with `scripts/measure-agent-loop.py`. Note that the saving is in
*output* tokens: reasoning is never replayed into the next prompt, so it costs
per turn rather than compounding through the conversation the way tool output
does.

**The policy names one model and no fallback, deliberately.** `chat` falls back
to `qwen7b` when the main model is not loaded, which is right for a person — a
smaller answer beats no answer. It is wrong for an agent: a weaker model does
not fail, it writes worse code, and nothing in the transcript says which model
wrote it. So `code` returns `503 no_available_model` instead, which is a thing
the operator can act on. Add a fallback only if you would rather have the work
done badly than not at all.

## 2. Issue a key sized for an agent

**API keys**, issue a new one for the `code` capability. Two of the defaults are
wrong for this caller and both fail in ways that look like the platform is
broken:

- **Requests per minute.** An agent makes one request per step, and a single
  task is tens of steps. A limit sized for a person typing will hit `429
  rate_limited` in the middle of a task.
- **Daily token quota.** An agent replays the whole conversation on every turn,
  and `prompt_tokens` counts towards quota (since 2026-08-04). Consumption is
  therefore roughly quadratic in the length of a task, not linear. Size this
  generously or leave it unset.

Set the CIDR allowlist if the machine running the agent has a fixed address. It
is the one control that survives the key leaking, and an agent's key sits in a
developer's environment rather than in a deployment.

## 3. Configure the client

For Codex, `~/.codex/config.toml`:

```toml
model = "code"
model_provider = "rcsl"

[model_providers.rcsl]
name = "RCSL AI Nexus"
base_url = "https://llmapi.rcsl.online/v1"
env_key = "RCSL_API_KEY"
wire_api = "responses"
```

Then export the key: `export RCSL_API_KEY=nx_live_...`

Four things are easy to get wrong:

- **`model` takes a capability, not a model name.** `code`, not
  `qwen2.5-coder:32b`. This is the platform's one real divergence from other
  providers and it is deliberate; the routing policy decides what actually
  serves the request. `GET /v1/models` lists what your key may ask for.
- **`wire_api = "responses"` is required**, and this line is the one that has
  changed. Codex dropped Chat Completions in February 2026; the gateway grew
  `/v1/responses` on 2026-08-07 to meet it. A client old enough to accept
  `"chat"` can still use `/v1/chat/completions`, which is unchanged and remains
  the documented interface for everything else.
- **`base_url` ends in `/v1`.** The client appends the path for the wire API it
  speaks — `/responses` under the setting above, `/chat/completions` under
  `"chat"`. This line said `/chat/completions` unconditionally until
  2026-08-14, which had been wrong since the line above it changed: it told
  anyone debugging a `responses` client to go looking at the wrong endpoint's
  logs. `/models` is appended the same way.
- **Do not choose a model in the client's own picker.** It overrides the `model`
  line above, and every model it offers is one this deployment refuses. Codex
  `0.148.0` fills that list from `GET /v1/models` in a shape of its own —
  `{"models": [...]}`, carrying its per-model metadata — while this gateway
  answers in OpenAI's `{"object": "list", "data": [...]}`, which every client
  library reads and its picker does not. Finding nothing it recognises, the
  picker falls back to Codex's built-in models, so `code` is not among the
  choices and anything chosen there produces `403 capability_not_issued`. This
  cost two integrators an evening on 2026-08-14, and the printout of a script
  that had correctly written `model = "code"` was what made it hard to see.
  `codex -c model=code` overrides a selection already made.

- **Codex's auxiliary model slots read their own slug, not `model`.** The one
  seen so far is `codex-auto-review`, which the client sends before running a
  command it wants to escalate. It is a built-in slug like any other, so it
  answers `403 capability_not_issued` no matter what `model` says — and because
  the refused call is the *review*, what the user sees is the escalated command
  failing, not a model error. On 2026-08-17 an agent read that 403 as a
  filesystem permission problem and spent four rounds trying PowerShell, then
  Node, then Python to write one file, none of which could have worked.

  Nothing needs granting: `codex-auto-review` is not a capability, so there is
  no capability to issue. Turn the auto-review off, or point that slot at `code`
  if your version exposes a setting for it. Check the gateway log for the slug —
  `capability_not_issued` names it — before believing any other explanation of a
  blocked write.

  **`codex-auto-review` is a real slot; `gpt-5.6-luna` was the picker again.**
  On 2026-08-17 one key was refused for `gpt-5.6-luna` 78 times in four bursts,
  each beginning within minutes of a `context_too_long` cluster, and the entry
  written that evening guessed at an automatic compaction step while saying the
  mechanism was not established. It was not compaction. A `models_cache.json`
  read from a client machine later the same night lists the picker's own models
  — `gpt-5.6-sol` at priority 1, `gpt-5.6-terra` at 2, **`gpt-5.6-luna` at 3** —
  so luna is an ordinary user-selectable model and those bursts are the picker
  trap in the bullet above, recurring: refused by the ceiling, somebody reached
  for another model, and every model the picker offers is one this deployment
  turns away. The correlation with the 413s was real and the inference from it
  was wrong.

  The same file separates the two cases cleanly. `codex-auto-review` is in it at
  priority 43 carrying `"visibility": "hide"` — a model the picker will not show
  and the client selects on its own — which is what makes it an auxiliary slot
  and luna not one. **Read `models_cache.json` before theorising about a slug**:
  it is the client's own list, it says which slugs are selectable and which are
  hidden, and it settled in one read a question two evenings of gateway logs
  could not.

  The gateway does not answer in Codex's shape, and that is a decision rather
  than a gap. `construct_model_info_from_candidates` takes a matched remote
  entry **whole**, so a slug we advertise no longer falls back to the client's
  local metadata — and that metadata is where the agent's entire system prompt
  comes from. Advertising `code` without also serving some 20,000 characters of
  Codex's own instructions, re-checked against every client release, would
  leave the agent running with none: no sandbox rules, no tool protocol, and no
  error. An unknown slug reaching the local fallback is what makes `model =
  "code"` work today.

**Every local Codex surface reads this one file**: the CLI, the IDE extension,
and the Codex built into the ChatGPT desktop app. Configuring the CLI therefore
configures all three, which is a correction — this file and the `/agent-setup`
page both said the desktop app could not be pointed here, and on 2026-08-09 an
operator connected the CLI and watched the app switch over with nothing
configured inside it. Neither document had tested it; both stated it anyway.
**The sharing runs the other way too, and that direction breaks the connection
outright — see 3.2 before connecting a machine that has the desktop app.**

What remains true is narrower: **Codex on the web** (`chatgpt.com/codex`) runs
on OpenAI's machines, reads no file on yours, and cannot be pointed at a custom
endpoint.

**Confirm the field names against your installed version** (`codex --version`)
before spending time debugging. This file records what the gateway needs; the
client's configuration schema is not ours and has changed between releases.

### 3.1 Undoing it, and running both

The configuration above changes the client's **default**, which is why the
desktop app followed the CLI across without being asked. Whoever connects an
agent should be told how to reverse that in the same breath as how to do it —
a default someone does not know how to unset is a worse thing to have handed
them than one they chose per invocation.

- **Back to the client's own default.** Delete the `model` and
  `model_provider` lines from `~/.codex/config.toml`. The
  `[model_providers.rcsl]` block may stay: it *describes* a provider, and
  nothing selects it once those two lines are gone. Restart the desktop app,
  which reads the file at startup. `codex login` may be needed to use OpenAI
  again, since pointing here never required it.
- **Both, side by side.** Put the provider block in
  `~/.codex/rcsl.config.toml` and leave `config.toml` untouched, then run
  `codex --profile rcsl`. Plain `codex` stays on the default. In `0.147.0`
  `--profile <name>` layers **a separate `$CODEX_HOME/<name>.config.toml`**
  over the base config — not a `[profiles.<name>]` table inside `config.toml`,
  which is what older guides describe and what this file would have said had
  `codex --help` not been read first. The same caution as above, applied.
- **Once, without writing anything.** `codex -c model_provider=rcsl -c
  model=code`.

**None of these disconnect anything on this side**, and it is worth being clear
with an integrator about that. They are settings on a machine you control, and
a copy of the configuration elsewhere keeps working. The disconnect this
platform enforces is **revoking the key** (section 2), which is also the only
one that helps if the key has reached somewhere you did not intend.

### 3.2 The same sharing, in the direction that breaks it

**A machine with the ChatGPT desktop app installed cannot be connected through
`~/.codex` at all**, and the reason is the shared file the section above treats
as a convenience. The app does not only *follow* the CLI's configuration; it
*owns* that directory, rewrites it, and hands the CLI its own tool surface.

Measured on 2026-08-17 against a teacher's Windows machine, app build
`26.810.52044`, client `0.148.0`. Every request carried **286 tool definitions
estimated at 122,870 tokens** — more than the entire 98,304 ceiling on its own,
so no conversation of any length could be sent. The conversation was 17,000
tokens across four messages, seven per cent of the payload. Four attempts over
twenty minutes produced a byte-identical tool figure while the message count
moved, which is the signature to recognise: **a share that does not change when
the conversation does is not a conversation problem.**

The source was `[mcp_servers.node_repl]` — the app's computer-use and browser
runtime — plus five bundled plugins: `chrome`, `sites`, `browser`,
`computer-use`, `visualize`.

**Three things kept that out of sight for an hour, and each looked like
evidence of innocence:**

- `codex mcp list` answered `No MCP servers configured yet` while
  `[mcp_servers.node_repl]` was in `config.toml`.
- `config.toml` read clean of plugins, then read with one plugin, then with
  five, `[marketplaces.openai-bundled].last_updated` moving twice inside fifteen
  minutes.
- Quitting the app changed nothing, because what the CLI reads is the file the
  app already wrote.

**The app rewrites `config.toml` continuously**, so every read is a snapshot
between two rewrites and any hand-written block is temporary — the
`[model_providers.rcsl]` block written that evening was gone by the next read,
replaced by the app's own `model = "gpt-5.6-sol"`. Do not diagnose from one
read of that file, and do not expect a provider block to survive in it.

**The remedy is a separate `CODEX_HOME`**, holding nothing but the eight lines
of section 3:

```powershell
$env:CODEX_HOME = "C:\Users\<user>\codex-nexus"
codex
```

The app cannot reach that directory, so the CLI starts with its own native tool
set instead of inheriting the desktop surface. Set it per shell rather than with
`setx`: a machine-wide `CODEX_HOME` moves the app too.

**Reverting needs one more step than it looks.** Deleting `model` and
`model_provider` leaves the app erroring at startup that the provider is not
found, because a conversation created against that provider still references it.
Deleting that conversation cleared it; the state file was renamed aside first
and turned out not to be the cause.

### 3.3 What a conversation costs before anybody types

**A new conversation does not start at zero, and the part that is not zero is
the part a client controls.** Three sessions opened on 2026-08-17 began at
42,005, 42,427 and 42,080 estimated tokens -- tool definitions, the agent's
instruction file, and whatever was pasted to start. Against that day's ceiling
that left about 38,000 for the work, and the turns that wrote files cost around
10,000 each, so the session had roughly four turns in it. **The operator read
that as the platform getting weaker over the evening.** It was the starting
position.

The gateway now says so without waiting for a refusal: when tool definitions are
at least half the estimate and worth at least a tenth of the ceiling, a line is
logged naming the share, the count and that they are resent every turn. It fires
on requests that succeed, which is the point -- the two clients diagnosed that
day were both diagnosed from a refusal, after the work was lost.

Three things to check on the client, in order of what they usually cost:

- **The tool list.** Resent whole on every turn, so it is charged once per step
  of a task rather than once per task. See 3.2 for the case where it exceeded
  the entire ceiling on its own.
- **The instructions file** (`AGENTS.md` and whatever the client layers on top).
  Also resent every turn.
- **What gets read into the conversation.** A large file read once stays in the
  payload for every subsequent turn, so re-reading it is not the expensive part
  -- reading it at all is.

None of these are settings on this platform, and the ceiling is not the lever
that fixes them: doubling it doubles how long a session runs before it stops.

## 4. Check it end to end

Before involving the agent, confirm the platform half with curl. A failure here
is a deployment problem; a failure only inside the agent is a configuration or a
model problem, and separating the two saves the most time.

```bash
curl https://llmapi.rcsl.online/v1/chat/completions \
  -H "Authorization: Bearer $RCSL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "code",
    "messages": [{"role": "user", "content": "list the files here"}],
    "tools": [{"type": "function", "function": {
      "name": "sh",
      "description": "Run a shell command",
      "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}
    }}]
  }'
```

**What a working response looks like:** `finish_reason` is `tool_calls`, and
`choices[0].message.tool_calls` holds a call with an `id`, a `name` and an
`arguments` string.

**What the interesting failure looks like:** 200, `finish_reason: "stop"`, and
a `content` full of prose about listing files. That is the model declining or
being unable to call tools, and it is the one failure mode no error will tell
you about. Try a different model before touching anything else.

## 5. Known limits

| Symptom | Cause |
|---|---|
| `413 context_too_long` mid-task | The conversation grew past `MAX_CONTEXT_LENGTH`. Tool definitions and replayed calls count towards it, so a long agent session reaches it by accumulation. Start a fresh conversation, or raise the setting knowing what section 4.3 of security.md says about it |
| `400 runtime_capability_unsupported` | The client sent `tool_choice: "required"` or named a function. Neither runtime can constrain decoding, so it is refused rather than quietly served as `auto`. Configure the client to send `auto` |
| `403 capability_not_issued` | The `model` field named something this key may not call — most often the client's own default model name rather than a capability. The message names what you asked for and what you may ask for instead; `GET /v1/models` is the same list. See section 3 |
| `429` early in a task | The key's requests-per-minute limit. See section 2 |
| `503 runtime_timeout` on long conversations | Prompt evaluation outran the platform's read timeout. Retry immediately, once — the prompt is now in the runtime's prefix cache and the retry is nearly free. If the agent's SDK timeout is shorter than ~1600s it will kill the connection first and you will never see this code; size it up (see `/api-docs`, Timeouts) |
| `503 overloaded` | Every inference slot was busy for the whole two-minute queue wait. The deployment is full, not broken; back off for `Retry-After` |
| `400 runtime_capability_unsupported` on a replayed conversation | An assistant turn in the history carries `arguments` that are not valid JSON, and Ollama takes arguments as an object, so the platform refuses before sending. Repair or drop that turn — retrying replays the failure |
| `422` naming `functions` or `function_call` | The client sent the deprecated OpenAI spellings, which are refused rather than silently ignored (before 2026-08-05 they were dropped, and the client stalled with prose and no error). Configure it to send `tools` / `tool_choice` |
| `422` on **every** request, naming an `input` tag that "does not match any of the expected tags" | A Codex newer than the shapes this endpoint was built against sent an input item the gateway did not know. `additional_tools` did this on 2026-08-14, before the fix that accepted it and offered the tools it carries. Any *other* unknown tag now costs that item alone, so this should no longer be a total failure — report the tag if you see it, and check `X-Dropped-Input-Items` on the response |
| Very slow first token on every step | Deliberation is still on for the capability. See section 1, step 3 |
| Tool calls never happen, no error | The model does not do function calling. See section 4 |
| The reply stops mid-sentence, no error | The conversation has crowded the answer out of the model's context window. See 5.1 |

Two behaviours that are correct but surprising:

- **`n` other than 1 is refused.** The platform serves one choice per request.
- **`parallel_tool_calls` is accepted and ignored.** Neither runtime offers a
  way to bound how many calls a model emits in one turn, and dropping the
  extras here would discard output the model produced and the caller paid for.
- **An input item the gateway does not recognise is dropped, not refused.** It
  is named once in `X-Dropped-Input-Items`; a tool type it does not recognise
  is named in `X-Dropped-Tools`. Both headers exist because the alternative to
  a narrowed request is a failed one, and the alternative to a header is
  narrowing it in silence. Tools declared in an `additional_tools` item are
  *not* in that category — they are offered to the model like any other.

### 5.1 The reply that stops mid-sentence

**A context window holds the prompt and the answer in the same space.** Ollama
is given `num_ctx` from the model's registered `context_length`, and what is
left to answer in is that figure minus everything the prompt already occupies.
An agent replays the whole conversation on every turn and grows it with file
contents and tool output, so the room to answer in shrinks with every step of a
task, reaching zero while the task is still going.

Measured on this deployment on 2026-08-09, from a real Codex session — one row
in `usage_records`:

| | tokens |
|---|---|
| prompt | 32231 |
| reply | 537 |
| `num_ctx` for `gemma4-31b-q8` | 32768 |

**32231 + 537 = 32768 exactly.** The model did not choose to stop; it ran out
of window, in the middle of a sentence.

**Two things made this worse than it needed to be, both ours, both fixed the
same day.**

**The guardrail was at the wrong height.** `MAX_CONTEXT_LENGTH` is 65536 — the
ceiling on what a caller may *send* — against a registered window of 32768.
The check that exists to refuse an oversized prompt was admitting prompts that
left no room for an answer, and `413 context_too_long` never fired because the
prompt was never the thing that was too long. `num_predict = 16384` could not
help either: it bounds an answer from above, and this one was bounded from
below by what was left over.

**`gemma4-31b-q8` now registers `context_length = 131072`**, twice what a
caller may send, so a full 65536-token prompt still leaves 65536 to answer in
and the window cannot be the thing that binds. This cost almost nothing, which
is the part worth recording — measured on 2026-08-09 by loading the same
weights at both sizes:

| `num_ctx` | resident |
|---|---|
| 32768 | 31.36 GiB |
| 131072 | 31.47 GiB |

**0.11 GiB for four times the window.** `gemma4` is almost entirely sliding-
window attention — 60 layers against `attention.sliding_window = 1024` — so
only the few full-attention layers scale with context at all. The window had
been costed as if it were an ordinary dense model and set low to be safe; it
was never expensive. Residency is 36.39 GiB against the 51.2 GiB budget, up
from 36.30. `gemma4-31b` (the q4 build kept as the rollback) was raised with
it: same architecture, same layer count, and a KV cache that does not depend on
weight quantisation — **inferred from the measurement above rather than
separately measured**. `glm47-flash` is left at 32768 for the opposite reason:
different attention, and nobody has measured it.

**And nothing told the client.** Ollama reports `done_reason: "length"`, and
`/v1/chat/completions` passes it through as `finish_reason: "length"` — the
signal an OpenAI client reads to know a reply was cut. The `/v1/responses`
translation dropped it: `interfaces/http/responses_sse.py` never read
`chunk.finish_reason`, so it emitted `response.completed` whatever happened,
and `_collect` hardcoded the same for the non-streaming path. So Codex — which
speaks `responses`, per section 3 — was told a truncated answer was a whole
one.

That module now ends a cut-off stream with **`response.incomplete`**, carrying
`status: "incomplete"` and `incomplete_details: {"reason":
"max_output_tokens"}`, with the text item marked `"incomplete"` beside it; the
non-streaming body reports the same. There are three terminal events, not two,
and the missing one was the common case. `"length"` is the only reason that
means truncation — `"stop"` and `"tool_calls"` stay `completed`, and a test
holds that line, because reporting an ordinary end as incomplete would tell an
agent to continue a turn the model had finished.

**What can still truncate**, honestly and now visibly: the 16384-token output
ceiling, and the 900-second generation deadline. Both report `length` and both
arrive as `response.incomplete`.

`usage_records` remains where to confirm any of this. `prompt_tokens` close to
the model's `context_length` was the tell, and `completed` is `true` on those
rows because the cut happened inside the runtime rather than at the platform's
own ceiling — which is itself worth knowing when reading the table.

### 5.2 Prompt evaluation is slow, and nginx is not the thing that cuts it

Raising the window moves the constraint rather than removing it. Prompt
evaluation produces no bytes at all while it runs, and the 32231-token prompt
above took **273 seconds** of silence — 117.9 tok/s, the same figure
[`PROGRESS.md`](../PROGRESS.md) recorded on 2026-07-27. A first turn or a cache
miss pays that in full; a continuing conversation re-evaluates only its new
tokens, which is what makes the cost easy to miss.

> **This section said, until 2026-08-09, that `proxy_read_timeout` on the
> inference host was `300s` and that a long prompt was 27 seconds from being
> cut. That was wrong, and it was already recorded as wrong in this
> repository.** On 2026-08-07, after shell access to the proxy host, the
> running configuration for `llmapi.rcsl.online` was read directly: its
> `proxy_read_timeout` is **86400s** ([`PROGRESS.md`](../PROGRESS.md),
> 2026-08-07). The `300s` figure came from [`ROADMAP.md`](../ROADMAP.md), which
> was never updated after that reading — and `PROGRESS.md` states in its own
> header that when the two disagree, it is the other file that is wrong.
>
> **The 273-second measurement was offered as evidence and is not.** That
> request *completed*. A request that finishes tells you the limit was not
> reached; it cannot distinguish `300s` from `86400s`. Only a request that runs
> **past** a suspected limit distinguishes anything.

So there is no cliff at 300 seconds, and the truncation in 5.1 had nothing to
do with nginx. The correct statement is narrower: **prompt evaluation is the
dominant cost of a long agent turn, and no proxy timeout on this deployment is
currently close to binding it.**

What is still worth doing is the opposite of what this section used to ask for.
`86400s` is a day, which is generous to the point of not being a backstop at
all: `proxy_read_timeout` is what reclaims a connection from an upstream that
has genuinely hung, and worker connections are finite. Lowering it to `3600s`
— comfortably above the 556-second worst case a full `MAX_CONTEXT_LENGTH`
prompt costs, and above the platform's own 1500-second per-request budget —
would restore that property. **It is a tidy-up with no user-visible symptom
behind it, not a fix**, and it should be described that way to whoever owns
that machine.

Both hosts read `86400s`, confirmed by `nginx -T` on 2026-08-09 — including
the management host, whose directives had never been read before that. The same
command showed `proxy_buffering off` live on both, and `server_name
llmapi.rcsl.online` appearing exactly once with no conflict warning, so the
duplicate-block repair of 2026-08-07 is holding.

## 6. Debugging an integration

Every response carries `X-Request-Id`, and every error body repeats it as
`error.request_id`. Quote it when reporting a failure — the platform's log
keys on it, and it is the difference between an administrator grepping
timestamps and finding the exact line.

**Since 2026-08-18 the request id is enough on its own for a refusal.** Every
refusal the platform produces is stored with the code, the status, the message
the caller received and the figures that came with it, and an administrator
reads it back on the **Refusals** screen — so "what happened at 19:16?" is a
search rather than a grep through container logs, which is what it was twice on
2026-08-17. A `429` is the case that gains most: the wait it asked for is a
header, and the header is gone by the time anybody comes to look.

The screen shows a caller their own refusals as well, so an integrator with an
account can answer the question without asking anybody. Nothing about the
request is stored — no messages, no tool definitions, no model name — so what
is there is exactly the answer that was sent.

For an active debugging session, open a **debug window** on the key (API keys
page, the Debug button: one hour per press, capped at 24, audited). While it
is open, error responses to that key carry `error.detail` — the
operator-facing explanation that is otherwise log-only, which turns "401
Authentication required" into "source 203.0.113.9 not permitted for
nx_live_abc" at exactly the moment you are debugging a CIDR list.

## 7. Do not point an agent at MLX yet

The MLX tool path is written but has never run against a live `mlx_lm.server`.
A build without tool support will accept the `tools` field and answer with
prose, which is indistinguishable from a model that chose not to call anything.
Keep agent capabilities routed to Ollama until that is verified; the open item
is in [`ROADMAP.md`](../ROADMAP.md) Phase 2.
