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
wire_api = "chat"
```

Then export the key: `export RCSL_API_KEY=nx_live_...`

Three things are easy to get wrong:

- **`model` takes a capability, not a model name.** `code`, not
  `qwen2.5-coder:32b`. This is the platform's one real divergence from other
  providers and it is deliberate; the routing policy decides what actually
  serves the request. `GET /v1/models` lists what your key may ask for.
- **`wire_api = "chat"` is required.** Codex speaks the Responses API to OpenAI
  itself; this gateway serves `/v1/chat/completions` and has no `/v1/responses`.
  Without this line the client will call a path that does not exist.
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
| `400 runtime_capability_unsupported` on a replayed conversation | An assistant turn in the history carries `arguments` that are not valid JSON, and Ollama takes arguments as an object, so the platform refuses before sending. Repair or drop that turn — retrying replays the failure |
| `422` naming `functions` or `function_call` | The client sent the deprecated OpenAI spellings, which are refused rather than silently ignored (before 2026-08-05 they were dropped, and the client stalled with prose and no error). Configure it to send `tools` / `tool_choice` |
| Very slow first token on every step | Deliberation is still on for the capability. See section 1, step 3 |
| Tool calls never happen, no error | The model does not do function calling. See section 4 |

Two behaviours that are correct but surprising:

- **`n` other than 1 is refused.** The platform serves one choice per request.
- **`parallel_tool_calls` is accepted and ignored.** Neither runtime offers a
  way to bound how many calls a model emits in one turn, and dropping the
  extras here would discard output the model produced and the caller paid for.

## 6. Do not point an agent at MLX yet

The MLX tool path is written but has never run against a live `mlx_lm.server`.
A build without tool support will accept the `tools` field and answer with
prose, which is indistinguishable from a model that chose not to call anything.
Keep agent capabilities routed to Ollama until that is verified; the open item
is in [`ROADMAP.md`](../ROADMAP.md) Phase 2.
