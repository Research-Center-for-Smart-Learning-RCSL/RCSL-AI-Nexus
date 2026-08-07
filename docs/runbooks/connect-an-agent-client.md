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

Three things are easy to get wrong:

- **`model` takes a capability, not a model name.** `code`, not
  `qwen2.5-coder:32b`. This is the platform's one real divergence from other
  providers and it is deliberate; the routing policy decides what actually
  serves the request. `GET /v1/models` lists what your key may ask for.
- **`wire_api = "responses"` is required**, and this line is the one that has
  changed. Codex dropped Chat Completions in February 2026; the gateway grew
  `/v1/responses` on 2026-08-07 to meet it. A client old enough to accept
  `"chat"` can still use `/v1/chat/completions`, which is unchanged and remains
  the documented interface for everything else.
- **`base_url` ends in `/v1`.** The client appends `/chat/completions`.

The CLI and the IDE extension read the same file. The ChatGPT-hosted web version
cannot be pointed at a custom endpoint at all.

**Confirm the field names against your installed version** (`codex --version`)
before spending time debugging. This file records what the gateway needs; the
client's configuration schema is not ours and has changed between releases.

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
| `429` early in a task | The key's requests-per-minute limit. See section 2 |
| `503 runtime_timeout` on long conversations | Prompt evaluation outran the platform's read timeout. Retry immediately, once — the prompt is now in the runtime's prefix cache and the retry is nearly free. If the agent's SDK timeout is shorter than ~1600s it will kill the connection first and you will never see this code; size it up (see `/api-docs`, Timeouts) |
| `503 overloaded` | Every inference slot was busy for the whole two-minute queue wait. The deployment is full, not broken; back off for `Retry-After` |
| `400 runtime_capability_unsupported` on a replayed conversation | An assistant turn in the history carries `arguments` that are not valid JSON, and Ollama takes arguments as an object, so the platform refuses before sending. Repair or drop that turn — retrying replays the failure |
| `422` naming `functions` or `function_call` | The client sent the deprecated OpenAI spellings, which are refused rather than silently ignored (before 2026-08-05 they were dropped, and the client stalled with prose and no error). Configure it to send `tools` / `tool_choice` |
| Very slow first token on every step | Deliberation is still on for the capability. See section 1, step 3 |
| Tool calls never happen, no error | The model does not do function calling. See section 4 |

Two behaviours that are correct but surprising:

- **`n` other than 1 is refused.** The platform serves one choice per request.
- **`parallel_tool_calls` is accepted and ignored.** Neither runtime offers a
  way to bound how many calls a model emits in one turn, and dropping the
  extras here would discard output the model produced and the caller paid for.

## 6. Debugging an integration

Every response carries `X-Request-Id`, and every error body repeats it as
`error.request_id`. Quote it when reporting a failure — the platform's log
keys on it, and it is the difference between an administrator grepping
timestamps and finding the exact line.

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
