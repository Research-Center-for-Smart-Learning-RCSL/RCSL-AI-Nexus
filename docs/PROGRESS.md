# Progress Log

What has actually been built, in the order it happened, and what was learned
doing it. Newest first.

This is the narrative record. Two other places describe state and neither
replaces this one:

- [`ROADMAP.md`](./ROADMAP.md) is the plan, item by item.
- [`architecture/security.md`](./architecture/security.md) section 13.0 is a
  checked control-by-control inventory of what exists.

If those two disagree with this file, they are wrong: update them here first
and propagate. The reason for saying so is that they have already drifted once.

---

## 2026-08-05

### A local model does drive an agent loop, and deliberation costs 42% of the wall clock

The question the whole 2026-08-05 tool-calling change was aimed at, and the one
the code could not answer: *can `glm-4.7-flash` hold up its end?* Measured
rather than argued, on a ladder of ten rungs, simplest first, so that a failure
would name the missing ability instead of reporting "the agent did not finish".

All ten passed. Every request was served by `glm47-flash` through the `chat`
capability — confirmed from `usage_records` rather than from the response, since
the gateway echoes the capability alias by design and would have looked
identical had it fallen back to `qwen7b`.

The rungs, in order: emit a call at all; fill an argument from the prompt;
complete the round trip and use the result; choose between two tools; chain two
calls where the second needs the first's answer; **not** call anything when the
question does not need it; two independent calls in one turn; recover from a
tool error; choose correctly from a menu of eight; and then the one that
actually resembles the work — *the tests are failing, find out why, fix the
source, re-run to confirm*, against a fake repository whose bug is `a - b` where
`a + b` belongs.

It solved that one every time, in six turns and about eleven seconds:

    run_tests → read tests/test_calc.py → read src/calc.py
    → write_file(src/calc.py, "return a + b") → run_tests → summarise

Nothing in the prompt said where the bug was. It ran the tests, read the
assertion, read the source, saw the sign, wrote the fix, and re-ran to confirm
before answering.

**The measurement worth keeping is the cost of thinking.** `OLLAMA_THINKING` is
true for this deployment and the `chat` policy takes that default, so every one
of those turns deliberated. Three runs each way, same task:

| | turns | wall clock | completion tokens |
|---|---|---|---|
| `think: true` | 6–7 | 9.4 / 11.5 / 12.7 s | 470 / 591 / 654 |
| `think: false` | 6 | 6.0 / 6.1 / 7.5 s | 275 / 283 / 366 |

**42% of the wall clock and 46% of the output tokens, with the task solved
6 out of 6 either way.** The ROADMAP predicted the shape of this on
2026-08-05 — "an agent on `code` deliberates again on *every tool round trip*;
a ten-step task reasons ten times over" — and this is the number under it. A
`code` capability should carry `thinking: false`, which is exactly what the
nullable per-policy column was added for.

One nuance that makes the cost smaller than it first looks: **reasoning is paid
for in output tokens but is not replayed into the next prompt.** An OpenAI
client sends back `content` and `tool_calls`, not `reasoning_content`, so
prompt tokens were within noise of each other either way (≈4.0–4.7k vs
≈4.1–4.3k). Deliberation costs per turn; it does not compound through the
context the way tool output does.

Three platform properties fell out of this as evidence rather than assertion.
**Two independent lookups in one turn arrived as two calls with two distinct
ids** — the property the "index runs across the whole stream, not per chunk"
fix exists for, seen from the client's side for the first time.
**`reasoning_content` and `tool_calls` coexist in one message**, so the
non-OpenAI extension does not disturb the OpenAI part. And **an actionable tool
error changed the next argument** rather than producing the same call again:
`get_population("Taipei")` → `ERROR: try the official name` →
`get_population("Taipei City")`.

**The perimeter also proved itself, by refusing.** The first request from this
host came back `untrusted_proxy`: the gateway requires the shared-secret header
and refuses to fall back to the peer address for `X-Forwarded-For`, so a
measurement run on the machine has to impersonate openresty to get in at all.
That is the control working, and it is worth writing down that a direct request
to the tailnet address is not a way around it.

Carried out with a single-use key scoped to `chat`, revoked immediately after —
the seventh such key in this deployment's history, and the reason the API keys
table hides revoked rows by default.

### The unverified MLX tool path is now refused, not merely warned about

Asked whether MLX needs installing, the honest answer turned out to be no, and
the question was better than the answer. Nothing here uses MLX: three models
registered, all Ollama, nothing listening on 8080, every capability served by
one runtime. The job MLX was given — *prove the hexagonal layering by adding a
second runtime without touching a use case* — was passed by the adapter
**existing**, not by it running. That verdict does not change whether a server
is up.

What remained was a trap rather than a task. The tool path is written and has
never run, and the failure it can produce is the one this whole feature exists
to remove: **a build without tool support accepts the `tools` field and answers
with prose.** The agent gets a 200 and waits for a call nobody requested. The
mitigation was a paragraph in the adapter's docstring — better than nothing, and
still a reachable path, so the platform would have served that failure once, to
whoever pointed a policy at MLX first. A documented absence and a working
feature look identical to a client library; that sentence has now been written
in this file three times about three different fields.

`MLX_TOOL_CALLING_VERIFIED`, default false, makes the adapter raise
`RuntimeCapabilityError` on a tool-carrying request — the same judgement `embed`
and `unload` already make there, and `should_send_tools` makes on an
unenforceable `tool_choice`. Refusing beats answering plausibly and wrongly.

**The guard sits on the branch that puts tools on the wire, not on the presence
of the argument**, which is the distinction worth having. `tool_choice: none`
sends no tools, so no client is waiting for a call and nothing silent can
happen; refusing it would have taken away a legitimate request. Plain
completion — MLX's only current use — is untouched, because a guard that took
the runtime out of service to protect a path nobody is on would be a worse
trade than the one it replaced.

**It cannot be a probe, and that is the whole difficulty.** There is no
capability endpoint, and a trial request settles nothing: a model that is
offered tools and legitimately declines to call one produces exactly what a
server that discarded the field produces. Not-calling is a valid answer, so the
absence of a call is evidence of nothing — which is precisely why this failure
is silent in the first place. That leaves a person who has read a real call off
the wire as the only thing that can assert it, and the setting records that
assertion rather than pretending to derive it.

Five tests, including one that the refusal happens **before** the network: a
guard that still sent the request would have served the failure it exists to
prevent and been indistinguishable in a test that only checks the exception.
Confirmed by removing the guard and watching two of them fail.

### The debug switch had a reader and no writer on the user half

The error-precision work earlier today closed `debug_logging_until` as "twelve
days of a switch wired to no lamp". It closed one of the two. The user half
kept the defect and hid it better.

`identity.py` read `user.debug_logging_until` and called `grant_debug_detail`
on it. `UserResponse` carried the field. The frontend schema declared it and
the Users table had it in scope. Every layer that consumes the value was
present and correct — and **nothing, anywhere, could set it**. No use case
method, no endpoint, no button. A grep for the column found it in eight files
and none of them was a writer.

**That is worse than the missing lamp, not better.** An unconsumed column is at
least visibly inert; a fully built read path reports a working feature from
every direction you might check it from. The API-key window shipped with a
button, so the control looked done, and the user column looked like the same
control seen from another table.

The reason the second half is not redundant is written into security.md §9.2
and had been since long before either half existed: *the management chat path
has no API key attached*. An administrator debugging the admin UI is
authenticated by a session cookie. There is no key to open a window on, so
until today the one operator most likely to need detail was the one who could
not be granted it — and the document asserting otherwise was, on that
sentence, simply false.

Now: `POST /admin/users/{user_id}/debug`, `ManageUsers.set_debug_window`, and
the same one-click toggle the API keys table carries, showing the minutes left
so a window left open is visible from the table rather than only from the error
bodies it widens. Audited as `user.debug_window_set`, which §12 gained a row
for — that table's survey predates both halves and listed neither.

Three decisions worth the ink:

**The ceiling moved out of the use case.** It was a class attribute on
`ManageApiKeys` and a restated literal in the request schema; a third copy in
`ManageUsers` would have made a single control into three independently
editable rules. It is one function in `domain/services/debug_window.py` now,
and the schema imports the constant instead of repeating it.

**`disabled_at IS NULL` is in the UPDATE, not in a check before it.** The same
reasoning `advance_totp_counter` records: read, compare in Python, write, and a
concurrent disable lands in the gap — leaving the window open on an account
nobody can sign in as, and telling the caller it was set. The repository
returns False and the use case turns that into a 409.

**No self-guard, unlike role change and disable.** Those are escalation and
lockout. This only changes what the caller is told about their own failures,
and debugging one's own admin session is the ordinary use rather than the
dangerous one.

**Verified on the deployment, not only by the suite.** Identical request twice
against the live tailnet entrance, differing only in the stored column:
`{"code":"user_not_found","message":"That account does not exist.",
"request_id":"req_..."}` with the window closed, and the same body plus
`"detail":"no user no-such-user"` with it open. Closing it took the detail away
again, 1441 minutes was refused by the imported ceiling, and the `audit_log`
holds both presses — `{"until": "2026-08-05T11:09:48+00:00"}` and
`{"until": "off"}`. The account was left as it was found.

### The deploy that reported success and shipped nothing

Getting to that verification cost a detour that is worth more than the feature.
`docker compose build gateway admin-tailnet admin-public frontend-tailnet`
printed `Image rcsl-ai-nexus-frontend:latest Built` and exited 0. The backend
image was untouched: **only `migrate` carries the backend `build:`**, by the
deliberate convention at the top of `docker-compose.yml` — services sharing a
tag would otherwise race to write it. Compose does not object to being asked to
build services that carry no build definition. It builds the ones that do, says
so, and succeeds.

`docker compose up -d` then recreated the two frontend containers and left the
backend alone, which also looked exactly like a successful deploy. Everything
was `healthy`. The only reason it was caught is that the verification asked the
running app a question it could fail: the new route was absent from
`/openapi.json`, and every check short of that would have passed.

This is the class the 2026-07-26 entry named — *checking in a way that can only
return one answer* — arriving from a fourth direction, and the sibling of
`docker compose up -d` being a no-op against a running container. **The command
is `docker compose build` with no arguments, or `migrate` and
`frontend-tailnet` by name.** Naming the service you actually changed is the
wrong instinct here and reads as the right one.

### The two things the deploy walked past, both now closed

**`csrf.py` was still explaining the bug it no longer had.** Its module
docstring said "the tailnet entrance does not install this. It has no ambient
credential: identity comes from a header injected by `tailscale serve` on each
request, and a hostile page cannot cause that header to be added."

That is not a stale sentence. It is the *exact false premise* that commit
`ec56046` removed on 2026-07-25, whose own message says so: "CSRF was absent
from the tailnet entrance on the false premise that it has no ambient
credential. `tailscale serve` attaches the identity header to any request a
hostile page can provoke, so a body-less POST — revoke, unload, download,
invalidate an invitation — was cross-site reachable."

The argument's second half is true and irrelevant: the page does not need to
add the header, because the proxy adds it to anything leaving that device,
including a request provoked from the browser of somebody signed in to the
tailnet. A header injected by the proxy is as ambient as a cookie attached by
the browser.

So the fix landed in `main_admin_tailnet.py` and the reasoning that had caused
the defect stayed where anyone reasoning about CSRF reads first, for eleven
days. **A fix that does not reach the explanation leaves the next person the
same premise to be wrong from** — and this file's history is of a control
"designed, written down, marked done, and not actually in force", which is the
same failure with the two halves swapped: in force, and still described as
absent. Corrected, with the reason recorded rather than the conclusion.

**The admin 422 now looks like every other admin error.** It was FastAPI's raw
`{"detail": [...]}` — no `code` to branch on and, since this morning, no
`request_id` to quote, which made a validation failure the one admin error a
caller could not correlate to a log line. The gateway's 422 was given its
envelope this morning; the admin side was not, and the asymmetry was invisible
because both are 422s carrying a readable string *somewhere*.

It cost the operator something concrete, not just consistency. The frontend's
`messageFor` reads `body.message`, then `body.detail` **if it is a string**;
pydantic's is a list, so both fell through to `Request failed with status 422.`
— a status number shown in place of a message that had already named the exact
field and rule. Three tests pin it now: each envelope's own shape, and one
asserting directly that neither still answers with a bare `detail` list, which
is what a regression would look like.

The test for it needed its own correction first. `class Body(BaseModel)`
declared inside the app factory cannot be resolved by FastAPI from the
annotation, so `payload` was read as a *query* parameter and the 422 under test
was about a missing query field rather than a body — passing for the wrong
reason. Module scope, and a comment saying why.

The tests are the actual deliverable here, because the code was never the hard
part. The two that existed handed `grant_debug_detail` a value directly, which
tests the consumer and says nothing about who supplies it — precisely the gap
the missing writer lived in. There are now two that drive the tailnet resolver
against a stored column and assert on the response body, joining the row to
what the operator receives, plus a frontend test that an open window *closes*
rather than re-opening. Each was confirmed by putting its defect back: the
resolver test fails when `grant_debug_detail(user.debug_logging_until)` becomes
`grant_debug_detail(None)`, the toggle test fails when the click always sends
60.

### The gateway can call tools, which is what "OpenAI-compatible" was missing

The API has been OpenAI-*shaped* since Phase 1: the right paths, the right
envelope, the right error format, `/v1/models`, bearer auth. What it was not is
OpenAI-*capable*, and the gap was one feature wide. Asked to serve a coding
agent, the platform accepted the request, returned 200, and did nothing useful,
because `tools` was dropped by pydantic's default `extra="ignore"` and the model
was never told there was anything to call.

**That is the worst shape a compatibility gap can take.** Nothing errors. The
agent sends its tool definitions, gets prose back, and stalls waiting for a call
that was never requested — and every layer in between reports success. The
ROADMAP had recorded the drop since 2026-07-30 as a documented absence, which
made it visible but not fixed; a documented absence and a working feature look
identical to a client library.

Tool calling now runs the whole way through: `ToolCall`, `ToolDefinition`,
`ToolChoice` and `SamplingOptions` in the domain, three new arguments on
`ModelRuntimePort.generate`, both adapters, the request schema, the SSE framing
and the non-streaming assembly. What is worth recording is not the plumbing but
the four places where getting it wrong would have been silent.

**Ollama ends a tool-calling turn with `done_reason: stop`.** True of the model,
wrong for the client. An agent loop branches on `finish_reason` alone to decide
whether to execute a call or show a person an answer, so "stop" means the calls
are never run and the conversation stalls with the model waiting on results
nobody will produce. The adapter rewrites it to `tool_calls` whenever calls were
emitted. Nothing upstream can detect this; the request succeeds either way.

**Ollama gives a call no id, and OpenAI requires one.** It is the handle a
client pairs its result back to, so the adapter mints it. It has to be unique
within a *conversation* rather than within a chunk — an index would restart on
the next turn and pair a result with the wrong call, which produces a coherent
conversation about the wrong thing.

**`arguments` stays JSON text through the domain.** It is model output, so it
can be malformed. The caller recovering from that needs the bytes the model
produced, not our re-encoding of a parse that may have succeeded by accident.
Ollama takes an object, so the adapter decodes on the way out — and when it
cannot, sends the raw string rather than a substitute, so a conversation whose
model once emitted invalid JSON stays replayable instead of becoming a
permanent 400.

**A `tool_choice` the runtime cannot enforce is refused rather than
downgraded.** `none` is exact everywhere and `auto` is the default, but
`required` and naming a function ask the runtime to constrain decoding, which
neither runtime here exposes. Serving `auto` instead would answer a caller who
demanded a call with prose, discovered inside their parser. Same judgement the
MLX adapter already makes on `embed` and `unload`.

### Frame order is the same lesson for the third time

`delta.tool_calls` has to be framed **before** the terminal frame, because a
runtime reports the call and the end of the turn in one event and a client that
has seen `finish_reason` has stopped reading deltas. This is the rule
backend.md §6 already states twice, from the two previous times it was got
wrong (`RouteChatRequest` on 2026-07-27, `ProposalCollector` on 2026-07-29).
Arrived at from a third direction and pinned by a third test asserting on order
rather than on content, which is the only kind of test that catches it.

The related one: the tool call index runs across the whole stream, not per
chunk. A client buffers calls keyed on `index`, so restarting the counter merges
two separate calls into one whose name and arguments are both concatenations of
the pair.

### Four documented absences became behaviours, and the page said the opposite

`/api-docs` is the whole of the consideration security.md §4.4 receives for
disabling `/openapi.json`, and it had been carefully written to say that
`tools`, `temperature`, `top_p`, `n` and `stop` parse and do nothing, that a
`tool` role is a 422, and that streaming carries no `usage` at all. All four are
now false. **A page documenting what a feature does not do is the kind that goes
stale silently**, so each is now stated with the date it changed rather than
quietly rewritten — an integrator reading it against an older deployment needs
to know which side of the change they are on.

The 422 gained an envelope while we were there. FastAPI answers a validation
failure with `{"detail": [...]}`, its own shape, and every OpenAI client library
reads `error.message` — so on the gateway a malformed request produced a body no
caller's code could surface, at exactly the moment they are still getting the
request right.

### Deliberation is per capability now, because an agent pays for it every turn

`OLLAMA_THINKING` was one setting for the whole deployment, and the three
capabilities want different answers: `chat` wants a model to think, `assist`
cannot afford it beside a settings form, and an agent on `code` deliberates
again on *every tool round trip* — a ten-step task reasons ten times over. It is
a nullable column on `routing_policies`, where null means "no opinion, take the
deployment default", which is what every policy written before it means.

The frontend half of that produced the one real bug of the day, caught by a test
written for the round trip rather than for either direction: the `<select>`
holds three strings and zod preprocesses `'default'` to null, so
`thinkingToApi` was written against the *parsed* type and read `'default'` as
"not on", which is `false`. Every policy edited through the dialog would have
silently come off the deployment default. Fixed by making the function total
over both the pre- and post-parse value instead of narrowing it, since nothing
in the types enforced which side it was called on — `z.preprocess` makes the
input type `unknown`, so TypeScript had nothing to object to.

### The context ceiling moved, and it could not move alone

32768 → 65536 tokens. An agent replays the whole conversation every turn and
grows it with file contents and tool output, so it crossed the old ceiling
within a few rounds and the 413 arrived in the middle of a task rather than at
the start of one.

**It was briefly 131072, which was wrong, and the reason is worth keeping.**
Prompt evaluation sends no bytes. So the thing that bounds it is not the
generation deadline but `REQUEST_TIMEOUT_SECONDS`, the per-read HTTP timeout —
and at the measured 117.9 tok/s of prompt evaluation on the largest model this
machine holds, 131072 tokens costs 1112 seconds against a 300 second timeout.
That is a 96,000-token band where the guardrail admits a request and the
transport then kills it, and not as a 413 the client can act on: an
`httpx.ReadTimeout` is not a `DomainError`, so it escaped the router's handler
as a bare 500, or mid-stream as a connection that simply stopped without
`[DONE]`. The three numbers are one decision:

    65536 / 117.9 = 556s of prompt evaluation, against a 600s read timeout

**The deadline was the same mistake one layer up.** Its clock started when the
request reached the runtime, before prompt evaluation, so a large prompt spent
the budget for the answer on reading the question — 556 seconds of it against
900. The stream was then cut on its first token reporting
`finish_reason: "length"`, telling the client the model had talked too much when
it had not yet started. It now starts at the first chunk, which makes the two
limits compose rather than overlap: the read timeout bounds reading, the
deadline bounds writing, and each is the limit that was designed for its job.

That composition has a consequence that the cross-file invariant test did not
catch, because it was checking the wrong quantity. One request's worst case is
now 600 + 900 = 1500 seconds, but the test compared the frontend's
`proxyTimeout` against the deadline alone, so it kept passing with the proxy at
960 seconds — **the original silent socket reset, moved from 30 seconds to 16
minutes**, which is the failure that test exists to prevent and the second time
raising a limit has handed the cut back to the proxy (the first was 2026-07-27).
`proxyTimeout` is 1560 s and the test now reads both figures out of
`.env.example` and compares against the sum. Verified by putting 960 back and
watching it fail.

This is one of the six resource guardrails security.md §4.3 counts on, so
raising it costs something real: context is superlinear on unified memory and
measured throughput already decays from 60.8 to 23.5 tok/s across a single
generation. The cost of the read timeout is paid by a *hung* runtime rather than
a busy one, since a producing stream resets it on every chunk: ten minutes
holding a slot instead of five. **The hole this would have opened is `tools`**:
tool definitions are arbitrary JSON that no person types, so a ceiling counting
only `messages` would have let a caller carry an unbounded payload straight past
it. They are counted.

### Review of the tool calling commit, and its four fixes

All four findings were real, and each was verified by reproducing it against
the running code before anything was changed. Three share a shape worth naming:
**a rule written when the last message was always the user turn.**

**`max_length=4` on `stop` capped the string at four characters.** The field is
`str | list[str] | None`, and pydantic applies a length constraint to every
member of a union it fits — four *items* for the list, four *characters* for the
string. So `"User:"` and `"\n\nObservation:"` were refused with a 422 whose
message talked about items. The count is now checked after normalisation, where
one string is one sequence. **The test written for this field used `"END"`**,
three characters, so it passed and hid the bug it existed to prevent; the
replacement is parametrised over realistic sequences. A test that picks the
smallest legal value tests the smallest legal value.

**Grounding split an assistant tool call from the result answering it.**
`ground()` inserted the retrieved-context message at `len(messages) - 1`, which
was the last user turn until this same commit added a `tool` role. In an agent
conversation the tail is an assistant turn carrying `tool_calls` followed by the
tool result, so the system message landed *between the pair* — and a chat
template pairs a tool result with the assistant call immediately preceding it,
so `use_knowledge: true` on any agent conversation produced a malformed prompt.
It now anchors on the last user message, which is what the docstring had
claimed all along and what `query_from` already picked; the two now agree.

**MLX could report `finish_reason: tool_calls` with no tool calls.** The flag
was set from having seen the key, while the accumulator drops any call that
never received a name. That is the same stall the finish-reason rewrite exists
to fix, arriving from the other end and worse: an agent waits to execute
something it was never given, with no content to fall back on. The reason is now
derived from what is actually being forwarded, and both adapters refuse to pass
a runtime's own `tool_calls` claim through when nothing survived parsing.

**An unenforceable `tool_choice` went unrefused when no tools came with it.**
`if tools and should_send_tools(...)` short-circuits, so `tool_choice:
"required"` with an empty `tools` array returned 200 and prose where three
separate pieces of documentation promise a 400. Evaluated unconditionally now.

### What is not proven

The MLX half. `mlx_lm.server` speaks the OpenAI chat schema, so tools are
forwarded as the field it already defines and calls are reassembled from the
fragmented `delta.tool_calls` an OpenAI client would parse — but none of it has
run against a live server, the same boundary MLX inference as a whole has always
sat behind. A build without tool support would accept the field and answer with
prose, which is precisely the silent failure this whole change exists to remove.
Point an agent capability at Ollama until that is checked; it is written into
the adapter's docstring rather than left to be discovered.

And the question the code cannot answer: whether a local model is actually good
enough to drive an agent loop. Codex's prompts are tuned for a model this
deployment does not have. The platform can now carry the conversation; whether
`qwen2.5-coder` or `glm-4.7-flash` can hold up their end of it is a measurement,
not a merge.

### A second review, this time against the running runtime

Same day, after deployment. The method differed from the morning's review in one
way that turned out to be the whole of its value: every suspicion that *could*
be tested against the live Ollama 0.32.4 was, instead of being settled by
reading. Two of the four real findings were claims the code made about Ollama's
behaviour, and both were false in ways reading could not have shown.

**The "stays replayable" fallback had no input on which it could succeed.** The
adapter sent undecodable `arguments` upstream as the raw string, on the theory
that Ollama should judge a payload we did not invent. Measured: Ollama types the
field as an object and answers 400 for *any* string — malformed, or valid JSON
in string form, identically. So the fallback was not a permissive path but a
guaranteed failure, and a worse one than refusing: that 400 came back through
`_raise_for_status` as `no_available_model`, whose documented remedy is retry,
for a failure that is permanent. A client following our own documentation would
replay the same doomed conversation forever. It is now refused before the
request is sent, as `RuntimeCapabilityError` — a 400 that says the request
itself is the problem, which is the same honesty judgement as `tool_choice:
required`, reached from the opposite direction: there refusing beat serving
something else, here refusing beats promising a retry that cannot work. MLX
keeps carrying the raw string, because its server takes a string; the capability
genuinely differs per runtime, which is what the error class is for.

**The id was minted, cited, and then dropped.** The adapter minted `call_x`
because "Ollama gives a call no id" — true when written, false on 0.32.4, which
mints its own. Minting stays (nothing Ollama publishes promises the field or its
uniqueness), but the replay path sent the assistant's calls *without* their ids
while sending the tool result's `tool_call_id` faithfully — one half of a pair
whose other half we were deleting. A build that pairs on ids would attach the
result to nothing. Measured: 0.32.4 accepts `id` on a replayed call; it is sent
now, on the argument the two `tool_name`/`tool_call_id` spellings already rest
on — a Go handler ignores a field it does not know, so sending it costs nothing
and depends on nothing.

**MLX read half of the usage object.** `completion_tokens` and not
`prompt_tokens`, so every figure downstream — the `include_usage` frame, the
non-streaming `Usage`, the quota that counts prompt tokens since 2026-08-04 —
reported 0 prompt tokens on that path. An agent's consumption is mostly prompt;
on the MLX path the quota would have measured approximately nothing.

**`functions` was the same disease, resurfacing under its old name.** The
deprecated spellings `functions`/`function_call` still fell to `extra="ignore"`
— 200, prose, a stalled agent loop, from an older client library instead of a
current one. The identical failure shape the whole 2026-08-05 change exists to
remove, one field over. Refused now, with the message naming the fields to send
instead.

Smaller, from the same pass: `tool_calls` on a non-assistant role is refused
(the adapters forwarded it on whatever role carried it); the timeout detail no
longer diagnoses every `httpx.TimeoutException` as a long prompt (a connect
timeout is a down runtime, a mid-stream stall is neither); the terminal Ollama
event is filtered against calls already forwarded, so a build that restates the
turn's calls in its done event cannot make an agent execute side effects twice;
an MLX event carrying both content and a call fragment bills one token, not
two; `stream_options` without `stream: true` is refused as OpenAI refuses it;
`top_p: 0` is legal.

The lesson is the morning's own, applied to the morning: the review that found
"a rule written when the last message was always the user turn" was itself
carrying rules written against an Ollama that no longer exists. A claim about a
runtime's behaviour ages like a claim about a colleague's schedule, and the only
test that catches it is the one that asks the runtime.

### Error precision: the id that was promised, the codes that were one code

An audit of the error system for debuggability found that the biggest hole was
not in the code table but in *correlation*, and that two mechanisms the
codebase already described did not exist.

**`DomainError`'s docstring said detail is logged "with the request id". There
was no request id.** Nothing minted one, nothing logged one, nothing returned
one — the sentence described the design, not the system, and security.md §9.2's
"logged by default: request id" was aspirational on the same point. A caller
reporting a failure had a timestamp and a path; four concurrent slots and a
queue make that ambiguous exactly when it matters. Now: middleware mints
`req_<hex>` per request (contextvar, not `request.state`, because the two
places that most need it — the SSE frame generator and the 500 handler — run
where the request object is out of reach), every response carries
`X-Request-Id`, every error envelope repeats it as `error.request_id`, the
domain-error log line includes it, and the mid-stream SSE error frame carries
it too, since a death after the first byte has no other channel left. The 500
gained the standard envelope at the same time; it had been the one non-JSON
body the API could produce, on the status where a client most needs to parse.
Detail still never leaves by default — precision comes from the bridge, not
from leaking.

**`debug_logging_until` had existed since the first migration, on two tables,
in the admin schema, and was consumed by nothing.** Twelve days of a switch
wired to no lamp — settable state that promised behaviour nothing implemented,
which is the same shape as a documented absence, in the database. It is now
the one deliberate exception to "detail never leaves": while the window is
open on a credential, error responses to it carry `error.detail`. Set from the
API keys page (an hour per press, capped at a day in the use case, so
"time-boxed" is a property of the mechanism rather than a hope), audited as
`api_key.debug_window_set` because it loosens an information control, granted
at the moment the credential resolves so that CIDR, rate-limit and quota
refusals — the runbook's own troubleshooting cases — can explain themselves to
the caller being debugged. §9.2's original intent for the field, full
prompt/completion logging, remains unimplemented and is now recorded there as
such.

**`no_available_model` was six causes wearing one name, spanning three
remedies.** A missing routing policy, a downed runtime process, a prompt that
outran the read timeout, and a mid-generation stall all told the caller "retry
with backoff" — for some of them retrying was pointless, and for one of them
backoff is precisely wrong. Split by remedy, not by cause, which is the rule
the code table already followed everywhere else: `runtime_timeout` (retry
immediately, once — the prompt now sits in the prefix cache, a measured
property), `stream_interrupted` (you may hold a partial answer; whether to
retry is your idempotence judgement), and `no_available_model` keeps the
routing-layer meaning whose remedy really is backoff-then-administrator. Both
new errors subclass the old one, so routing's candidate loop and every
existing `except` keep working, and the status stays 503 throughout — a split
of codes, not of statuses.

**The queue was unbounded and invisible.** `slot()` waited on the semaphore
forever, and a slot can legitimately be held for 25 minutes, so a caller
arriving fourth-plus-one waited in silence — zero bytes, no code — until their
own client timeout fired, indistinguishable from a hung deployment.
`QUEUE_WAIT_SECONDS=120` bounds the wait; elapsing it is `503 overloaded` with
`Retry-After`, the code that finally makes "busy" distinguishable from
"broken". Zero restores the old behaviour, documented rather than possible by
accident.

The `/api-docs` page gained the sections an integrator previously learned by
surprise, of which the sharpest was **client timeout sizing**: the first token
of a context-ceiling request can take ~10 minutes of legitimate silence, and
the OpenAI SDK's default timeout is 600 seconds — so a correctly-configured
agent on a long conversation was killed by its own client, in a way
indistinguishable from platform failure, and no error table row could ever
have said so. Also added: the `extra_body` route to `think`/`use_knowledge`
(the SDKs refuse unknown named arguments; every example was curl), the full
SSE frame sequence as one annotated listing, the `/v1/models` response shape,
the 4-characters-per-token budgeting rule on the 413 row, the absence of
`x-ratelimit-*` headers, and the new codes with their remedies.

---

## 2026-08-04

### Records now have an expiry date, and an administrator can bring it forward

The growth audit ended with a decision to make rather than a fix to apply, and
the administrator made it: **360 days for everything, settable in the UI, with
a manual purge that can be aimed at one dataset.** The three questions it turned
on were answered as well — audit entries are deletable, `retention:write` is
admin-only, and the sweep runs daily.

**Deleting audit entries is a choice with a cost, made in front of the cost.**
The alternative offered was to keep the purge but write an undeletable record of
each one; what was chosen is the fully open version, where the entry recording a
purge is itself removable by a later purge. So the platform administrator can
erase their own trail. That is now what the platform does, and it is written
down in `security.md` §12.1 rather than mitigated in code, because a control
that half-implements a rejected design is worse than the design that was
chosen.

`retention:write` is admin-only and joins `tenant:write` in `ADMIN_ONLY_SCOPES`
for a related reason: a `tenant_admin` who could purge could erase the record of
what they did inside the tenant they administer, and the audit log's whole value
is that it is written by a wider authority than the one being recorded.

**Two tables, and the enum is the allowlist.** `audit_log` and `usage_records`
are the only things that grow without a person deciding, and the dataset a
request names is a `RetentionDataset`, not a table name — these values reach a
`DELETE`, so what is safe to delete from is decided in the domain rather than at
the edge. `/admin/retention/users/purge` is a 422, and there is a test that says
so.

**The count is the feature.** "Keep 90 days" is an abstraction until something
says it removes 4,000 entries, and that sentence is the difference between
saving thoughtfully and saving. So the preview runs against the number in the
field rather than the number in the database, before the save rather than after
it, and the confirm dialog repeats the count rather than the window — it is what
the reader is agreeing to. The preview is a separate endpoint rather than a
dry-run flag, because a dry run sharing a code path with the real thing is one
edit away from deleting during a preview.

Three smaller decisions worth their lines. The floor is 30 days and a shorter
window is **refused rather than clamped**, since storing a number nobody typed
and reporting success puts the gap between choice and effect where nobody
re-reads. A purge may name a window narrower than the policy without changing
it, which is the "clear this one thing" case. And a dataset with no stored row
reports the default rather than being omitted, so a fresh deployment shows the
number that governs rather than an empty screen implying nothing expires.

The scheduled half sleeps before its first sweep, like the node heartbeat beside
it — without that, every test that builds the admin app would purge whatever
fixture data it had just written. Both admin entrances run it, which is safe
because `DELETE ... WHERE at < cutoff` run twice deletes nothing the second time.

Two things the tests caught while being written. The new domain error had no
entry in `STATUS_MAP`, so a window of 7 days answered **500** — an input error
reported as a server fault, which is exactly the class of thing that gets
investigated as an outage. And the migration was chained to `f7a9d24c8b16`,
which stopped being the head this morning when `prompt_tokens` landed; alembic
refused with "multiple head revisions" rather than picking one, which is the
right failure. 686 backend tests and 218 frontend, and the live database is at
`a1b2c3d4e5f6` with both datasets reporting the 360-day default.

### The entrance is green on both new names

`verify-public-entrance.sh`: **9 passed, 0 failed, 0 skipped**, the first clean
run under `llm.rcsl.online` and `llmapi.rcsl.online`. Both present valid
certificates, `llmapi/healthz` is answered by the gateway and `llmapi/` returns
the application's own 404 rather than the proxy's, the four header directives
are in the right place on both hosts, and a forged `Tailscale-User-Login` is
refused. The administrator migrated rather than duplicated: the two `nexus`
names are gone.

The rename is therefore complete end to end — configuration, documentation,
images, and the proxy — and the certificate question it was made for came out
as predicted, with the existing `*.rcsl.online` wildcard covering both
single-label names.

### What grows without a bound, and the one thing that already had

Asked in the abstract — "is there anything that grows forever, like log
retention?" — and worth answering with measurements from the running machine
rather than from the shape of the code. Most of it is in better condition than
the question implies, and the one real leak was not in the platform at all.

**Bounded already.** Redis holds two keys and both carry a TTL, so sessions,
rate-limit counters, job progress and cache entries all expire by construction
— there is no key without one. Prometheus runs `--storage.tsdb.retention.time=30d`
and sits at 70 MB for nine days of three targets, so its steady state is a few
hundred megabytes. `invitations` and `recovery_codes` are bounded by the number
of accounts. The knowledge base and its Qdrant collections are bounded by what
a curator uploads, which is a person making a decision each time.

**Unbounded but slow, and needing a stated policy rather than a fix.**
`audit_log` (112 rows) and `usage_records` (65 rows) are append-only with
nothing that prunes them, and nothing should prune them casually: an audit log
whose old entries vanish is worth less than one that grows, and usage records
are the accounting the quotas are measured against. At 160 kB and 120 kB after
nine days, neither is a capacity problem this year. What is missing is the
**decision** — how long an entry is kept and who may delete one — recorded
before the first person asks the platform to forget something.

**Unbounded and worth fixing.** No service declares a `logging:` block and the
daemon sets no default, so every container writes a `json-file` log with **no
rotation**. Today that is a few hundred kilobytes and Grafana is the largest at
530 kB; under real gateway traffic it is the first thing that would fill a disk,
and it fills it silently. A `max-size`/`max-file` pair per service is the whole
fix.

**And the one that had already grown: 1.7 GB of orphaned Postgres data.**
Sixteen dangling anonymous volumes, about 120 MB each, dated from 2026-07-27
onwards — one per integration-test run, including two from this morning. The
`postgres` image declares `/var/lib/postgresql/data` as a `VOLUME`, so the
recipe in the README creates an anonymous volume every time, and `--rm` does not
reliably remove it. **Confirmed by experiment rather than inferred**: dangling
count 16 before running the documented command and removing the container, 17
after.

The README recipe now mounts that path as `--tmpfs` with `uid=70`, the alpine
image's `postgres` user, without which `initdb` cannot write to it. Measured the
same way: 16 before, 16 after. Nothing to leak, and the test database is in RAM,
which is the smaller benefit. `-fv` is on the teardown line for anyone who drops
the tmpfs.

The general lesson is worth more than the gigabyte: **a leak in a documented
command is a leak in everyone's habits.** This one was in the file every
contributor is told to start from, it fired on every integration run for nine
days, and nothing in the platform's own logs, metrics or dashboards would ever
have mentioned it.

### One symptom, two causes, and neither was the width someone had set

Reported as one bug — text running past the right edge, in the chat capability
picker and in the Logs `Detail` column. They share nothing but the symptom.

**The picker.** `embedding` and `rerank` are listed and disabled on purpose:
the chat screen shows what a key can be issued for, and routing either of them
would send the request to a model that does not generate text. Two things
together made that unreadable. The popup was pinned to `w-(--anchor-width)` —
the trigger's width, and the trigger is `w-36` — with `overflow-x-hidden`, and
the explanation was appended to the option's own label, inheriting the item's
`whitespace-nowrap`. So it was cut off around `embedding (not a conv`, with no
ellipsis and no scrollbar to reveal the rest: **the disabled state was legible
only to someone who already knew what it said.**

The popup now sizes to its content, floored at the trigger width and capped at
`--available-width`, and the reason is its own muted element. **A trigger is
sized for the selected value; the list is not**, and that is the assumption the
pinned width encoded. Fixed in `ui/select.tsx`, so it is every picker in the
platform rather than this one.

**The Logs column was not a width problem at all.** Both cells carried
`max-w-[16rem] truncate` directly on the `<td>`, and under the automatic table
layout every table here uses, `max-width` on a cell is advisory: the column is
sized from its content first. The cap was ignored, `truncate` had nothing to
truncate against, and a long value widened the whole table until it ran past
the edge — reachable only through the wrapper's horizontal scrollbar, and never
showing the ellipsis that would have said there was more. `detail` is every key
and value of an audit entry joined into one line, so it is routinely longer
than the viewport, which is why that column showed it first. Moving the cap to
a block inside the cell is the whole fix. The pattern appears nowhere else.

Neither of these can be proved by a test here: jsdom does no layout, so the
causal chain above is read from the CSS rather than watched in a browser. What
a test could pin is the structural half — that the cap lives on an inner block
and not on the cell — which is exactly what a future edit would undo.

### The last key was revoked, and the list it left behind needed a filter

`qwen7b` is revoked. It was the only unrevoked key on the platform and the
reason given for keeping the old `api.nexus.rcsl.online` name alive as a 301 —
a reason that does not survive looking it up. **The holder was the
administrator themselves**, not an external caller, and its whole history was
two requests and 33 tokens on 2026-07-26, the day it was issued. The 56
requests and 101k tokens in the same period carry a null `api_key_id`: that is
admin chat, which uses no key at all. Nothing depended on it.

Revoked through the admin API rather than with an `UPDATE`, so the audit log
carries `api_key.revoked` against the account that asked. Doing it in SQL would
have produced the same row in `api_keys` and no record that anyone did it,
which is the half of §12 that took a sweep to notice was missing the first
time. Two things the attempt ran into, both of them controls working: the
tailnet entrance still requires the CSRF double-submit on a POST, and the
`__Host-` cookie it issues is `Secure`, so the token has to be carried
deliberately rather than picked up by a cookie jar over loopback http.

**The screen this left behind is what the filter is for.** Seven keys, all
revoked — six single-use verification keys from the morning sweep and this one
— so the API keys table was entirely history, and the row anybody would come
back for is one that does not exist yet. Revoked keys are now hidden by
default, with the count in the toggle: `Show 7 revoked` says both that they
exist and where they went, where a bare "Show revoked" would leave someone
hunting for a key they know they created. The toggle is absent when there is
nothing to hide.

The part worth keeping is the empty state. Filtering every row out leaves the
table looking exactly like a fresh deployment, and the stock message would then
tell someone with seven keys to go and issue one. It says "No active keys" and
names the way back instead. **A default that hides needs two things, not one:
a way to reverse it, and a signal that it is on** — the second is the one that
gets left out, and it is the one that turns a filter into a disappearance.

Expired keys are deliberately not covered. They become inert without anyone
acting, and lapsing is often exactly what someone came to look for; one control
meaning both would answer neither question.

**A review then found the change committing the exact fault it was written to
prevent.** All of the reasoning above was applied to the unfiltered list, and
`DataTable` filters again afterwards with its search box. So typing the name of
a hidden key — the most natural way to look for a key you know you created —
emptied the table and answered with the caller's `emptyDescription`: *"No API
keys. Issue a key to let an application reach the gateway."* Told to someone
holding seven of them. The follow-on was worse: with a search active and the
message advising "Show 7 revoked", clicking it made the screen **less**
informative, because the message reverted to the generic one.

The fix belongs one level down rather than in this screen. **An empty result
from a search is the table's own story, and no caller's `emptyDescription` is
ever true about it** — every one in this codebase describes an empty dataset,
which is a false statement about a table whose rows a query merely did not
match. `DataTable` now says "No matches" with the query and a Clear search
button, and falls through to the caller's message only when nothing is typed.
That fixes every table at once; this screen was just the one where the wrong
message was insulting enough to notice.

Three smaller ones from the same review, all real: the toggle set `aria-pressed`
*and* swapped its label, so a screen reader announced the state twice in
opposite directions (`aria-pressed` dropped — the label is the mechanism that
also works for someone who cannot tell a pressed variant from an unpressed
one); the permission comment on the Issue-key button had been left stranded
above the new fragment, attached to the toggle, which has no permission gate at
all; and both the comment and this entry worked their example from `Show 6
revoked` while describing seven keys all revoked, which is what the label would
actually say. Seven tests now, including the search path that started it.

### Redeployed, and the build refused for a file it had never been given

Everything from today went out at once — the rename, the dependency bumps, own
usage, the nav tests. `docker compose build` failed on the first attempt, and
the failure was the useful part.

**`pnpm-workspace.yaml` was never copied into the frontend image.** The `deps`
stage takes `package.json` and `pnpm-lock.yaml` and nothing else, so the file
that has held this project's pnpm settings since 2026-07-26 — moved there
precisely because pnpm 10 stopped reading them from `package.json` — has never
been present at the only point where pnpm reads them. Moving the `postcss`
override into it turned that from silent into fatal: the lockfile records an
`overrides:` block, the config declaring it was absent, and `--frozen-lockfile`
refused rather than resolving something different from what was locked.

Worth being exact about what was broken before today, because it is less than it
first looks. The missing file meant the **build-script allowlist** was absent
from the image, and pnpm's default with no allowlist is to run **no** dependency
build scripts. So the effect was the safe direction of the failure — nothing
unapproved ran — and the one entry the allowlist permits, `esbuild`, matters
only to the test runner, which does not run in the image. Nothing was
mis-built. What was wrong was that the intent was stated in the repository and
enforced nowhere in the artefact, which is the same shape of defect as the
original one that put the file there.

The lesson generalises past this repository: **a config file only counts where
the tool runs, and a Docker stage that copies dependency manifests by name will
silently omit the one added later.** `--frozen-lockfile` is what turned it into
an error, by comparing the lockfile against a configuration that was not there.

The deploy itself: eleven services up, `migrate` `Exited (0)`, gateway and
parser healthy, all three applications answering `/healthz` and `/readyz` with
`database`, `cache` and `runtime` true, no traceback in the logs. The containers
carry the new configuration (`PROXY_HOSTNAME=llmapi.rcsl.online`,
`ADMIN_BASE_URL=https://llm.rcsl.online`) and the new code: `/admin/usage/me`
answers 401 rather than 404, which separates "route exists, no identity" from
"route absent" — a nonexistent sibling path returns 404 from the same entrance,
which is what makes that distinction mean anything. The shipped frontend bundle
contains `usage:read_own`, so the nav change is in the image rather than only in
the tree.

**Half the entrance had already moved under us.** `verify-public-entrance.sh`
reports **6 passed, 1 failed, 2 skipped**: `llm.rcsl.online` is live and
`ai.nexus.rcsl.online` is gone, so the administrator migrated the management
host rather than adding a second one. `llmapi.rcsl.online` is not configured yet
and `api.nexus.rcsl.online` still answers, so the data plane is still on the old
name — which is the safe order, since it is the one with an external caller
holding a base URL.

The part that matters most in that run: **checks 4 and 5 pass on the new host.**
The four `proxy_set_header` directives are in the right place first time — a
wrong `X-Nexus-Proxy` and the real one both return 401, and a forged
`X-Forwarded-For` and a forged `Tailscale-User-Login` are both discarded. That
trap cost four days across two placements last week, and rebuilding under a new
hostname was exactly the occasion to repeat it.

### A scope nobody could spend, and the nav that had no test

Two things, found by asking whether the sidebar varied by role. It already did —
that landed this morning — so the work became verifying it rather than building
it, and the verification is what turned up both.

**Every nav entry's `requires` matches the scope its screen's own first request
demands.** Checked one by one against the `authz.require(...)` in each use case:
Dashboard and Usage against `read_dashboard` and `read_usage_analytics`, Logs
against `read_audit_log`, and so on. The three entries that deliberately declare
nothing — API keys, API, Chat — are correct too, because every role holds
`api_key:read_own` and `chat:use`. So the invariant the nav table claims for
itself holds with no exceptions: **a hidden link and a 403 mean the same
thing.**

**`usage:read_own` was granted to every human role and required by nothing.** It
has been in `_BASE_SCOPES` since the roles existed, described there as part of
what having an account is worth — and no endpoint asked for it, so a member
could not see their own figures anywhere in the UI. `/admin/usage/me` now
answers it, and the Usage screen serves whichever question the reader is
entitled to ask.

The attribution is by **actor**, not by key, which is worth stating because it
is what makes the answer useful: the gateway resolves an API key to its owner
(`api_key_auth.py` builds the actor with `id=key.owner_id`), so one account's
usage is every row its keys produced — current, rotated, revoked — plus its
admin-chat traffic, with no join and nothing to remember. The filter is applied
*inside* the tenant scope rather than instead of it, and the integration test
asserts exactly that by planting the same actor id under a second tenant.

Two separate paths rather than one endpoint that quietly returns less to a
narrower caller. A chart that silently changes what it counts based on who is
looking is one nobody can compare with anyone else's, and the scope it checks
would stop matching what it returns.

**The nav had no test, and neither did `can`.** `app-shell.tsx` carried the
filtering, the shared definition behind both the sidebar and the mobile panel,
and the guard that redirects an out-of-scope URL — none of it covered, in a file
that changed shape twice in one day (`adminOnly` to per-scope this morning,
`usage:read_all` to `usage:read_own` this afternoon). Neither change is visible
to a type checker. Fifteen tests now cover it, driven by **scope sets rather
than role names**: the authoritative role table is the backend's, and asserting
a frontend copy of it would only prove the copy matches itself.

The one that took a correction while being written: an `auditor` sees **every**
link, identical to an admin. That looks like a bug and is the role working — it
holds a read scope for everything, and what differs is inside each screen, where
the write controls are gated separately. The test now pins the count so a future
entry an auditor should not see fails here.

`can`'s own contract moved to `lib/session.test.tsx`, where it belongs: an
**absent** scope list falls back to the old `role === 'admin'` boolean, an
**empty** one grants nothing even to an admin, and neither grants anything while
the query is still pending. The absent case is not hypothetical in this
deployment — the last deploy recreated `admin-public` alone, so a frontend newer
than its backend is an ordering that really happens, and answering "holds
nothing" during it would empty the nav for everyone and explain nothing.

Rendering the shell in a test also surfaced a Base UI warning nobody had seen:
the Account button and the not-found link render as anchors while claiming
native button semantics. Both now say `nativeButton={false}`. **A component that
had never been mounted in a test had never printed its warnings either.**

### Both runtime advisories are closed, and one of them was called unfixable twice

The two that reach the deployed images are gone. `pip-audit` against the
production resolution reports **no known vulnerabilities**, and `pnpm audit`
lists no `sharp` and no `postcss`. What is left is ten advisories, every one of
them development scope — `undici`, `ip-address`, `fast-uri`, `brace-expansion`,
`@hono/node-server`, mostly arriving through `shadcn` and the MCP SDK — and
none of them is in anything shipped.

**`cryptography` 49.0.0 → 50.0.0** (GHSA, PKCS#7 `EnvelopedData` decryption
exposes a Bleichenbacher oracle through distinguishable errors and timing). It
is a **direct** dependency, declared `>=44.0`, so the floor moved with it rather
than being pinned in the lockfile alone. The vulnerable path is one this
platform never calls — nothing here decrypts PKCS#7 — so the real exposure was
low and the bump was one line either way. 577 backend tests and strict mypy over
159 files are unaffected.

**`sharp` 0.34.5 → 0.35.3**, overridden in `pnpm-workspace.yaml`. This is the
advisory two earlier entries called upstream and unfixable from here, which was
true when they were written: sharp inherits four libvips CVEs and `next` pins
its minor, so nothing could move until sharp 0.35.0 shipped with libvips 8.18.3.
It has, so it did. The override now resolves 0.35.3 and the loaded binary
reports `libvips 8.18.3`.

Two things this turned up that are worth keeping. **Verify the resolution from
where the consumer resolves it, not from the project root** — `require('sharp')`
fails there under pnpm's layout, because sharp is `next`'s optional dependency
and is never hoisted; resolving with `paths: [next's directory]` is what proves
the thing Next will actually load. And **"upstream and unfixable" is a statement
with a date on it**: it was recorded twice here, correctly both times, and the
only work needed to falsify it was to look again once a release existed.
`next build` still produces all 21 pages, 193 frontend tests and lint pass, and
`pnpm install --frozen-lockfile` is consistent, which is the check CI runs.

### The public hostnames became single-label, which is a certificate decision

`ai.nexus.rcsl.online` and `api.nexus.rcsl.online` are now `llm.rcsl.online` and
`llmapi.rcsl.online`. The change is on this end only — configuration and
documentation — and the proxy administrator has been asked for the server
blocks; **nothing has been redeployed and neither new name answers yet**, so the
entrance is currently green on names that are being retired.

The renaming itself cost two `.env` values, because **a hostname is not a trust
boundary in this platform**. `PROXY_HOSTNAME` only feeds `gateway_base_url`, the
origin shown beside a newly issued key and rendered into `/api-docs`, and
`ADMIN_BASE_URL` only builds invitation and reset links. There is no
`TrustedHostMiddleware`, no CORS origin list, and no cookie `domain`; the
perimeter is the `X-Nexus-Proxy` secret plus the client address, and the
frontend is entirely same-origin through the Next.js rewrite. Everything else
touched was a default, a script's default, a comment, or prose.

What the new names buy is not brevity. **A TLS wildcard matches exactly one
label while a DNS wildcard matches any depth**, which is why the two-label names
resolved for weeks before they could be served and why each needed its own
certificate (`ROADMAP.md`, external coordination). `llm` and `llmapi` sit inside
`*.rcsl.online` on both sides, so the certificate item may reduce to pointing
the server blocks at a certificate that already exists. The same property closes
half of `security.md` §15.4: the old names resolved only by multi-label
synthesis and would both have vanished the moment anyone added a `nexus` node to
a zone this project does not control. `llmapi` is one word rather than
`api.llm.rcsl.online` for that reason alone.

Two consequences to expect on cutover rather than discover: session cookies are
host-only, so every signed-in operator is signed out and enrols again from the
new origin, and any invitation or reset link already issued points at the old
host and must be reissued. The old blocks should serve a 301 rather than be
deleted, since the one active key's holder has the old base URL.

### A review found three serious defects in the day's work, two of them mine

Run against the seven commits. Nine findings, all real; the three that mattered
were verified here before being fixed, because a review is a claim until it is
reproduced.

**The prompt-token quota was bypassable, by the change that added it.**
`max_tokens: 1` in front of a context-filling prompt cost one token of quota.
The ceiling check ran first and `break` left the runtime's terminal event
unread — the only place `prompt_eval_count` appears — so the figure was zero on
exactly the requests designed to abuse it. Reproduced with a probe before
touching anything: `max_tokens=1 -> billed 1, prompt_tokens 0`. **The comment I
wrote asserted the opposite in as many words** ("Truncation at the ceiling is
not affected: Ollama's own done chunk arrives on the same token"), which was
true about when the event *arrives* and wrong about whether anything reads it.
A confident comment on an unverified claim is worse than none, because it is
what the next reader checks instead of the code.

Now the loop reads past the ceiling without forwarding, which costs nothing —
the runtime is told `num_predict = ceiling`, so its terminal event is the next
one — bounded by `_TERMINAL_EVENT_DRAIN_LIMIT` for a runtime that ignores that.
Two things fell out of doing it: drained content is *not* billed, since it was
withheld from the caller; and the terminal frame the client sees now keys on
whether one was **forwarded** rather than whether upstream sent one, or a
truncated stream would have ended with no terminal frame at all.

**Adding `tenant_admin` opened a path to platform `admin`.** `USER_WRITE`
answers "may this caller create accounts" and never answered "with which role",
which was invisible while `admin` was the only holder and nothing sat above it.
A `tenant_admin` could invite an account with `role: admin`, take the
single-use onboarding link out of the same response body, and hold every scope
— including the `TENANT_WRITE` the role is explicitly denied, and every
platform-global scope the tenant boundary does not cover. The new §5.2 table
said "deliberately cannot create a tenant" while the role could create somebody
who could.

Closed with one rule in `domain/services/grantable_roles.py`: **you may grant a
role only if you already hold everything it confers.** It needs no table, and
it keeps being true for roles added later by people who never read that file.
`tenant_admin` can still staff its own tenant — `curator`, `auditor`, `user`,
its own role — and cannot reach `operator` or `admin`.

**The `auth_mode` fix from this morning was half a fix.** `install_error_handlers`
was corrected to say `local`; `GET /admin/me` still answered
`settings.auth_mode`, and the UI prefers that field over the 401 hint. So a
*signed-in* user on the public entrance was still told `tailnet`, which hides
the Account button, Sign out, the password form and TOTP re-enrolment — on the
one entrance that has any of them. It now answers `actor.source`, set by
whichever resolver authenticated the request, so it cannot disagree with how
the caller actually arrived. This morning's PROGRESS entry described the 401
half in detail and did not mention this one.

Six smaller findings, all fixed: `can()` falling back to the old boolean when a
backend does not send scopes at all, because frontend and backend are separate
images and this deploy recreated `admin-public` alone — "no scopes reported"
would have emptied the nav for everyone including `admin`; the "Issue key"
button and `canManageKey` still assuming everyone may write their own keys,
which stopped being true when `auditor` arrived; a 422 still naming two of six
roles; `ROLE_SCOPES` exported as the live dict rather than a `MappingProxyType`,
in a module whose first line argues nothing may grant itself a scope; a
heartbeat comment calling a 0 → N write cost a "halving"; and **a test of mine
that asserted on a labelled scope while claiming to cover the unlabelled
fallback** — it could not have failed, which reads as coverage and is worse
than an absence.

### The account screen answers "why can I not see that screen"

The permissions list is on `/account` too, from `me.scopes` — the scopes the
request was actually authorized with, rather than a description of the role's
name. Shown to everyone rather than only to administrators, because the person
who asks why the Logs link is missing is by definition the one without
`logs:read`, and until now the answer existed only in `role_authorization.py`.

`ScopeList` is shared with the role picker. One component, because the rule
that matters is identical in both and easy to get wrong once: a scope with no
plain-language name is rendered as its identifier rather than skipped.
Understating what is granted is the one direction a permissions display must
never be wrong in — a reader who sees `logs:read` learns something, a reader
shown nothing concludes there is nothing there.

The empty case is two cases and they are kept apart. An account holding no
scopes and a server that did not report them are the same empty list and mean
opposite things, so the screen says which one it is looking at. That branch is
not decoration: `me.scopes` is optional precisely so a frontend running against
an older backend degrades instead of crashing, which is exactly when the
distinction is load-bearing.

### Four more roles, and a UI that says what they mean

Two roles for a platform with a knowledge base, a fleet, tenants and an audit
log. The gap between them was the whole of the problem: `user` held four scopes
and `admin` held all nineteen, so anybody who needed to load a model also got
the power to invite people and read every log line.

**The expensive part turned out to be already built.** Authorization is
scope-based — `_BY_ROLE` is a hardcoded table and use cases declare a scope —
so a role is an enum member and a `frozenset`. Nothing branches on a role name
in the backend, and the hardcoding that exists so no database row can grant
itself a scope is also what makes adding one safe. No migration: `users.role`
is a `String(16)` with no enum constraint, and the four new names fit.

| Role | Has | Deliberately lacks |
|---|---|---|
| `tenant_admin` | its tenant's people, keys, knowledge; reads the fleet | creating tenants; any fleet write |
| `operator` | models, nodes, routing, logs, all usage | inviting, promoting, issuing keys for others |
| `curator` | the knowledge base | everything else |
| `auditor` | every read there is | every write, including its own API keys |

**`tenant_admin` is not a second dimension, and checking that was the part
worth doing carefully.** The tenant boundary is already structural: `di.py`
builds `ManageUsers` with a *tenant-scoped* repository, so `user:write`
reaches only the holder's own tenant whoever holds it. The only powers that
cross tenants are the platform-global ones — tenants, nodes, models, routing —
so the role is expressible by omitting their write scopes, and one dimension
still does the job. Two dimensions would have been a rewrite of every
repository construction for no additional confinement.

`operator` is the split that motivated the rest: running a platform and
deciding who may reach it are different jobs, and an operator who can issue a
key can hand themselves everything else in the table. `auditor` drops
`API_KEY_WRITE_OWN`, which every other human role gets from the base set —
an auditor who can mint a key can act through the gateway, and then their visit
is no longer only a read. `curator` exists because §7.3 treats knowledge
documents as a prompt-injection surface: whoever writes them shapes what the
models answer, which is authority worth granting on purpose.

**The rot this invites is now a failing test rather than a review note.**
`_ADMIN_SCOPES` is `frozenset(Scope)`, so every scope added later reaches
`admin` automatically and no new role — each feature quietly narrowing the
roles beneath it. `test_role_scopes.py` requires every scope to reach some
non-`admin` role or to be named in `ADMIN_ONLY_SCOPES` with its reason. Only
`tenant:write` is named, and the reason is that a tenant is the boundary the
other roles are confined by. Same shape as `EXPECTED_SERVICES` listing nine of
eleven services this morning: a list nothing compares against is a list that
drifts.

**The UI asked the wrong question in forty-five places.** `isAdmin` is a
boolean, and it was the gate on every screen and every row action. It would
have hidden Models and Nodes from the `operator` whose entire job they are, and
shown an Invite button to an `auditor` the server refuses. `GET /admin/me` now
returns the caller's resolved scopes and the frontend asks `can('model:write')`
— the same question the server will answer, so a hidden control and a 403 mean
the same thing. Still an affordance, not a control.

**And the picker now explains itself**, which is what was actually asked for.
It offered six words, which is enough to choose between `admin` and `user` and
nowhere near enough to choose between `operator` and `tenant_admin` — the two
that differ in exactly the way that matters, one running the hardware and
granting nobody access, the other the reverse. Each role now shows a sentence
saying what it is for and what it deliberately cannot do, and beneath it the
real permission list from `GET /admin/roles`, generated from the same table
`RoleAuthorization` enforces. Two layers because they fail differently: if the
sentence drifts it reads oddly, but the list cannot claim a permission the
platform does not grant. A scope with no plain-language name is shown by its
identifier rather than omitted — understating what a role grants is the one
direction this screen must not be wrong in.

#### A documented decision was reversed, on purpose

ROADMAP's `prompt_tokens` item said to count it *without* changing what the
quota meters, "so that a documented figure and a billed one do not silently
become the same number". This morning's change did exactly that. It was
deliberate and requested, and the argument is that a quota charging for output
alone is not a limit on the work asked for — a caller could fill the context
window every request and spend none of it. So the two figures are now the same
number, and the obligation transfers: `/api-docs` said in as many words that
`prompt_tokens` is never reported and the quota meters produced tokens only,
which stopped being true at 11:00 and is corrected. **The reversal is recorded
rather than quietly performed**, because a decision overturned without a note
is indistinguishable from one nobody knew about.

### The Users screen could not edit a user, and both reports were the same gap

Reported as two problems — a display name that cannot be changed, and an
administrator who cannot promote anyone — and they are one missing dialog.

`PATCH /admin/users/{id}` works, `updateUser` wraps it, `updateUserSchema`
validates it and `useUpdateUser` wraps that. **The hook had no caller anywhere
in the application.** So a display name was whatever it was given at invitation
and could never be corrected, and nobody could be promoted — which is the one
operation that lets a second administrator exist, on an instance that has
exactly one account.

The backend was never at fault and was checked rather than assumed: `PATCH` of
a display name returns 200, and changing *your own* role returns 403, which is
the guard `ManageUsers.update` documents. The new dialog mirrors that refusal
instead of discovering it — the role control is disabled for yourself, with the
reason attached, rather than offering an edit the server will reject.

It is mounted only while a row is selected, so the form's defaults and
`useUpdateUser(id)` both belong to that row. Keeping one instance and swapping
the prop would leave both pointing at whoever was edited first — the same
reconciliation trap that ate every keystroke in the login form earlier today,
and the reason it is worth stating twice.

Four tests, in a directory that had none until this morning.

### The four findings from the sweep, all addressed

**Prompt tokens are counted now.** `prompt_eval_count` was in every Ollama
response and read by nothing. It is carried on the terminal chunk — once, for
the whole request, because summing it per chunk would multiply the prompt by
the length of the stream — recorded in a new `usage_records.prompt_tokens`
column, and summed alongside `tokens` by the quota and by both usage
aggregates, so the dashboard and the charge agree. The envelope now reports
`prompt_tokens: 10, completion_tokens: 102, total_tokens: 112` where it
reported zero input for every request before.

A second column rather than a wider `tokens`, so rows written before today keep
meaning what they said instead of being reinterpreted as totals they never
were. One honest gap remains and is commented where it matters: a client that
disconnects mid-answer records zero prompt tokens, because the terminal chunk
is the only place the figure appears. Closing that needs a count taken before
generation, which no runtime port offers.

**`observed_at` means last observed.** An unchanged observation is restamped
instead of skipped, so the field answers the question its name asks. Verified
by sampling: four stamps in eighty seconds, exactly thirty seconds apart.
Still not *counted* as a change — the sweep's return value answers "what
moved", and a transition buried under thirty restamps a minute is one nobody
sees. A model that cannot be observed at all is still left untouched, because
`set_observed` nulls the timestamp along with the state and rewriting an
already-null row buys no freshness.

**One heartbeat, not two.** `admin_lifespan` takes `run_node_heartbeat`, and
the public entrance passes `False`. The tailnet entrance owns the sweep: it is
the internal one, and a background database writer in the process that faces
the internet buys nothing. The thirty-second spacing above is the evidence —
two sweepers would have averaged fifteen.

That change is also what made the restamping affordable, which is why the test
that asserted the old behaviour could be rewritten rather than argued with: its
stated reason was "both admin entrances run this sweep", and now they do not.

**The health script watches everything again.** `EXPECTED_SERVICES` was missing
`parser` and `qdrant`; all eleven long-lived compose services are checked
against it now, verified by comparing the list to `docker compose config
--services`.

### A sweep of the whole platform, now that there is a way in to sweep it with

Everything that can be exercised from this machine was, because until this
morning most of it could not be reached and "it was fine last week" had stopped
meaning anything. Nothing is broken. Four things are worth acting on and none of
them is a failure, which is why they are written down rather than fixed on the
spot.

What passed: eleven services running with **zero restarts** and every healthcheck
green, `migrate` correctly `Exited (0)`; all six published bindings held by the
kernel; four launchd daemons installed; every health and readiness endpoint 200
with `database`, `cache` and `runtime` all true on both the admin and gateway
apps; Prometheus scraping three targets up and `/metrics` served under its
bearer token; Alembic at `f7a9d24c8b16` with `current == heads`; Postgres, Redis
and Qdrant reachable, Ollama holding three models; **633 backend tests** (547
unit, 86 integration against a throwaway database) and **180 frontend tests**,
with `tsc --noEmit` and eslint clean; fourteen admin API surfaces answering; and
no traceback anywhere in 24 hours of logs — every line that greps as an error is
an expected refusal logged at WARNING.

**Inference works end to end through the public entrance**, which is the first
time that has been true. `POST https://api.nexus.rcsl.online/v1/chat/completions`
returns `OK` with `finish_reason: stop`, the streaming path returns 99 SSE frames
reassembling to the same answer and terminating with `[DONE]`, an invalid key is
refused 401, and the gateway refuses a request that did not come through the
proxy exactly as the admin entrance does. A first attempt looked like a defect —
empty `content` — and was not: `max_tokens: 20` truncates `glm47-flash` while it
is still reasoning, and `content` is legitimately empty until the thinking ends.
Worth remembering before reporting the next one: **a reasoning model on a short
budget produces exactly what a broken response mapper produces.**

Four temporary API keys were issued during this and all four are revoked; the
one active key is the pre-existing `qwen7b`.

#### Four things to decide about

**Prompt tokens are not counted, anywhere.** `RouteChatRequest` records
`tokens=produced` and the response carries `Usage(completion_tokens=tokens,
total_tokens=tokens)`, so `prompt_tokens` is the schema default of `0`. Ollama
reported 34 prompt tokens for the same call. Two consequences: an OpenAI client
computing cost from the envelope is given a wrong number, and
`quota_tokens_per_day` does not charge for input at all, so a caller can send
arbitrarily large prompts free. On unified memory, prompt evaluation is real
work.

**`observed_at` means "last changed", not "last observed".** `observe_models`
skips the write when the observation is unchanged, so the model rows have read
`2026-07-30` for five days while the heartbeat has been sweeping every 30
seconds. That is correct behaviour and an unreadable field: a model steadily
observed for five days and a heartbeat that died five days ago are the same row.
It is the ambiguity `check-platform-health.sh` argues against in its own header.

**That health script cannot see two of the services it is meant to watch.**
`EXPECTED_SERVICES` lists nine and omits `parser` and `qdrant`, both long-lived.
If either disappeared the sweep would report success — the enumeration error the
script's own comments warn about, in the script that warns about it.

**Both admin applications run their own heartbeat.** `admin_lifespan` is shared,
so `admin-public` and `admin-tailnet` each sweep the same nodes and models every
30 seconds against the same rows. Harmless while writes are change-only, and not
obviously intended.

Smaller: `/admin/knowledge/collections` reports none while Qdrant holds
`kb_default`.

### Two defects in the second step of sign-in, and neither was reachable until today

Reported as "the TOTP field will not take input". It was two independent
defects sitting on top of each other, either of which alone makes the step
impassable, and the account had no other way in: the recovery-code route was
broken by the first of them too.

**The field dropped every keystroke.** `LoginForm` returns three branches —
password, TOTP, recovery code — from the same position, differing only in which
form's `control` they carry. React reconciles them as one component and reuses
the mounted `Controller`, whose registration stays bound to the previous form.
The input rendered, took focus, and showed nothing: the value went to a form
nobody was reading and the displayed `value` came from a field nobody was
writing. A `key` per branch forces the remount that re-registers it.

**The submission was a dead end.** `loginStepTwoSchema` required `challenge`,
which is not a form field — it lives in `useLogin` state and is attached by
`submitTotp` on the way to the API. The resolver rejected the only shape the
form could hold, so `handleSubmit` never called the hook, and the error was
attached to a name no `FormField` renders: no request, no message, nothing.

Diagnosis was slower than it should have been because the first probe was
written against a synthetic harness rather than the component. `FormField` with
the TOTP props accepts and displays typing perfectly *when it is mounted
directly* — which is true, and which sent the search towards CSS and the
browser, neither of which was involved. The step transition is the whole
defect, and only rendering the real component through it shows that. **Reaching
for the real thing early would have cost less than the two rounds spent proving
things about a stand-in.**

Each fix is attributed rather than assumed: with the `key` reverted, "shows the
typed code" fails `'' != '123456'` and the recovery route fails with it; with
the schema reverted, typing displays and only the submission fails. 180 frontend
tests pass, `tsc --noEmit` and eslint are clean, and the entrance is still
9/0/0 after redeploying both frontends from one image.

`src/features/auth/components/` had no tests at all, which is why two defects
sat in the one screen standing between the public entrance and everything
behind it. It has five now. Both were also invisible for the ordinary reason:
until this morning no request reached this application, so nobody had ever got
as far as the second step.

### The entrance passes everything, and the defect underneath it was waiting

**9 passed, 0 failed, 0 skipped at 10:14, the first time
`verify-public-entrance.sh` has been clean.** Both hosts are back, the four
directives are reaching the request, and `api.nexus.rcsl.online` answers
`{"status":"ok"}` from the gateway on `/healthz` and the application's
`{"detail":"Not Found"}` on `/` — checked by body, which is how our 404 is told
from the proxy's.

The paired probe reversed, which is the part that carries the claim. Sending a
wrong `X-Nexus-Proxy`, the real one, and none at all now return **401, 401,
401** — identical, the signature of nginx overwriting whatever the caller sent.
This morning the same three returned 400, 401, 400, and the divergence was the
evidence that the application was reading the caller's header. Neither reading
needs the configuration file to interpret it. A forged `X-Forwarded-For:
8.8.8.8` now yields `not_authenticated` rather than `country_not_allowed`: the
forged value is discarded, the real address is judged, and the country filter
and the per-key CIDR allowlists mean what they say again.

`perimeter_rejected` has stopped in `admin-public`, and `/admin/me` now reaches
authentication and is refused `no session cookie`. That is the first time a
request has arrived carrying the header from the entrance itself — the 64
earlier 401s were all probes supplying the secret by hand, which was the defect
rather than an exception to it.

**The cause was the duplicate `location`, confirmed by the administrator rather
than inferred here.** A Custom Location whose path is `/` collides with the
`location /` NPM generates for the same host; the reload fails and the
previously loaded configuration keeps serving, which is why the UI showed the
new directives and behaviour never changed. That was written down as the
leading candidate earlier the same day, before it was checked. Which route the
directives finally took is *not* recorded, and `nginx -T` for the `ai.` server
block is still worth capturing: the next person to rebuild this will otherwise
walk into the same trap the entry below describes.

One transient worth naming so it is not read as a fault. During the change `/`
timed out into a 504 while `/login` and `/account` returned 200 and
`/favicon.ico` returned an immediate 504; the origin answered `/` in 5 ms
throughout, so nothing on this side was involved. Readings taken while someone
is saving are not evidence about any configuration, including the one being
saved.

### A 401 from the public entrance said the tailnet had dropped

Found while verifying the above, live on the entrance that had just come up,
and fixed in `main_admin_public.py`.

`auth_mode` is echoed on 401 bodies so the frontend — one build serving two
entrances — can tell "your Tailscale connection dropped" from "go to the login
screen". `install_error_handlers` says exactly that in its docstring. Both
applications passed `settings.auth_mode`, which is deployment-wide and reads
`tailnet` in any real deployment, so the public entrance was answering a
browser arriving from the internet with `auth_mode: tailnet`. `app-shell.tsx`
then took both branches on that value: `shouldRedirectToLogin` is
`authMode !== 'tailnet'`, so the redirect to `/login` was skipped, and the
unauthenticated branch rendered **"Tailscale connection lost"** with a retry
button. The front door of the public entrance offered no way in. `/login` sits
in the `(auth)` route group outside the shell and still worked if typed, so the
side door was open the whole time.

It survived because the assertion was written for one entrance only:
`test_a_401_tells_the_frontend_which_entrance_it_reached` covers the tailnet
application and nothing covered the public one. And it was invisible in
production because no request had ever got past the perimeter to be refused by
the application — this is the second defect today that was hidden behind
another, and both surfaced within the hour the first was fixed.

The fix is the entrance's own mode rather than the deployment's: this
application is session-based whatever `AUTH_MODE` says, being the only one that
mounts the credential flow. The missing half of the test now exists and fails
with `assert 'tailnet' == 'local'` against the previous code. 547 unit tests
pass. `rcsl-ai-nexus:latest` was rebuilt — the working tree matched `1bcd12c`,
the commit the running image was built from, so the rebuild carries this change
and nothing else — and only `admin-public` was recreated. The tailnet entrance
still answers `auth_mode: tailnet`, and the entrance is still 9/0/0. The
browser itself was not driven; what was verified is the value on the wire and
the two conditions that read it.

**Confirmed end to end later the same day**, once the two login-form defects
below were also fixed: a real sign-in from a browser reached the login screen
rather than "Tailscale connection lost", and returned a session. That exercises
the whole chain in one go — the four nginx headers, the trusted-proxy check,
the country filter, CSRF and the session cookie — every segment of which was
broken this morning.

### The entrance came back with the headers still missing, and the 400 is not the page

The administrator restored `ai.nexus.rcsl.online` and moved the directives into
an NPM **Custom Location** — `Define location: /`, forwarding to
`TAILNET_IP:3001` — re-declaring NPM's own generated set (`Host`,
`X-Forwarded-Scheme`, `X-Forwarded-Proto`, `X-Real-IP`, `Upgrade`, `Connection`)
alongside our four. That is what [deployment.md](./architecture/deployment.md)
section 5 asks for, and the configuration as written is correct. It is not the
configuration nginx is running.

`api.nexus.rcsl.online` was not restored: still TLS alert 112 (`unrecognized
name`) on 443 and NPM's stock welcome page on 80. One of the two hosts is back,
so the script's sections 3–5 run against the management host instead of
skipping — **4 passed, 3 failed, 2 skipped**, against 1/2/6 this morning.

**The paired probe says nothing is being set, which is the same state as
2026-08-03.** A deliberately wrong `X-Nexus-Proxy` returns 400; the real value
returns **401**. If nginx set the header at all — right value or wrong — the
caller's own would be overwritten and both probes would return the same thing.
They differ, so what the application reads is the caller's header and nginx is
contributing nothing. The wrong-value branch is ruled out twice here: by the
probe, and by the person who entered it confirming the field holds the real
secret and was masked only when it was pasted.

`X-Forwarded-For` corroborates it independently. With the real secret and a
forged `X-Forwarded-For: 8.8.8.8` the request is judged American and refused
`country_not_allowed`. The block the administrator sent sets `$remote_addr`,
which would have discarded the forged value; what is running is NPM's own
`$proxy_add_x_forwarded_for`, which appends, and `client_ip.py` reads the first
value. Two directives out of one block, both absent, one cause — and no single
probe would have established either alone.

**The 400 in the browser is not the page.** `/` and `/login` return 200: they
are served by `frontend-public`, which checks nothing. Every `/admin/*` call
underneath returns `{"code":"untrusted_proxy"}`. The UI shell loads and each
request it makes is refused, which is what "the site 400s" looks like from a
browser, and it locates the fault precisely — routing is right and only the
header is wrong. The refused requests arrive from `172.19.0.3`, the frontend
container, so openresty is reaching `TAILNET_IP:3001` exactly as configured.

No request through this entrance has ever returned 2xx. Across the retained
logs `/admin/*` on the public app is 64×401, 58×400, 7×403 and nothing else —
and every one of those 401s is a probe that supplied the secret itself, which is
the defect rather than an exception to it.

### Why a correct configuration is not the loaded one

Not established from here; it needs `nginx -T` on the proxy to settle. The
leading candidate is that a Custom Location whose path is `/` collides with the
`location /` NPM generates for the same host — nginx refuses a duplicate
`location`, the reload fails, and the previously loaded configuration keeps
serving. That presents exactly as observed: the UI shows the new directives and
behaviour is what it was before them.

What to check, in order. That `X-Nexus-Proxy` appears **inside** a `location` in
`nginx -T` output, rather than merely appearing — that distinction is the whole
of the 2026-08-03 finding and it survives a change of field. That
`X-Forwarded-For` is declared **once** in that block and set to `$remote_addr`,
since nginx does not de-duplicate `proxy_set_header` and one inherited from
NPM's `proxy.conf` sitting beside ours restores the forgery. And whether the
reload reported `duplicate location "/"`.

The security consequence changed shape today rather than easing. This morning
the forged-`X-Forwarded-For` hole sat behind an entrance that answered nothing.
The management host now answers the internet with the hole live: the country
filter and every per-key CIDR allowlist are set by the caller.

### The entrance is off, and the script blamed the certificates

Both hostnames stopped answering overnight. The administrator has taken the two
proxy hosts down while working on yesterday's header placement, so this is
intended and temporary — but nothing about the way it presents says so, and the
first reading available was that the entrance had broken worse.

openresty itself is still up. What is gone is the two host entries: 443 answers
TLS alert 112 (`unrecognized name`) for every SNI, **including a name invented
for the test**, which is what separates "no server block matches" from "our two
certificates are bad"; and port 80 serves NPM's stock welcome page for both
names. Nothing on this side is involved: gateway, both frontends and
admin-tailnet all answer 200 on the tailnet, and the proxy still carries
`tag:ntnu-proxy`.

**The two header defects from 2026-08-03 are hidden, not fixed.** They are
properties of a configuration that is not currently loaded, and they return the
moment the hosts come back unless the four `proxy_set_header` directives move
inside the generated `location`. The entrance being down is the reason the
script can no longer see them, which is exactly why those checks now skip rather
than pass.

### One probe, four causes, and a confident message for the wrong one

`verify-public-entrance.sh` reported 8 failures, and the first of them said to
go and look at certificate scope. It read `%{ssl_verify_result}` and called any
non-zero value an invalid certificate — but that value is 1 whenever the
handshake did not complete at all, so a removed host, a stopped nginx, a dropped
packet and a genuinely bad certificate all arrived as one message, carrying a
hint about `*.rcsl.online` not covering two-label names. That hint is correct in
one of the four states and misleading in the other three, and today was one of
the three. This is the same shape as the `X-Nexus-Proxy` diagnosis corrected
yesterday: a single probe cannot support the accusation the message makes.

`entrance_state` now classifies by curl's exit code, which distinguishes what
the status code cannot — every one of these is `000`. `unrecognized name` is
corroborated from port 80: NPM answers a name it does not know with its own
welcome page, so seeing it means the proxy is *running* and the host entry is
missing, which is the difference between restoring a host and starting a
service. Certificate scope keeps its note, in the one branch where the handshake
got far enough for the certificate to be at fault.

Sections 3–5 skip when the entrance is not answering instead of failing three
more times with `got: ` and once with `unexpected status 000`. An empty body is
not evidence about what serves a path, and four hollow failures competing with
one real one is how the real one gets read past. **1 passed, 2 failed, 6 skipped**,
against 1/8/0 before, and the two failures name the cause and the fix.

Five of the seven branches were exercised end to end by pointing the script at
substitute hosts — `ok`, `cert` (expired and self-signed), `dns`, `refused`, and
`unconfigured` against the live entrance. `timeout` and `handshake` are not
covered: both need conditions that cannot be produced from here.

### A "postcss and sharp, upstream and unfixable" advisory turned out to be one of them

Dependabot flagged `postcss` again — CVE-2026-45623, GHSA-6g55-p6wh-862q, an
arbitrary-file-read: `PreviousMap` follows the `sourceMappingURL` path out of a
CSS comment with no scheme check and no traversal check, `path.join` does not
block `..`, and the first ~10 bytes of whatever it reads leak through the
`JSON.parse` `SyntaxError` message the caller sees. The 2026-07-30 entry above
called this one upstream and unfixable from here; it was not.

`pnpm-lock.yaml` carried two copies of `postcss`: `8.5.22` from
`tailwindcss`/`@tailwindcss/postcss`, already past the patched `8.5.12`, and
`8.4.31` — the vulnerable one — pinned exactly, not as a range, inside
`next@15.5.21`'s own `package.json`. Nothing in this project's `package.json`
names `postcss` at all, so pnpm had no lower bound of its own to fall back on.

`overrides: { postcss: ">=8.5.23" }` in `frontend/pnpm-workspace.yaml` forces
the second copy onto the same patched line as the first — `next`'s snapshot in
the lockfile now reads `postcss: 8.5.25` where it read `8.4.31`. `pnpm audit` no
longer lists it, `pnpm build` still produces every page (the exact path the
override touches, since Tailwind's postcss pipeline runs at build time), and
the 193-test suite and lint are unaffected. The four remaining advisories from
2026-07-30 are three; `sharp` is the one still actually upstream.

**The floor is `8.5.23` rather than the `8.5.12` this fix was written with**,
and the two revisions between those numbers are the useful part. `postcss` was
patched twice more while the change sat in review, both times for the same
`sourceMappingURL` reader: Dependabot alert #6 (path traversal, patched
`8.5.18`), and then an advisory for the *incomplete fix* of the very one this
entry opens with — arbitrary `.map` read when `from` is unset, vulnerable
through `8.5.22`, patched `8.5.23`. So the original floor would have permitted
five versions still vulnerable to the first, and the resolved `8.5.22` was
itself vulnerable to the second, which Dependabot had not yet raised. `pnpm
audit` found it and now reports no `postcss` advisory at all.

**And the override was in the file pnpm is in the middle of abandoning.** It
was written as `pnpm.overrides` in `package.json`, which is precisely what
`pnpm-workspace.yaml`'s own comment has warned about since 2026-07-26, when the
build-script allowlist was found sitting there being silently ignored. What
made this one hard to see is that it *worked*: pnpm 10.17.1 still honours the
field, `packageManager` pins that version, and CI installs through it, so every
check was green. pnpm 11 ignores the field and says so — the warning appears on
any `pnpm` command run outside the pin, which on this machine is the Homebrew
one. So the failure was scheduled rather than absent: the first regeneration
under a newer pnpm restores `next`'s exact `postcss@8.4.31` and no test fails.
Moved to `overrides:` in `pnpm-workspace.yaml`, verified by deleting the
`package.json` field entirely and watching the lockfile still follow an edit to
the workspace file.

Three things worth keeping. **An override floor is a promise about future
resolutions; only the lockfile says anything about this one** — reading the
range against the advisory catches what a green audit of the current tree
cannot. **A fix for a path-handling bug is a place to expect a second
advisory**, since the incomplete-fix advisory here is the same code, the same
reporter, and three weeks later. And **a pinned toolchain hides deprecations
rather than protecting you from them**: the pin is why this was invisible, and
the machine that ignored the pin is what surfaced it.

## 2026-08-03

### The public entrance went live, and two controls were reporting nothing

The proxy administrator did all four items today: the host joined the tailnet at
16:12 carrying `tag:ntnu-proxy`, both hostnames have valid certificates, and both
reach this deployment rather than a default page — `api.nexus.rcsl.online/healthz`
answers `{"status":"ok"}` from the gateway and `/` answers the application's own
`{"detail":"Not Found"}`, which is how you tell our 404 from the proxy's.

**Two of the four header confirmations in item 4 were not done, and neither is
visible from the proxy's side.** Every response there looks like a working TLS
terminator forwarding to a live backend.

`X-Nexus-Proxy` is not set at all. The first attempt to establish this was a
weak test — supplying the *correct* secret and watching the 400 become a 401,
which cannot distinguish "nginx sets nothing" from "nginx sets it and my header
was ignored". Supplying a deliberately **wrong** value is the test that decides:
it survived to the application, so nothing upstream is overwriting it. Every
request through the entrance was being refused, and 48 `/admin/me` calls from
`frontend-public` have never once returned 200.

`X-Forwarded-For` is appended rather than overwritten. A request sent from
Taiwan carrying `X-Forwarded-For: 8.8.8.8` came back `403 country_not_allowed`,
which means the forged value was believed. That is the country filter and every
per-key CIDR allowlist bypassed by a header the caller writes. Before reporting
it, the frontend was ruled out as the culprit: `middleware.ts` uses
`NextResponse.rewrite`, which forwards headers unchanged and cannot resurrect a
value nginx replaced, so the append is upstream of us.

Only the two together kept this from being live: the forged address is worthless
without the secret, and the secret is not in nginx to leak. That is a
coincidence, not a control. **The §14 forged-`Tailscale-User-Login` check passed
on the way through** — 401, with the public entrance stripping the header as §4
requires.

### The perimeter had an explanation for all of it, and threw it away

`untrusted_proxy` has three causes — wrong secret, absent `X-Forwarded-For`, one
that will not parse — and the response deliberately distinguishes none of them,
because naming the half that failed tells an attacker which half to work on. The
operator is meant to read the difference from `geo_middleware`, which writes one
line for exactly that purpose at INFO.

It had never appeared. **Nothing in this tree configured logging at all**, so the
root logger had no handler, Python's `lastResort` fallback took every record, and
that handler emits at WARNING and discards the rest. Every `logger.info` in all
three processes had been written, formatted and dropped since the first deploy.
The cause above was instead established by probing from outside with wrong values
until the answers narrowed it down — which is the work that line exists to make
unnecessary. The control was working and its own record of firing did not exist,
the same shape as the audit gap closed on 2026-08-02.

`infrastructure/logging_config.py` now configures the `app` logger, deliberately
not the root: raising the root also raises `httpx`, which logs a line per request
to the model runtime, on the hot path, saying nothing `usage_records` does not
already hold. `LOG_LEVEL` defaults to INFO.

**Writing the test found a second copy of the same defect.** The new unit tests
passed alone and failed in the full suite, with the logger reporting an effective
level of INFO while `isEnabledFor(INFO)` returned False — a combination that
means `disabled = True`, which no level inspection reveals. `alembic/env.py`
called `fileConfig` without `disable_existing_loggers=False`, and `alembic.ini`
names only root, sqlalchemy and alembic, so running a migration disabled the
entire `app.*` tree. A deployment is unaffected because `migrate` is its own
process; the test session was not, and had been silently discarding every
application log line from the first integration test onward. Two independent
mechanisms, found the same day, both of which made a diagnostic exist and never
arrive.

### The configuration was correct, and correct in the wrong place

The administrator sent a screenshot and it matched the template line for line.
The checks still failed. Both statements were true.

**The first thing that had to go was the diagnosis, not the configuration.** The
script reported "nginx is not setting this header" on the strength of one probe
— a deliberately wrong value coming back 400 — and that probe cannot support it.
Three states produce that result differently:

| | wrong value sent | real value sent |
|---|---|---|
| A: nginx sets nothing | 400 | passes |
| B: nginx sets the correct secret | passes | passes |
| C: nginx sets some other value | 400 | 400 |

A wrong value is refused in both A and C, so the message was accusing the
administrator of one specific mistake while the evidence covered two — and C,
a placeholder left in place or a secret that never arrived, is *exactly* what a
correct-looking screenshot suggests. Sending the real value separates them:
it passed, so the state is A. **Nothing is being set at all**, and the value in
the screenshot is not the problem.

That leaves placement, and one mechanism accounts for the whole failure.
`proxy_set_header` is inherited all-or-nothing: a level takes the set from above
only if it declares none of its own. NPM's **Custom Nginx Configuration** field
is inserted at *server* level; its generated `location /` carries its own
`proxy_set_header` directives, more of them with the websocket toggle on. So all
four of ours were discarded before a request was ever proxied — `X-Nexus-Proxy`,
the `X-Forwarded-For` override, and both `Tailscale-*` blanks. Two symptoms, one
cause, and both of today's findings explained by it. The same field's
`client_max_body_size`, `proxy_buffering` and `proxy_read_timeout` are not
`proxy_set_header`, inherit normally, and worked — which is why everything else
looked healthy.

**A third finding came out of reading the screenshot rather than probing.**
`client_max_body_size` was `10m` on the management host. That directive *is*
live, and 10 MiB is tighter than the application's own 32 MiB
(`upload_policy.py`), whose docstring says in as many words that nginx is set to
64m so ours is the limit that fires and the caller gets an error naming the
reason. Inverted, a 15 MB PDF meets nginx's HTML 413 instead of the upload
dialog's message. The template in deployment.md now carries that reasoning
beside the number instead of in a source file nobody configuring a proxy reads.

`limit_req` was missing too and is deliberately not being asked for yet. It is
the second line on a control the application already enforces — `LoginThrottle`,
measured here on 2026-08-02 at twelve attempts producing six failures and
exactly one throttle row — and requesting it means explaining that its
`limit_req_zone` goes at a *third* level again, to someone who has just lost a
round trip to levels. It follows once the entrance works. What did get fixed is
that `limit_req_zone` was never defined anywhere in deployment.md while §5's
template referenced the zone, so that template could not have loaded as
published.

Also recorded because it is what made three of the missing directives harmless:
this platform reads neither `Host` nor `X-Forwarded-Proto`. Checked rather than
assumed, and worth knowing before anyone else audits a proxy configuration
against the template.

### Deployed, and the log immediately said what the probing had inferred

Commit `1bcd12c` is on the Mac Studio: the backend image rebuilt and `gateway`,
`admin-tailnet` and `admin-public` recreated on it. `migrate` exited 0 — no
schema change, `alembic upgrade head` is idempotent, and it now runs with the
`fileConfig` fix. Recreate rather than restart, so requested-versus-actual port
bindings were compared on all three; all matched. Five entrances answered
`/healthz` 200.

The verification is the line itself, and it is worth the entry because it turned
an inference into a statement from the application:

    INFO app.interfaces.http.middleware.geo_middleware
      perimeter_rejected path=/admin/me code=untrusted_proxy
      detail=proxy secret missing or wrong

That names which of the three causes fired. Everything above it in this entry
was established by sending deliberately wrong values from outside and reading
the shapes that came back; this is the deployment answering directly. The second
finding confirmed the same way, and more completely than the external probe
could — the geo filter now records what it judged on:

    INFO ... geo_filter  rejected request from 8.8.8.8 (US)
    INFO ... geo_middleware  perimeter_rejected code=country_not_allowed detail=country=US ip=8.8.8.8

`ip=8.8.8.8` is the forged value being used as the basis of the decision, which
is the whole of the `X-Forwarded-For` finding stated by the thing that was
fooled. Six perimeter events recorded in the first three minutes, against zero
in the entire life of the deployment before this.

### An acceptance script, because neither failure shows up in a status code

`scripts/verify-public-entrance.sh` runs what was done by hand here: the tag, the
certificates, that the backends reached are ours, the two header controls, and
§14's forged identity. The two that matter work by sending something
deliberately wrong and requiring it *not* to survive, which is the only way
either can fail visibly. It reproduces today's state exactly — 7 passed, 2
failed — and is what the proxy administrator's fix will be checked against.

`security.md` §14 says several items must be tested rather than assumed. Until
today there was nothing to test them against.

### The deploy, and a page whose own HTML could not confirm it

Commits `a5ab7a7` and `7bb1ed4` are on the Mac Studio. Only the frontend changed,
so only the one shared image was rebuilt (`ea97a6c52ada` → `35924b43dd63`) and
only `frontend-tailnet` and `frontend-public` were recreated. No backend change,
no migration.

**Recreate, not restart, so the port forwards were checked.** A forward is
created with the container, which is why the reconciler uses `--force-recreate`
and why `restart` cannot repair a lost binding — and it is the same mechanism the
§1.1 boot race turns on. Requested and actual were compared on both containers
afterwards rather than assumed: `127.0.0.1:3000` and `100.108.250.62:3001`, both
matching. `tailscaled` was up throughout, so there was no race to lose; the check
is cheap and the failure it looks for is silent.

**The page could not be verified the obvious way.** `/api-docs` is a client
component, so the served HTML is a 12 KB shell containing none of the new text —
a `curl | grep` came back empty against a correct deploy, which is the shape of
result that gets read as a failed one. Verification moved to the build output
inside the running container, and **the two checks that carried the weight were
the negative ones**: `three share 400` and `vector_store_unavailable` are absent.
Those are the review's findings, so their absence proves the image holds the
corrected page rather than the first draft. Grepping only for the new strings
would have passed on either version, because the draft contained them too.

Six entrances answered 200 (both admin apps, the gateway, both frontends,
Grafana), eleven services up, and the health daemon's state file said `OK` with
no `failing` event across the recreate.

**The GeoLite2 daemon is loaded and has never run.** `launchctl print` shows it
scheduled, and `/opt/homebrew/var/log/nexus-geolite2.log` does not exist — the
refresh that happened today was a hand run whose output went to a terminal. So
what is proven is the script working and launchd holding the job; what is not
proven is launchd *firing* it, which is a different claim and the one the log
will carry on Wednesday at 05:30. The same distinction the health daemon needed a
boot to settle, where every mail before it had come from a hand run.

### The country database stopped ageing, four days after the mechanism to stop it existed

`launchd/refresh-geolite2.sh` was written on 2026-07-30 and did nothing until
today, because its plist was never installed, because the licence key was never
placed. The database was seven days old with nothing scheduled to replace it —
the same outcome as having no mechanism at all, which is the point worth
keeping: **a written script and an installed daemon are different states, and
only one of them is a control.** The key went into `secrets/maxmind_license_key`
(0600, no trailing newline, though the script strips whitespace anyway), the
script ran by hand, and the plist went in afterwards. Loaded in the system
domain, running as `rcslmac1` so it can reach the user's Docker socket, `state =
not running` because it is calendar-scheduled rather than `RunAtLoad`, firing
Wednesdays at 05:30.

The hand run did the whole path in two seconds: download, the two validity
checks, atomic replace, and `docker compose restart gateway admin-public` — the
tailnet entrance deliberately not cycled, since it does not enforce the filter.

**The restart is also the only verification available, and that is worth
stating.** There is no endpoint that reports which database a running container
has open, and geoip2 opens the file once at startup. What makes the restart
evidence rather than a hope is `build_geo_filter` refusing to start without the
file in production: both services came back up and answered `/healthz` 200 on
the tailnet address, so each opened a database, and the only one on disk was the
new one. A probe of `127.0.0.1:8000` answered nothing, which is §3.3 working
rather than a fault — five of the entrances bind the tailnet address, and a
loopback probe is the wrong question here.

**One thing the run surfaced: the new file's mtime is MaxMind's publish date,
not the download date** — `tar` preserves the archive's timestamp and `mv`
carries it across. So today's fresh download is dated 2026-07-31, and the
script's own staleness guard, which reads `stat -f %m`, measures **how old the
data is** rather than **how long refreshes have been failing**. The first is
closer to what matters, so this is left as it is; the log line it prints
(`refreshes have been failing`) is the part that would misattribute, and only in
the case where MaxMind itself went a month without publishing. Recorded rather
than fixed, because the fix is to separate the two claims and the message has
never fired.

### The five gaps in `/api-docs`, and the two the audit itself had got wrong

The page is the entire consideration `security.md` §4.4 receives in exchange for
disabling `/openapi.json` and `/docs` on the gateway. The 2026-07-30 audit found
five things it did not say; this closed them. Everything it already said was
accurate then and still is, so this is addition rather than correction.

What went in: the two grounding fields and the `X-Knowledge-Sources` header,
including the part an integrator cannot afford to guess — retrieval **degrades
to an ordinary ungrounded answer** rather than failing, so `use_knowledge: true`
is a request and the header is the only evidence it was honoured. The six OpenAI
fields that parse and do nothing, because pydantic's default is `ignore` and a
caller setting `temperature: 0` gets a 200 that means nothing happened. What a
mid-stream failure looks like on the wire, and the rule that follows from it: a
stream that ended without `[DONE]` is a failed request, not a short answer.
`prompt_tokens` declared absent rather than left to look measured. Four error
codes, and the note that `no_available_model` is also what arrives in an error
frame.

**Re-verifying the audit's own list against the code changed two entries, which
is the argument for not transcribing a finding into documentation.** The audit
said `vector_store_unavailable` was newly reachable through grounding. It is
not: `SearchKnowledge.execute_or_empty` catches `VectorStoreError` and
`NoAvailableModelError` precisely so a Qdrant outage cannot turn a working chat
into a 503. Publishing it would have told integrators to handle a 503 this
endpoint does not produce — a documented error that cannot happen is the same
class of defect as an undocumented one that can, and harder to notice because
nothing contradicts it. And the audit grouped the wall-clock deadline with the
mid-stream error frame; the deadline emits `finish_reason: "length"` and a
normal `[DONE]`, indistinguishable from the token ceiling. That is a truncated
success, not a failure, and a client told to treat it as a failure would retry
an answer it already had.

The reachability of what was added was checked the same way rather than assumed.
`model_not_found` turned out to be the one worth having: it is not
grounding-specific at all, since `_raise_for_status` maps Ollama's 404 on
`/api/chat`, so any deployment whose routing policy names a model the runtime
does not hold answers an ordinary chat request with a 404 no client would have
expected. `runtime_capability_unsupported` needs the `embedding` policy pointing
at MLX, which refuses to embed rather than returning a plausible wrong vector.
`untrusted_proxy` needs nothing but reaching the application port directly.

Gates: `tsc`, `eslint --max-warnings=0`, 171 vitest tests, and a real `next
build`. No backend change — every one of these was a behaviour that already
existed and was not written down.

### The review, which found the same defect this entry had just claimed to avoid

Six findings, all six confirmed against the code rather than accepted. Two of
them were the work being wrong in the way it had congratulated itself for
getting right.

**`internal_error` was a documented error that cannot happen.** Two paragraphs
above, this entry argues that publishing `vector_store_unavailable` would have
been a defect because the code never produces it — and the same commit added a
`500 internal_error` row. Counting the classes settles it: all 35 `DomainError`
subclasses are in `STATUS_MAP`, so `_status_for` never falls through to its 500
default, and the only bare `raise DomainError` in the tree is in `pull`, which
the gateway does not mount. Worse, a genuinely unexpected failure is not a
`DomainError` at all, so it never reaches the handler — Starlette answers with
plain-text `Internal Server Error` and no JSON. A client written from that row
would have parsed an envelope on the one status where it most needs to degrade.
The row now says exactly that, which is more useful than either publishing the
false code or deleting the row: **a 500 is the one response that is not JSON**.

**"Retrieval degrades quietly rather than failing your request" was false for
the likeliest embedding failure.** `execute_or_empty` catches `VectorStoreError`
and `NoAvailableModelError` — not `ModelNotFoundError`, which is what
`OllamaAdapter.embed` raises when the routed embedding model is absent from the
runtime. That is the same condition this entry had just called the most valuable
addition to the error table for `chat`; it escapes and 404s the whole request.
So `use_knowledge: true` *can* turn a working chat into a failure, in exactly
two ways, and the page now names both instead of promising it cannot happen.

The rest were the page contradicting itself — "three share 400" against a table
listing two, and the mid-stream frame described as carrying the same envelope
when `sse.py` writes it by hand with no `type` — plus the runbook's new section
being placed before the repository is cloned, so both of its commands were
unrunnable and the "prove the key works" step would have reported failure on a
correct setup by restarting containers that do not exist yet. It moved to §7
beside the other daemon installs, where the stack is already up.

**The through-line is that all four page defects are the same mistake**: writing
what the wire ought to do instead of reading what it does. That is the mistake
the 2026-07-30 audit existed to catch, repeated while closing it.

## 2026-08-02

### The administrator got public-entrance credentials, and the last two events fired

The account bootstrapped from a tailnet identity had no `password_hash` and no
`totp_secret` — an open item since 2026-07-26, and the reason four of the new
audit events had never been seen on this deployment. Closed through the UI:
**Re-invite** on the Users page, then the ordinary acceptance flow.

Two things about doing it that are worth writing down.

**The invitation link points somewhere that does not exist yet.**
`ADMIN_BASE_URL` is `https://ai.nexus.rcsl.online`, which is correct for the
deployment this will be and useless today — nginx is still the proxy
administrator's four outstanding items. The token is fine; only the host is
wrong, so swapping it for the tailnet hostname works. Worth knowing before
someone clicks a single-use link, reads a dead URL, and closes the dialog that
cannot be reopened.

**It has to be done from another device, and that is a feature.** MagicDNS still
does not resolve on the host itself (the 2026-07-26 caveat, still unchased), and
going around it via `http://127.0.0.1:3000` fails twice over: that path does not
pass through `tailscale serve`, so no identity header is injected and the admin
UI 401s, and `COOKIE_SECURE=true` means the `__Host-` CSRF cookie is dropped over
plaintext, so no form can be submitted. Doing it from a phone on the tailnet
therefore also closed the *other* thing 2026-07-26 recorded: that the tailnet
entrance "has never been confirmed end to end from a device that is not this
one, and that is the confirmation that counts."

Enrolment recorded `user.invitation_reissued`, then `user.invitation_accepted`
and `user.totp_enrolled` 0.8 ms apart — the pair added the day before, firing for
the first time. `totp_last_counter` is claimed, which is the check worth making:
it distinguishes "a TOTP secret was written" from "a code was actually verified",
and only the second means the second factor works.

**Then the login itself**, which a browser cannot do: the public entrance
requires the trusted-proxy header on every route and there is no nginx to add it.
Driven with `curl` instead, from a script rather than a pasted block — password
and code read from `/dev/tty` and piped into `curl`'s stdin, so neither becomes a
process argument. Password step, TOTP step, `/admin/me` with the session, logout:
all four passed, and `user.signed_in` (`factor: "totp"`) and `user.signed_out`
landed 50 ms apart. **That is the public entrance's whole login flow proven
before nginx exists**, which takes a piece of risk out of the cutover rather than
discovering it on the day.

**Nine of section 12's twelve event classes have now been observed in
production.** The three that have not — recovery code use, node registration,
user role changes — are absent because *the actions have never been performed on
this deployment*: one user, so no role to change; a single node written by
`provision` rather than through the write endpoint; and no reason to spend one of
ten recovery codes to watch a row appear. That is a different thing from a
recording that does not work, and the distinction is the whole point of keeping
the list.

### Two scripts that were wrong, and the second was wrong in the worse way

The first attempt at the login check was a block to paste into a terminal. It
wedged the shell: an interactive `read` inside a pasted block consumes the paste
buffer as its own input, so the remaining lines were swallowed as a string
literal and nothing ever reached the platform — confirmed by an audit log that
simply stopped. Rewritten as a file, reading from `/dev/tty` so that no pipe or
paste can feed it.

The rewrite then failed on `set -u` with `"${arr[@]}"` on an empty array —
**unbound variable on the bash 3.2 macOS ships**, fixed in 4.4, which is not what
runs here. The constraint is written at the top of this repository's own
`launchd/check-platform-health.sh`; it just was not read first.

The bug is ordinary. What it printed is not: the script answered *"no CSRF cookie
issued — is admin-public up?"*, and `admin-public` was entirely healthy. A
guessed cause presented as a finding, two lines away from the real one — the
shape this log keeps recording, produced this time by an error message rather
than by a check. It now states only what it observed and prints the actual HTTP
status for the reader to judge.

### Deployed and verified on the Mac Studio the same night

Commit `4c6604d`, CI green, both images rebuilt, `docker compose up -d`, `migrate`
exited 0. No migration in this change, so the deploy was a rolling restart of the
five services carrying the two images. `rollback-20260803` names the 2026-07-30
build, which had been serving three days without incident — the tag means "last
known good", not "previous", per [deployment.md](./architecture/deployment.md) §9.

**Two of the checks along the way could each have returned only one answer, and
both were caught before being believed.** The running image was going to be
dated against the last commit — and the image was built at 17:19:12 against a
commit at 17:19:03, nine seconds apart, which a timestamp cannot separate. Asked
instead whether the container held `_with_state`, the marker that commit
actually added, the answer was definite. Then a naive port probe reported three
of five entrances unbound, because it tested loopback: they are bound to the
tailnet address, which is §3.3 working correctly. A check that reports failure
on a correct configuration is the same defect as one that reports success on a
broken one.

What was verified live, on the deployment rather than in a test:

- **`authz.denied`**, driven by an administrator trying to change their own
  role. That refusal is raised directly by `ManageUsers` without consulting
  `AuthorizationPort`, so it is exactly the case the handler-based approach
  catches and a `require`-based one would have missed — the argument for the
  design, confirmed against the real thing rather than against a fake
- **`user.sign_in_failed` on three paths**: a real account attributed to its own
  user id with `no_local_credentials`, an unknown address-shaped login kept
  verbatim, and a password-shaped string recorded as `redacted:b64851d1…`, whose
  digest was checked against `sha256` of the string. The plaintext is not in the
  table
- **The throttle recording once per window.** Twelve attempts from one address:
  six 401s and six 429s produced six `user.sign_in_failed` rows and **exactly one**
  `user.sign_in_throttled`. Without the review's fix that would have been six,
  and unbounded under sustained grinding
- **The logs filter.** `outcome=denied` returns 2, `outcome=failed` returns 10,
  and `outcome=failure` — the value the UI sent until today — returns 0 against a
  table that now demonstrably has failures in it
- Zero `audit_write_failed` lines, so nothing took the swallowed-exception path;
  zero unexpected exceptions in any container; health check `OK` on a run whose
  state file was written the same second it was read

**What could not be verified live at the time of the deploy** — and was, an hour
later: `user.signed_in`, `user.signed_out`, `user.totp_enrolled` and
`user.recovery_code_used` all require a *successful* public-entrance login, and
no account on this deployment had public-entrance credentials. The bootstrapped
administrator carried no `password_hash` and no `totp_secret`, the open item this
log had been carrying since 2026-07-26. The one path exercised on the real
entrance at deploy time, `no_local_credentials`, was the platform's own report of
that same gap. See the entry below.

The verification rows are in `audit_log` permanently. There is no delete path in
any repository and the table is append-only by design, so removing them would
mean doing by hand the thing the design forbids. They are also true: those
requests were made.

### Two completeness sweeps, one of which came back clean and one of which did not

`ROADMAP.md` carried two Phase 2 items that are audits rather than features:
"full audit coverage across every event in §12" and "authorization checks
covering every use case". Both were run by enumeration rather than by sampling,
because the thing they are looking for is an absence, and an absence is what
sampling is worst at.

**The authorization sweep found nothing, and that is a result.** All 26 use
cases, every public method that takes an `Actor`, checked against
`self._authz.require`. Every one carries it. The five use cases without a check
are unauthenticated or self-scoped by design — `AuthenticateLocal`,
`AcceptInvitation` and `BootstrapFirstAdmin` are the flows that establish an
identity rather than use one, `ManageOwnAccount` goes through `_require_self`,
and `EmbedTexts` / `GroundChat` / `IngestDocument` are internal collaborators
that take no actor at all. `ManageApiKeys` was followed through by hand because
it is the one with a per-owner rule rather than a flat scope, and its three
write paths all reach `_require_owner_permission`. The layering did what it was
chosen for: putting the check in the use case rather than the router means
enumerating use cases is the same thing as enumerating the checks.

**The audit sweep found that the identity plane wrote nothing.** Nine of §12's
twelve event classes were covered, and all three gaps were in the same place.
`AuthenticateLocal`'s constructor had no `AuditPort` in it — so a successful
sign-in, a failed one, a spent recovery code and a sign-out all left the audit
log untouched. `authz.denied` did not exist either: `RoleAuthorization.require`
raised, `errors.py` mapped it to a 403 and wrote one `logger.warning`, and
nothing durable recorded that anyone had been refused anything.

Put another way, and it is worth putting this way because it is the reason the
gap mattered more than its size suggested: **every administrative action was
recorded and no authentication event was.** After an incident the log could say
what was changed and could not say who had signed in, from where, how many times
they had failed first, or what they had been refused. Those are the first four
questions anyone asks.

### A sentence in security.md that had been describing an intention for months

§5.3, in the present tense, on the login flow:

> Repeated failures raise an alert and are written to the audit log.

Neither half was true, and had never been true. §13.0's own Phase 3 list said
"alerting on authorization failures" was still to come, so the document
contradicted itself two hundred lines apart — and the sentence a reader reaches
first, while deciding whether the control exists, was the false one.

This is the eighth or ninth instance of the shape this log keeps recording, and
the first where the artefact carrying it was the security document rather than
the code. Worth noticing: the code was honest here. `AuthenticateLocal` made no
claim to audit anything; it simply did not take the port. Only the prose
asserted a control. A reader auditing the code against the document would have
found the discrepancy; a reader trusting the document would not have looked.

### What was built, and the two defects the building turned up

Sign-in now records `user.signed_in`, `user.sign_in_failed` (with the reason the
*response* deliberately withholds — an unknown login and a wrong password are
indistinguishable to the caller and must not be to the operator),
`user.sign_in_throttled`, `user.recovery_code_used`, and `user.signed_out` from
the logout handler. Authorization failures record `authz.denied` from the shared
exception handler.

**The handler, not the port, and the reason is worth stating.** Recording in
`AuthorizationPort.require` would be closer to the decision, but `require` is
synchronous and `AuditPort.record` is not, so it would mean making the port
async at seventy call sites — and it would *still* miss the refusals use cases
raise directly without consulting it, of which there are four: an administrator
changing their own role, disabling themselves, deleting themselves, and a key
id that does not exist. The handler is the one place every `NotAuthorizedError`
must pass through, which makes it the only place that cannot be forgotten by a
use case written next year.

**A recovery code gets two rows, deliberately.** `user.signed_in` says a session
was granted; `user.recovery_code_used` says a single-use credential was spent,
which is a fact about the account rather than about that login. §12 lists them
separately for the same reason: someone scanning actions for "was the second
factor ever bypassed" should not have to know to read inside a `detail` field.

**Every failure path records exactly once, and that is a constraint rather than
tidiness.** `dummy_verify` exists so an unknown login and a wrong password take
comparable time. A database round trip on some failure paths and not others
would reintroduce exactly the oracle it removes. The four branches in
`verify_password` now each perform one write on the same side of the same work,
and a future branch that skips it would be a timing leak as well as a missing
entry — which is now said in the module docstring, where the next person editing
it will meet it.

Two defects surfaced from building rather than from the sweep:

**`_self_actor` dropped `tenant_id`.** Invitation acceptance and password reset
consumption built their audit subject without carrying the user's tenant across,
so those rows landed in the default tenant. The logs screen is tenant-scoped, so
a non-default tenant's own enrolment events were invisible in the only view that
tenant can read. Found while writing the shared `audit_subject` module the login
path needed, which is the ordinary way this kind of thing surfaces: the second
caller is what makes the first one's assumption visible.

**An over-long value made the writer lose the event silently.** Postgres refuses
a string wider than its column rather than trimming it, and
`PostgresAudit.record` swallows its own failures on purpose — losing an event
beats turning a successful administrative action into a 500. Those two are fine
apart and bad together: any unbounded value silently drops the row. `target` on
an authorization failure is the request path, and nothing bounds a path, so a
few hundred characters of padding in a URL would suppress the record of someone
probing — **a way to be refused without leaving a trace, introduced by the
change meant to record refusals.** The writer now trims to each column's width
with a marker. `actor_display` was the near miss: `LoginRequest.login` is capped
at 255 and the column is 255 wide, so the longest login a caller can send fits
exactly, and a narrower column would have been trimming every failed login
instead.

### Where the checks were put, and what putting them back proved

Each new record was verified by removing it and confirming a test failed —
the habit from 2026-07-29 and 2026-07-30, and it earned its keep twice.

One test was wrong on the first run in a way worth recording. It asserted that a
replayed TOTP code records `totp_replay`, and it failed: a *sequential* replay
never reaches the conditional UPDATE, because `TotpPort.verify` already rejects
a counter at or below the stored one, so it arrives as `bad_totp_code`. The
`totp_replay` reason belongs to the concurrent case only — two requests carrying
the same code, both reading the old counter, both passing the Python check, one
losing the write. The test now drives that race explicitly with a repository
that advances the counter behind the caller's back, and a second test pins the
sequential path so the pair documents that **the reasons do not partition the
way their names suggest**. Left as it was, the log would have been read as
saying replays never happen.

The audit *writer* had never been tested against a real database at all: every
existing test used `FakeAudit`, which accepts anything, and the adapter swallows
its own failures, so a row Postgres rejected would have vanished with only an
application-log line. `tests/integration/test_audit_writer.py` closes that, and
it is the test that fails when the trimming is removed. The end-to-end
deployment test now also reads `/admin/logs` after walking bootstrap →
invitation → enrolment → sign-in → sign-out, and asserts the five rows are
there — through the real composition root, the real adapter and the real
columns, which is the only arrangement that would have caught a
`build_authenticate_local` that forgot to pass the port.

### The review of this work, and the amplifier the fix had built

Five findings, all real, all fixed. Three are worth recording because each is a
case of a control being turned against itself.

**Recording the throttle on every refusal was a write amplifier.**
`assert_allowed` refuses every request for the remaining 900 seconds and the
refused path never calls `record_failure`, so the counter never decays inside
the window. Recording each refusal therefore gave an attacker who had *already
been rejected* one unauthenticated INSERT per request — in its own transaction,
into an append-only table retained a year, and drowning the logs screen while it
went. The limiter exists to make abuse cost the attacker rather than the
platform, and the audit record inverted it: the cheapest thing an attacker could
do became the most expensive thing the platform did. Now claimed once per
address per window through the limiter that owns the window, keyed on the
address rather than the pair, because the pair key would let the same attacker
mint a fresh marker per invented login *after* the per-address ceiling had
already made refusal free — the amplifier again with an extra step.

**Signing out had quietly acquired a database dependency.** Naming the account
for the sign-out row added a `users.get`, and the logout handler's whole
docstring is about working when things are broken: it deliberately does not
require a valid session, because returning 401 would leave the cookie in place
on a shared machine. With the lookup unguarded, an exhausted pool meant a 500
*after* `sessions.destroy` had run — session gone, cookies still in the browser,
which is the exact outcome the docstring exists to prevent. Worse, the docstring
added the same day *claimed* the record was best-effort. That is the shape this
log keeps recording, committed a few hours after an entry about finding it in
§5.3, and this time it was in text written to describe the fix.

**A password typed into the login field would have been stored for a year.**
`unknown_subject` recorded the presented string verbatim, reasoning that it
arrived unauthenticated from the network and is not a secret. True of an
attacker; not true of the ordinary user who types their password into the login
box, whose credential would then sit in `actor_display` — readable with
`logs:read`, retained a year, in the table §12 says must never carry a
credential. Logins are `EmailStr` at creation, so the test is cheap: keep the
string when it is address-shaped, otherwise a digest that still groups repeats
and can be confirmed against a suspected value. `LoginThrottle` had already
reached this conclusion for its own counters, and the reasoning was sitting in a
docstring one file away.

The other two: the throttle row was attributed to `unknown` even when the login
named a real account, which put it in the default tenant — so a tenant
administrator watching an attack on their own user would have seen every
`user.sign_in_failed` and none of the rows saying it had become an attack, the
very failure the tenant test written that afternoon guards against for the other
rows; and three second-step refusals raised silently while the module docstring
claimed every outcome was audited, the most interesting being an account
disabled inside the five-minute challenge window, which is precisely what an
incident review goes looking for.

### And the logs screen's Failure filter had never matched a row

Checking whether the new events needed anything in the UI turned up something
older. The action filter is a free-text box and needed nothing. The outcome
filter is three buttons, and the third one sent `failure` — a value nothing in
the backend has ever written. The writer produces `success`, `failed` and
`denied`, and the query is an exact match on the column, so pressing **Failure**
turned a working query into an empty one.

The failure mode is the reason it survived: an audit log with no failures in it
looks like a well-behaved deployment. There is no error, nothing renders wrong,
and the one reading it concludes something reassuring. It is the same shape as
the audit job that never ran behind a green pipeline (2026-07-30) and the
account-split test that asserted nothing (2026-07-26) — a control that reports
the good answer whatever is true.

Now three buttons matching what is written, with `denied` split from `failed`
because they are different questions: `failed` means an action was attempted and
did not complete, `denied` means it was refused. As of today `denied` is the
busiest of the two, which it could not have been before this afternoon.

### What was deliberately not done

**The gateway does not write audit rows.** Its database account may INSERT into
`usage_records` and nothing else (§6). Granting it `audit_log` would let a
compromised gateway write into the record that exists to describe the
compromise, to capture one event: a key reaching for a capability it was not
issued for. That refusal stays in the application log and the usage series, and
the absence is now stated in §12 rather than left to be discovered.

**Alert delivery is still Phase 3.** What exists now is the substrate — every
throttle trip and every refusal is a queryable row. The rule that reads them and
the channel it reports to are the remaining work, and the channel already
exists: `launchd/check-platform-health.sh` mails on a state change.

**The knowledge job read still has no tenant filter.** `GET
/admin/knowledge/jobs/{job_id}` was the one thing the authorization sweep did
find, and only half of it is fixed. Its scope check used to be a call to
`list_collections` whose result was discarded — correct, but indistinguishable
from a stray query, and one tidy-up away from taking the endpoint's entire
authorization with it. That is now an explicit `assert_may_read`. The tenant
boundary is the half left standing: job ids live in a cache entry with no
tenant, so a knowledge reader who learns another tenant's job id sees that job's
document id and progress. The id is a uuid4 and the entry lives 24 hours, so it
is recorded in §7.3 as the one read the isolation paragraph does not cover,
rather than fixed by putting a tenant on the cache entry.

## 2026-07-30

### What `/api-docs` does not say, audited against the wire it describes

`security.md` §4.4 trades `/openapi.json` and `/docs` away on the gateway in
exchange for hand-written public documentation. The page exists (2026-07-28), so
the trade has looked settled since — but nothing had ever compared it against
what the gateway actually serves. Read side by side with
`routers/chat.py`, `schemas/chat_schemas.py` and `errors.py`, five things are
missing, and two of them make an integrator write code that is wrong without
saying so. **Recorded rather than fixed**, so the gaps are visible while the
decision about the third one below is still open.

**Knowledge grounding is not mentioned, and the gateway implements it.**
`ChatCompletionRequest` carries `use_knowledge` and `knowledge_collection`; both
paths in `routers/chat.py` honour them, and a grounded answer returns its
citations in `X-Knowledge-Sources` as `<document_id>:<passage index>`. The
request-field list on the page covers `stream`, `max_tokens` and `think` and
stops there, so the most valuable thing this deployment can do is undiscoverable
from the only document that describes the contract.

**`temperature`, `top_p`, `n`, `stop`, `tools` and `response_format` are
accepted and silently dropped.** The request model sets no `extra`, so pydantic's
default `ignore` applies — verified against the model itself, not inferred. A
caller who sets `temperature: 0` for reproducibility gets 200 and the model's own
default, with nothing anywhere saying the field went nowhere. This is the class
of thing documentation exists for: not a missing feature, a silent
non-compliance with the schema the page claims to be compatible with.

**`usage` is half-filled, and absent entirely when streaming.** `_collect`
builds `Usage(completion_tokens=tokens, total_tokens=tokens)`, so
`prompt_tokens` is always the default `0`; anyone doing cost accounting
under-counts the input side permanently. The streaming path emits no `usage`
object at all, so a client sending `stream_options: {include_usage: true}` — the
OpenAI way to ask — receives nothing. **The open question is which of the two
this is**: documenting "prompt tokens are not reported" is honest and free,
while actually counting them means changing what `RouteChatRequest` records, and
the quota deliberately meters produced tokens only. Documenting it first, and
treating the count as a separate roadmap item, is the current inclination rather
than a decision.

**A stream that fails after the first byte is a 200 with an error frame, and no
`[DONE]`.** That design is deliberate and right — the status line is committed
before the failure, so `sse.py` yields `{"error": {...}}` and suppresses the
sentinel, because `[DONE]` means "completed normally" — and its own docstring
says it is "documented for consumers". It is not: the error section describes
HTTP statuses only. A client that treats a missing `[DONE]` as a transport
problem will retry a request the platform deliberately refused, and one that
treats the error frame as content will show it to a user. The wall-clock
generation deadline reaches callers the same way and is also unmentioned.

**Five reachable error codes are not in the table, four of them newly reachable
because grounding is.** `vector_store_unavailable` (503) when Qdrant is down,
`runtime_capability_unsupported` (400) when the `embedding` policy names a model
that cannot embed, `model_not_found` (404) when the runtime does not hold the
weights the registry claims, `untrusted_proxy` (400) for a misconfigured proxy,
and the unmapped fallback of 500 `internal_error`. Two smaller inaccuracies sit
beside them: the envelope also carries `type` (`OPENAI_ERROR_TYPES`), which the
page's example omits, and `Retry-After` is set on `quota_exceeded` as well as on
`rate_limited` — the page implies only the latter, which is exactly the field a
client needs to back off correctly.

What the audit did *not* find is worth stating too, because it is the part §4.4
depends on: everything the page does say is accurate. The capability convention,
the `GET /v1/models` narrowing ("narrowed to what your key was issued for" — and
`ListCapabilities` does intersect with the key's own list), the two-403 and
two-429 distinctions, and the reasoning about `reasoning_content` never being
merged into `content` all match the code. The gaps are omissions, not errors.

### Review of the day's four commits, and the six things it found

Six findings, all fixed. Three deserve recording because each is a shape this
log has already recorded once.

**The observation outranked a load that had just happened.** Making routing
prefer the observation over the intent — the whole point of the read-back — left
nothing to invalidate an observation when the platform itself writes intent. The
sweep records `observed_state=downloaded`; the operator loads the model;
`state` becomes `loaded` and the stale observation still outranks it, so for up
to a heartbeat interval a `model_state: [loaded]` policy skips the model that is
resident and a single-candidate policy answers 503. **The verification earlier
that day missed this by luck of timing**: qwen7b was loaded and the assistant
tested a minute later, after the next sweep had corrected the observation. One
more instance of a check that could only return one answer. Fixed by pairing the
clear with the intent write in both writers, and the pairing is now stated on the
port rather than left in two adapters.

**A test that passed either way, again.** The first fix came with two unit tests
asserting that a load clears the observation — and both passed with the defect
put back, because `ManageModels.load` writes `LOADING` through the state
committer first and *that* write clears it. The assertion was true for a reason
unrelated to what it claimed to pin. The contract now has an integration test
against real Postgres, where the UPDATE actually lives, and that one does fail
when the clause is removed. Same lesson as 2026-07-29, arrived at from the other
direction: putting the defect back is the only way to know a test is load-bearing.

**A docstring promising a claim that was not atomic.** `claim_reindex` said a
second re-index "is refused with an answer rather than racing" while reading the
status and writing it in two statements — so two tabs both claim, and both
delete and re-upsert the same Qdrant points, leaving the document briefly
unsearchable. `claim` gets away with the same shape because the row it claims was
inserted by the same request moments earlier; a re-index has no such protection.
Now a conditional UPDATE (`claim_document_status`), the same mechanism
`advance_totp_counter` uses, with the tenant filter every other write carries.

**And a seventh, found by verifying the first fix on the Mac Studio rather than
in a test.** Unloading a model answered `intent=downloaded, observed=loaded`
while the row itself held neither: `load` and `unload` return
`replace(model, state=...)`, an entity read *before* the write, so the response
carried the observation the same request had just cleared. The models table
renders a mismatch between the two in red, so the API was showing the operator a
divergence that did not exist. Worth recording because the unit tests for the
fix had all passed — the defect was only visible in an actual response body.

The rest: the new CI would have failed on its first run, because
`pnpm/action-setup` reads `packageManager` from a root `package.json` this
repository does not have; re-index was a write gated only on the read scope,
harmless today because only administrators hold either knowledge scope and a
real hole the first time a read-only role exists; models on any *other* node were
being observed as `not_downloaded` by the local runtime's answer, which the new
ranking would have turned from a wrong status into a model refused outright; and
the GeoLite2 refresh's "atomic mv" crossed a filesystem boundary (`/tmp` to the
repository), holding only because both happen to share a volume on this host.

### The first CI this repository has had, and what it found in its first run

Every quality gate here ran on the machine of whoever was committing: pre-commit
hooks that `--no-verify` skips, and two test suites nobody but the author ran.
The integration suite was the easiest of all to leave unrun, because it needs a
Postgres — and it is the suite that caught the account-split test asserting
nothing (2026-07-26). `.github/workflows/ci.yml` now runs all of it on push and
pull request: backend lint, format, strict mypy, unit tests, then the
integration suite against a real `postgres:17-alpine` service; frontend
typecheck, eslint, vitest, and a real `next build` — the last of these because
the baked-in admin URL from 2026-07-26 was a build-time defect that no test
would have shown.

**Setting it up made two local facts visible.** `ruff format` had not been clean
on `main` for some time (four files, two of them written the same day), which is
exactly the kind of drift a gate on someone's laptop permits. And every CI
command was run locally first, because a workflow whose steps have never been
executed is a red pipeline waiting to happen rather than a gate.

**And the audit job's first run proved the point it was written about.** It
never ran at all: `aquasecurity/trivy-action@0.29.0` does not exist (the tag
carries a `v`), an unresolvable `uses:` kills a job in "Set up job" before any
step executes, and because `continue-on-error` was on the *job* the run still
reported success. A scanning job that has never executed, behind a green
pipeline — the same "designed, written down, marked done, and not actually in
force" shape this log keeps recording, this time in the very thing added to
catch it. Every *command* had been run locally first; an action reference is the
one thing that cannot be, and that is exactly where it broke. `continue-on-error`
now sits on the three scanning steps instead, so a broken workflow or a failed
install fails the job and is visible, while a scanner that ran and found
something does not.

That move exposed the next layer of the same problem, and it was in a sentence
this file had already written: "the signal goes to whoever looks at the run". A
`continue-on-error` step reports its conclusion as success whatever it found, so
the findings existed only in the run log — and fetching logs needs admin rights
on the repository, which the operator reading this does not have. The claim was
false as written. All three scanners now write their output to
`$GITHUB_STEP_SUMMARY`, which renders on the run page with no special rights, and
the Trivy summary step is `if: always()` because the case worth publishing is
exactly the one where the scan stopped on a finding.

**The audit job is advisory, deliberately.** `pip-audit`, `pnpm audit` and
Trivy fail when *someone else* publishes an advisory, not when this repository
changes; blocking a merge on that means an unrelated CVE stops an unrelated fix,
which is how a red pipeline stops being read at all. It also runs weekly, so a
disclosure lands against unchanged code rather than waiting for a commit. Trivy
is scoped to `vuln,secret` and **not** `misconfig`: those rules have never been
run against this repository, so switching them on would publish a wall of
untriaged findings — and several would be choices `security.md` §15 records as
accepted. Triaging that is its own piece of work, and doing it badly here would
undermine the same argument the `continue-on-error` rests on.

**It found something on the first run.** `shadcn` — a scaffolding CLI used to
generate components, imported by nothing — was declared as a production
dependency, which put `@modelcontextprotocol/sdk` and its path-traversal
advisory in the shipped dependency tree. Moved to `devDependencies`: five
advisories became four, and the remaining four are Next's own `postcss` and
`sharp`, upstream and unfixable from here. A small finding, and precisely the
class that only appears when something other than the author's habits looks at
the repository.

### Re-index without re-upload, and a preview that shows the text rather than the file

Two knowledge base follow-ups, and both turned on a decision about what *not*
to touch.

**Re-indexing exists because the extracted text was kept for it.** Changing the
embedding model or the chunk size makes every stored passage stale, and the
only remedy before this was deleting each document and uploading it again —
which runs the parser a second time on every one of them. The parser is the
component with the CVE history and each run is an exposure, so a path that
re-embeds from the text already on the volume is the difference between a cheap
operation and one nobody should want to perform. `claim_reindex` moves the row
straight to `indexing`, never `extracting`, because nothing extracts.

It is offered on `error` as well as `extracted` and `indexed`, and that needed
a decision rather than a default. An `ERROR` document may have failed *during*
extraction, in which case there is no text and no amount of re-indexing will
produce one. Excluding `error` to be safe would refuse exactly the retry that
costs nothing — a post-extraction failure is the case this path was built for —
so it is allowed and the missing-text case is reported precisely: "No extracted
text is stored; upload the document again." The remedy differs from every other
failure on the path, so the message sends the operator to the upload rather
than back to the button they just pressed.

**The preview serves the extracted text, never the uploaded bytes.** Serving
the original back would hand a browser an attacker-supplied PDF to render,
which is the plugin surface the isolated parser exists to keep out of this
deployment — the preview would have quietly reintroduced it at the last step.
The text is rendered as plain text and not as markdown, the same reasoning that
makes a retrieved passage data rather than instructions. It is bounded at
20,000 characters (an upload may be 32 MiB) and the server carries the
`truncated` flag rather than letting the client infer it from a length, because
a client comparing against a constant of its own would disagree the first time
either changed.

Neither path adds a progress mechanism: the re-index moves the row to
`indexing` and the document table already polls while anything is transient, so
the 202's job body is deliberately dropped on the frontend.

### The registry stops taking its own word for it (Phase 2)

The roadmap carried two items that were one item wearing different clothes:
"reconcile the registry's `loaded` state against what is actually resident"
and "`MetricsPort` ingestion, a live memory figure feeding the budget". Both
are the platform reading real state back from the runtime instead of trusting
what it asserted earlier, so they were built as one mechanism.

The registry's `state` column is intent: asserted once when a load or unload
completes, and never re-checked. `qwen7b` read `loaded` for hours on
2026-07-27 while Ollama held nothing, and `OLLAMA_KEEP_ALIVE=-1` removed only
the most common cause of that lie (Ollama's own idle timer), not the class —
a runtime restart, an out-of-band `ollama rm`, or an eviction to make room
all leave the same standing falsehood. And the day this was built, the same
shape was live in production a second way: the `assist` policy's only
candidate required `model_state: [loaded]` while `qwen7b` sat at
`downloaded`, so the management assistant had quietly stopped routing to
anything.

**Intent and observation are separate columns, deliberately.** The choice
was between overwriting `state` when the runtime disagrees, keeping a
separate observation, or merely alerting. Overwriting was rejected because it
destroys the information that there *was* a disagreement — the operator sees
`downloaded` and cannot tell a deliberate unload from an eviction the
platform never sanctioned. So `models` gains `observed_state`,
`observed_memory_gb` and `observed_at`, written by the existing heartbeat
(the node-status half now has a model-residency half), and `state` stays
what it always was: what the platform last did on purpose.

The heartbeat asks each runtime that can answer — Ollama answers from
`/api/ps` and `/api/tags`; MLX has no residency endpoint and answers None,
the same honest refusal its `unload` and `embed` already make. **None means
"could not ask", never "nothing is resident"**: an unreachable runtime clears
the observation rather than asserting absence, because a network blip that
reads as "everything is unloaded" would be one more check that can only
return one answer, and 2026-07-26 already taught what those cost. A cleared
observation makes every reader fall back to intent, which is exactly the
pre-observation behaviour.

Three readers consume the observation. Routing's `model_state` requirement
now matches the observation when one exists and intent otherwise, so a
policy asking for a loaded model gets weights that are actually resident —
this is what turns the qwen7b lie from "standing for hours" into "corrected
within a heartbeat interval". The memory budget prefers
`observed_memory_gb` over the declared profile, because the runtime's own
figure includes the KV cache the form field does not: the measured gap is
5.7 GB resident against 4.7 GB declared for a 7B model, and with
`glm-4.7-flash` it is 38 GB against a declared 32. `list_occupying_memory`
also counts a model the runtime reports resident regardless of intent, so
weights warmed by an out-of-band `ollama run` are memory the budget sees.
The models screen shows the divergence in red under the intent badge and the
resident figure next to the declared one; agreement and "not observed" both
stay quiet.

What this deliberately does not do: write `state`. No automation moves
intent, because intent is the operator's, and the first design that
auto-healed it would have erased the very evidence the operator needs to ask
why the runtime dropped a model. And the `MetricsPort` roadmap item is
narrowed rather than closed: the budget now runs on observed residency,
which is the number that was missing, but a genuine host free-memory figure
(the OS and containers included) has no source a container can reach and
waits for a host-side exporter if one is ever warranted.

**Deployed to the Mac Studio the same day, and the deploy verified both this
and the knowledge base below.** The heartbeat's first sweep wrote honest
numbers: `glm47-flash` observed at 35.7 GB against 32 declared, `qwen7b`
agreeing at `downloaded` on both columns — which was itself the live instance
of the problem, because the `assist` policy's only candidate required
`loaded` and the assistant had quietly stopped routing. Loading `qwen7b`
through the API fixed it (observed 5.3 GB against 5.0 declared, caught by the
next sweep), and the assistant answers again. The knowledge base then went
end to end for the first time: a markdown file with fictional facts uploaded,
parsed in the isolated container, embedded through the `embedding` policy,
indexed into Qdrant (status `indexed`, one chunk), retrieved by semantic
search (score 0.61), and a grounded chat answered the fictional project
number and date correctly with the citation in `X-Knowledge-Sources`. The
test document was deleted afterwards so fiction does not pollute retrieval.
What remains unverified is quality at scale — one small document proves the
path, not the ranking.

The largest Phase 2 item, in four commits: uploads with an isolated parser, then
chunking and embeddings into Qdrant, then retrieval wired into the chat, then
the screen. Four decisions were taken before any of it was written, and each
changed what got built rather than only how.

**Documents live on a volume, not in MinIO, and the plan said MinIO.** It was
dropped on contact with the deployment. MinIO is another service to run, another
set of default credentials to replace (`minioadmin`/`minioadmin`, which
`security.md` §10 names), and another CVE surface; what it would have bought
(presigned URLs, per-tenant credentials, storage outliving one machine) is
unused by a single node with one filesystem. `ARCHITECTURE.md` §4 now records
this, with the trigger to revisit it: the moment a second compute node has to
read the same documents.

**Parsing runs in its own container, and its isolation is subtraction rather
than configuration.** This is the part worth remembering. `security.md` §7.3
required "a separate resource-limited process with no network access", and the
obvious reading — spawn a subprocess with rlimits — would have put the parser
inside the admin container, next to the database credentials and the mounted
secrets, which is where an exploit would then land. So `app/parser/` is a fourth
ASGI application in the same image, and what makes it isolated is what it does
not have: it reads no settings, so a compromise finds no credential in its
environment; it mounts no volumes, so a file-write primitive has nothing to
write to; it sits alone on an internal network, so it reaches neither the
internet nor Postgres, Redis or Qdrant; and it runs read-only with dropped
capabilities and a memory limit, so a decompression bomb kills it and not the
host. The same image rather than a second one is deliberate: the boundary that
matters is process, network and credential, not which layers the code was built
from.

Every one of those properties is one convenient import away from silently
stopping being true, and neither mypy nor a functional test would notice. So a
test parses the package with `ast` and fails if it ever imports from
`app.domain`, `app.adapters`, `app.application`, `app.infrastructure` or
`app.interfaces`. It is parsed rather than grepped because the module docstrings
name those packages precisely in order to explain the rule, and a text scan read
the explanation as a violation the first time it ran.

**Path traversal is made unreachable rather than validated.** The storage port
takes a document id and never a location, so no argument exists through which a
`../` could travel; the adapter is constructed with the tenant, putting it in
the path the way the scoped repositories put it in the WHERE. The uploader's
filename is kept for display only, and sanitising it is about what a control
character or a right-to-left override does in an operator UI, not about what a
slash does to a path. The other two attacker-controlled parts of an upload are
bounded separately: a size ceiling read in chunks rather than after `UploadFile`
has spooled the body (and never trusting `content-length`, a client header on a
streamed request), and a media-type allowlist checked against the file's own
magic bytes so a declared type cannot steer bytes to the wrong parser.

**Embeddings go through the existing routing policy, not a setting of their
own.** `embed` is on `ModelRuntimePort`, so an embedding model is registered,
budgeted and routed exactly like a chat model, and a policy on the `embedding`
capability decides which one answers. A second way of naming a model would be a
second place for the registry to be wrong. Two silent-corruption cases are
refusals rather than approximations, both for the same reason: they would not
fail, they would index the knowledge base with values that retrieve confidently
and wrongly. MLX raises rather than embedding, which is the judgement its
`unload` already makes; and a batch answered with the wrong number of vectors is
refused rather than zipped, since pairing passages with each other's embeddings
is invisible afterwards.

**The vector store's tenant boundary is enforced twice, and this deviates from
what the design specified.** `security.md` §7.3 described one shared Qdrant
collection with a payload filter, and included the code. That is sound but fails
in the wrong direction: a search that lost its filter returns every tenant's
passages. Each tenant now gets its own collection, named from the tenant the
adapter was constructed with, so a lost tenant names a collection that does not
exist and errors instead; the payload filter is applied as well. The document is
updated rather than left to disagree. Qdrant is also reached over its REST API
instead of `qdrant-client`, which would pull grpcio and protobuf into an image
that needs neither for calls that fit in a hundred lines of httpx, and it gets
the §6 least-privilege treatment: the gateway holds Qdrant's **read-only** key,
mounted at the same target name, so retrieving a passage cannot become writing
one. Its key is a required production secret with no opt-out, unlike the metrics
token, because Qdrant ships with no authentication at all and there is no
deployment shape where the placeholder is intended.

**Retrieval was added without touching `RouteChatRequest`.** That file is the
most carefully ordered in the tree, and putting a database read and an embedding
call in front of the concurrency slot and the `finally` that records usage would
have meant reasoning about all of it again. So grounding is a transformation of
the messages that runs before it: the streaming path receives a longer list and
nothing else. It is the same move the metrics work made when it added
observation through a wrapped repository rather than instrumenting the
generator, and it is the second time that shape has paid off.

The prompt assembly is where the injection concern is answered, and none of the
three mechanisms is asking the model nicely. Passages go in their own system
message rather than spliced into the user's turn. Each is fenced with a marker
generated per request, so a document would have to guess 64 bits to close its
own fence, and the marker is stripped from the passage if it appears anyway — a
fixed marker is one an uploaded file can simply write. And the instruction
naming them as data is placed *after* them, because an instruction before an
untrusted block is what the block is trying to override. This is mitigation and
is documented as such: no prompt construction makes a model immune to
instructions in its context, which is why "model output is always untrusted
input" still stands beside it.

Retrieval is opt-in per request, because it costs an embedding call and a slice
of the context window and silently grounding every completion would surprise an
API caller. Citations come back in a header rather than an extra SSE frame,
since the envelope is OpenAI's and a new frame shape is a protocol error to a
strict client; the header carries ids and indexes only, never passage text,
because a header reaches access logs (§9.2). It runs under `chat:use` rather
than `knowledge:read`, so a `user` who may never list documents still has
questions answered from them, and it degrades to an ordinary completion when
Qdrant or the embedding policy is unavailable — while deliberately not
degrading an authorization failure, which is a decision about who may ask.

**One real defect, and it is the familiar kind.** Both the document storage and
the vector store required their tenant id to be a UUID. `DEFAULT_TENANT_ID` is
the literal string `default`, which is the tenant every existing deployment runs
under, so both adapters refused it outright. Every unit test passed a generated
UUID and nothing noticed until an end-to-end request went through the real
gateway. The assertion was about the wrong property: what has to be true is that
the value is a safe path segment and collection name, not that it is a UUID.
That is now what is checked, and pinned against the default tenant explicitly.

Two pre-existing breakages were fixed on the way. `test_db_role_grants.py` had
not been updated when `usage_records.tenant_id` became NOT NULL, so the test
that proves the gateway account cannot write `api_keys` had been failing on a
constraint before reaching any grant — the security property it exists to
demonstrate had quietly stopped being demonstrated. It now also pins that the
gateway cannot write the knowledge base. And ruff's `S608` fires on the tenants
migration's hardcoded table interpolation, pinned per-file the way
`db_roles.py` already is.

Verified: 134 new backend tests (the upload policy's three attacker-controlled
inputs; the storage adapter against a real temporary directory, where another
tenant's document does not resolve and no write lands outside the tenant
directory; the parser service turning a crafted PDF into a refusal rather than a
traceback, plus the `ast` isolation test; chunking geometry, including that
overlap repeats text without losing any; the Qdrant adapter's request shapes;
the ingestion pipeline through indexing, a re-index replacing a stale tail, a
scanned PDF with no text layer indexing as zero passages rather than an error,
and a failed index preserving the extracted text so a retry does not re-run the
parser; and the prompt structure) and 9 new integration tests against real
Postgres 17. The full suite is 424 unit and 69 integration tests passing, ruff
and mypy clean, 77 frontend tests with `tsc`, `eslint` and `next build`
generating `/knowledge`, and `docker compose config` still showing the gateway
sharing no network with either admin entrance or with the parser.

What waits for the Mac Studio is what always does: real embedding, and whether
retrieval actually answers questions well, which is a quality property no stub
can report. The upload rules, the parser's isolation, the tenant scoping and the
prompt structure are exercised now.

---

## 2026-07-29

### An assistant in the admin UI, and the one filter that would have defeated it

The management UI now carries an advisory assistant: a drawer mounted by the app
shell, so one conversation follows the operator from the key list to the API
reference and back. It answers questions about this deployment's settings and,
on the two API key forms, offers values as a card the operator applies and then
saves themselves.

**It advises and does not act, and that was the design decision rather than a
first increment.** No tool call, no write path, no new authorization edge. Every
write still happens through the dialog that always performed it, with the scope
check in `ManageApiKeys` and the audit record it already had. The whole reason a
language model can sit in the control plane without reopening
[security.md](./architecture/security.md) is that it is not a caller with
permissions — it reads what the operator is already looking at and prints a hint
beside the form. §7.3 has said since Phase 2 that model output is untrusted
input and that agents and tool calls are where that becomes the line between
prompt injection and remote code execution. Staying on the near side of that
line is the feature.

Four controls are structural rather than remembered, which is the only kind
worth writing down: the request schema has no `system` role, so the instructions
assembled from live domain values cannot be displaced by a client; the frontend
publishes a six-field `ApiKeyDraft` that has no field a plaintext could arrive
in, and the create dialog stops publishing at all once a key exists; a proposal
is validated against `UpdateApiKeyRequest`, the same schema `PATCH` uses, which
also has no `owner_id`; and the operator's screen is serialised into a block
delimited by a per-request nonce, because a key's *name* is text its owner chose
and a fixed marker is guessable by anyone who has read the source.

### The filter that had to be re-applied by hand

`assist` needed to be routable without being issuable — a policy has to point it
at a fast model, and a key issued for it would sell an external integrator a
seat at an internal management surface. So `KNOWN_CAPABILITIES` became
`ISSUABLE_CAPABILITIES` and `ROUTABLE_CAPABILITIES`, with every reader forced to
say which question it is asking. There is deliberately no third name meaning
"either".

That split has a hole in it that the type system cannot see. **`ListCapabilities`
does not read either constant**: it derives its answer from the routing policies
that exist, and it feeds both `GET /v1/models` and the key-issuing form. So the
ordinary act of making the assistant work — writing a policy for `assist` —
would have published `assist` to every integrator and offered it in the issue
dialog, at the exact moment the split was supposed to be preventing that. Found
by reading the use case rather than by a failing test, because there was no test
that could have failed: nothing was wrong until a routable-only capability
existed.

A second one came out of the same read. `_scopes_for` was carefully a fixed
table so no database row could promote a key into the control plane, and the
comment above it says so — but `Actor.allowed_capabilities` was set to
`key.scopes` verbatim two lines below. `ManageApiKeys` refuses to issue `assist`,
so the only way to get one is a direct write to `api_keys`, which is precisely
the threat that rule exists for. Now intersected with the issuable set, which
restores the property the surrounding code already claimed to have.

### A setting nothing read

`API_KEY_MAX_LIFETIME_DAYS` was in `Settings`, documented in `.env.example`, and
read by nobody: `build_manage_api_keys` never passed it, and `ManageApiKeys`
carried an identical default of 365. The two agreed by coincidence, so setting
it to 90 changed nothing at all.

Found because the assistant has to quote the limit to an operator who is about
to rely on it, and a second reader of a number that was never authoritative is
how it starts being quoted wrongly. Both readers now take the setting. Same
shape as `api_keys.debug_logging_until`, which is still a column nothing writes
and nothing reads.

### What the assistant is not allowed to be slow

The capability is separate from `chat` for one measured reason, recorded on
2026-07-27: 16,384 tokens and 10m53s for zero answer tokens. Beside a settings
form that is not a slow answer, it is no answer. `assist` gets its own routing
policy pointing at a fast model, `think: false` on every request, and
`ASSISTANT_MAX_TOKENS=1536` — far below the platform ceiling, because this
answers in two or three sentences and a ceiling near the length of a good answer
turns a rambling model into a cut-off paragraph rather than ten held minutes.

**Neither prerequisite can be done from the development machine.** `assist` needs
a routing policy, and that policy needs a fast non-thinking model registered and
downloaded on the Mac Studio. Until both exist the drawer answers with
`assistant_unavailable`, which names the fix — unlike `no_available_model`,
which would send an operator looking at node load for a policy that was never
created.

### Reading past the terminator

The proposal has to be finished before it can be validated, so it travels as a
trailer: one frame after the terminal `finish_reason` and before `[DONE]`. Added
to the shared SSE framing as an optional argument rather than as a second framer,
so there stays one implementation of the envelope, the error branch and the
sentinel.

Which surfaced a real ordering problem on the client. `readChatStream` returns
the moment it sees a `finish_reason` — deliberate, tested, and correct for every
chat turn — so it would never have reached the trailer. The reader now keeps
going to the sentinel, but only for a caller that provides `onTrailer`, and the
reason is deferred rather than dropped. The frame is handed over undecoded on
purpose: `streamFrameSchema` strips unknown keys rather than rejecting them, so
a trailer routed through it would have arrived as `{}` — the same silent failure
that once made the chat panel render every reply as nothing at all.

Model output is stripped from the visible answer as it streams, which needs a
holdback: the `<proposal>` marker arrives split across chunks at whatever
boundary the tokeniser chose, and a partial `<propo` cannot be taken back once
it has been streamed. Flushed at the end — which turned out to be the wrong
place, and is the first finding of the review below.

353 backend tests and 135 frontend tests, up from 318 and 116.

### Deployed, and the two prerequisites that were not remote after all

Recorded as operator work "on the Mac Studio" while the development machine was
assumed to be somewhere else. It is not: this repository is checked out on the
Mac Studio, and the stack had been up for twelve hours. Worth writing down
because the claim was made twice in the same session, confidently, from
`README.md`'s statement that the development machine *need not* be the target.
A `hostname` would have settled it.

`qwen2.5:7b` was already registered as `qwen7b` and already loaded, and Ollama
reports its capabilities as `completion,tools` with **no** `thinking` — exactly
what the drawer needs. `glm-4.7-flash` is the other resident model and reports
`thinking`; it also holds `chat` at priority 200 against `qwen7b`'s 100, so the
`chat` capability resolves to the deliberating model. That is the measured case
from 2026-07-27 and the reason `assist` is a separate capability rather than a
setting.

Deploy was the routine upgrade from [deployment.md](./architecture/deployment.md)
§9: tag the running images, `docker compose build`, `docker compose up -d`,
confirm `migrate` exited 0 and that the ports are *bound* rather than merely
`Up`. Then the `assist` policy — which the previous image would have refused,
since its `KNOWN_CAPABILITIES` had no such name, so the policy and the code that
permits it could not be deployed in either order separately.

**The `ListCapabilities` filter was then confirmed against the live system**,
which is the check the whole two-set split exists for: an `assist` policy exists
and `GET /admin/gateway` still answers `["chat"]`. End to end, the drawer
answered in **6.6 seconds** against the same hardware that spent 10m53s
answering nothing through `chat`.

One thing about how the policy was written is worth being explicit about. The
tailnet entrance trusts its identity header outright and is protected by binding
to loopback, so an operator on the host can present any login they like. The
policy was written that way rather than through a browser, and the audit row
therefore reads `leolove3very@gmail.com / tailnet / routing_policy.saved`. The
identity is the authorising person's own and the action was theirs, but the
hands were not: that is a limit of what an audit log can record, and it is
better stated here than discovered later. Direct SQL would have been worse — it
bypasses the capability validation *and* leaves no row at all.

The `models.capabilities` column for `qwen7b` still reads `["chat"]` although it
now serves `assist`. `RoutingService` never reads that field — it matches on
`model_state`, `node_status` and free memory only — so this is a label on the
models screen rather than a fault. Left alone deliberately, and noted here so
the next person to read that column knows it is not authoritative for routing.

### What the review found, and the one it was wrong about

Eight findings against the assistant commit, all of them behaviour no existing
test covered. Two changed what reaches a screen or a wire.

**The holdback was released after the terminal frame.** The flush ran in the
code after the loop, which is after the chunk carrying `finish_reason` has
already been framed — so every answer's last nine characters arrived behind the
frame that ends the stream, and any client that stops reading there loses them.
That includes this repository's own `readChatStream` whenever `onTrailer` is
absent. The identical mistake is recorded against `RouteChatRequest` earlier in
this file, on 2026-07-27, and it is easy to make twice for the same reason both
times: **the frame that ends a stream is not the last one the code writes.**
Now released *on* the terminal chunk, with a tail that is a proper prefix of the
marker dropped rather than shown, since a block the model began and did not
finish is not text.

**The page-context registry was a slot rather than a stack.** Screens nest — the
key table stays mounted while a dialog on top of it registers — so closing the
dialog reset the surface to `other`, and the table beneath never re-registered
because its effect dependencies had not changed. Both call sites carried
comments asserting the opposite behaviour, which is the part worth noticing: a
comment describing an intention reads exactly like a comment describing a
guarantee.

The rest: `historyFor` sliced to the full cap and *then* appended the question,
sending 41 messages to a schema that accepts 40 — so after twenty exchanges every
further question was refused, and permanently, because the transcript is
restored from `sessionStorage`; a restored turn was shape-checked on two fields,
so a proposal from an older build with no `fields` reached `Object.entries` and
took the whole shell down on load, which is precisely what the loader's own
docstring claimed it prevented; clearing mid-stream let the in-flight turn
reappear in the transcript it had emptied; an abort before the response headers
was reported as a failure reading "signal is aborted without reason"; a screen
with no form published `{}` rather than undefined, making the system prompt's
"no form is open" branch unreachable and describing an empty key form to the
model while it was being asked about the documentation page; and two documents
still named `KNOWN_CAPABILITIES`.

**One finding was wrong, and it was accepted before being checked.**
`useChatStream` was reported as sharing the clear-mid-stream defect, and it was
repeated onward as fact without verification. It does not: its `finally` reads
the answer back out of the stream store, and `clear` resets that store before
the aborted read resumes, so the guard is already false. `useAssistant`
accumulates into a local, which the reset cannot reach — that difference is the
whole of it. The fix that had been written for the chat hook was reverted: dead
code defending an unreachable case, carrying a comment that explained a bug
which had never existed. The behaviour is now pinned by a test instead, because
the protection is indirect enough to be broken by an unrelated change.

### Removing each fix to see whether its test notices

Every fix in the round above has a test, and each test was checked by putting
the defect back. That caught one that did not work: the `AbortError` exemption
had a test that passed with the exemption removed, because the mock resolved
immediately and the abort therefore reached the reader rather than `fetch`. The
branch being "fixed" was never executed. Rewriting the mock to reject is what
made the test mean anything.

Both lessons point the same way and neither is about this feature. A test
written after a fix passes for the same reason the code does, and reading your
own code confirms what you meant rather than what you wrote. The mistake with
`useChatStream` was the same failure without the test: a claim that matched the
shape of a real bug, asserted without executing anything.

### The keychain again, from the other side, with a push that looked like it failed

`git push` ended with `fatal: failed to store: -61` while reporting the refs it
had just updated. The push had worked; only caching the credential failed. That
combination is the actual hazard — a line beginning `fatal:` that means the
opposite of what it says.

2026-07-27 called the Docker `credsStore` workaround "one instance of a class"
and this is the second instance, but the mechanism is worse than that entry
described. It is not that the login keychain is *locked* and nobody can answer
the prompt. It is that **the login keychain is not in a non-GUI session's
keychain search list at all**: `security list-keychains` returns
`/Library/Keychains/System.keychain` and nothing else, though
`~/Library/Keychains/login.keychain-db` sits there on disk. So the helper cannot
read either — `git credential-osxkeychain get` returns nothing — and the earlier
"unlock it and it works" reading does not apply.

Which raised the question of where the credential for a working push came from.
`GIT_ASKPASS` points at VS Code Server's `askpass.sh`, so it came from the
editor attached at the other end. **Nothing was stored on this machine at all**,
and every push depended on a client being connected — invisible while one always
is, and fatal to anything scheduled. `gh`'s stored token is separately expired,
so that was not a fallback either.

One thing narrows it: the repository is public, which was confirmed by cloning
the ref list with no credential and `GIT_ASKPASS` pointed at `/usr/bin/false`.
Only writes need authentication.

Fixed with an SSH deploy key rather than a token. A PAT on this machine can only
live in plaintext in `~/.git-credentials`, and §8 of security.md argues against
exactly that shape of secret; a deploy key is scoped to one repository and
revocable on its own. No passphrase, deliberately — a passphrase needs
`ssh-agent` and unlocking an agent needs somebody at the machine, which is this
problem one layer down. The host key was pinned against GitHub's published
fingerprint rather than accepted on first connection.

Two details worth keeping. The verification has to be run with `GIT_ASKPASS`
removed from the environment, or it proves only that the editor is still
attached. And the fingerprint comparison was written as a `grep` for the
literal string, which reported MISMATCH on two fingerprints that were visibly
identical: `+` is a repetition operator, and `SHA256:+DiY...` as a pattern means
"one or more colons". It failed closed, which is the only reason that was a
five-second problem rather than a habit of ignoring the check.

355 backend tests and 155 frontend tests. `vitest.setup.ts` gained
`afterEach(cleanup)` on the way, since these are the repository's first
component tests and Testing Library does not auto-clean without Vitest's
globals — the symptom is "found multiple elements", which reads as a broken
assertion rather than as missing setup.

---

## 2026-07-28

### The key was issuable and unusable

The question asked was whether the self-service path works: someone reads the
site, issues a key, and wires it into their own application. Key *management*
turned out to be in good shape. Everything after the clipboard was missing.

The holder was handed a bare `nx_live_...` and nothing else. **No base URL
appeared anywhere in the UI** — `PROXY_HOSTNAME` existed in configuration and
was never shown. **No documentation existed either**: §4.4 disables
`/openapi.json` and `/docs` on the gateway and says the public API is
"documented separately", and separately was nowhere. And the field that decides
what gets served, `model`, takes a **capability** rather than a model name,
which is a convention nobody guesses and which nothing on the wire disclosed:
the gateway mounts `/v1/chat/completions` and nothing else, so **`GET /v1/models`
— the first call every OpenAI client library makes — returned 404**. Guessing
wrong was punished with 503 `no_available_model`, deliberately made
indistinguishable from every node being busy, so a typo in the model name read
as a platform outage.

A member could not even look the answer up: §5.2 withholds model, routing and
node reads from them on purpose, because those let a member enumerate the
registry and the node's tailnet address.

Closed by giving each of those a home. `GET /v1/models` answers in OpenAI's
shape with the capabilities a routing policy actually serves, narrowed to the
calling key, and authenticated like everything else so that what a deployment
serves is not a free answer to a stranger. `GET /admin/gateway` gives the UI the
base URL (from configuration, since the admin origin cannot read the gateway's
off its own request) and the same capability list, behind `chat:use` rather than
`routing:read` so the people integrating can read it. The issue dialog now shows
curl, Python and TypeScript with the real key and the real origin already in
them, at the one moment the plaintext exists — a snippet somebody has to come
back and fill in is one they fill in wrongly. Both are backed by a single
`ListCapabilities` use case, because deriving the list twice is how the two
would come to disagree.

### The capability list on a key was decoration

Found while making the issue form offer only capabilities that would work.
There was no point gating the picker: **the stored list never restricted which
capability a key could invoke.** `RouteChatRequest` checked `CHAT_USE` and then
routed on whatever the body named, so a key issued for `chat` reached every
capability the deployment could serve. Worse in the other direction —
`_CAPABILITY_SCOPES` mapped only `chat` onto a scope, so a key issued for `code`
alone held no scopes at all and was refused everything, a choice the form
offered and the gateway could not honour. Both halves had been true since the
field was introduced, and security.md §4.2 describes it as "allowed
capabilities".

The fix keeps the reason the mapping is hardcoded. Scopes still come from a
fixed table so no database row can promote a key into the control plane;
`Scope.CHAT_USE` now answers only "may this caller reach inference at all", and
every inference capability grants it. *Which* capability is data, so it travels
on `Actor.allowed_capabilities` and is checked where the capability is read.
`None` there means a person on an admin entrance, unrestricted by capability
because their role decides their reach. Refused as 403 rather than folded into
the 503, because this is the one routing failure the caller can actually fix.

That reordering broke two existing tests, which is the useful part: they asked
for `vision` with a `chat`-only key and expected "nothing serves this". The
refusal now arrives first and hides that path, so the fixture key was widened
and the tests about the list mint their own narrow keys.

### Smaller things found on the way

**The edit endpoint had no caller.** `PATCH /api-keys/{key_id}`, the client
function and the `useUpdateApiKey` hook all existed and no component reached
any of them, so a key's limits, quota, sources and expiry could only be changed
by hand. It had also never been exercised over HTTP — the payload the dialog
sends, date-only expiry included, is now pinned by a test.

**A member could not manage their own keys.** Every action was gated on
`isAdmin` while the backend grants `api_key:write_own` to every role, and the
navigation entry was not admin-only, so a member got a page that could only ever
be empty and read-only. Gating now mirrors `_require_owner_permission`.

**An administrator could not issue on someone's behalf**, though `owner_id` had
been in the request body all along.

**The CIDR rule in the issue form had never run.** The regex sat on an array the
form never held while the text was split into the request after validation, so a
typo surfaced as a server error instead of a field message. Both dialogs now
validate the text they actually hold.

**And one comment was actively misleading**: the revoke client said the backend
"drops the Redis verification cache". §4.2 records that cache as a deliberate
non-feature — revocation is immediate because every request re-reads the row —
so a later reader could have "fixed" the missing drop by adding a revocation
window.

### What review found in the same day's work

Two of its findings were defects in the thing just built, both in the same
shape: **a control that could not do what its own copy said it was for.**

The edit dialog resubmitted the expiry on every save. A date input holds a
calendar day, so an untouched `18:00Z` expiry came back as midnight — every
edit silently shortening the key by up to a day, and once that midnight had
passed, refusing outright. Renaming a key that expired later the same day was
impossible, and so was the "extend it before it lapses" workflow both the
dialog and the API page advertise. The endpoint is a PATCH; the field is now
sent only when it was actually changed, or when the key was already expired and
the prefilled date is deliberately not the stored one.

The capability picker disabled every capability no policy served, including
ones a key already held. So a key issued for `vision` whose policy was later
deleted could never have `vision` removed — precisely the narrowing the control
exists for. Disabled now applies on the way in only.

Three more were consequences of the day's own choices. `gatewayInfoSchema`
parsed capabilities as the five-value enum while `ManageRoutingPolicies.save`
accepted any string at all, so one policy named `summarise` would have thrown
in the parse and taken out both the picker and the whole API page. That
disagreement is the older bug: `KNOWN_CAPABILITIES` lived in
`manage_api_keys.py` and was consulted only there, so a policy for `chatt`
stored and audited cleanly while no key could ever be issued for it. The set
now lives in `domain/entities/capability.py` and all three readers use it —
including the gateway's scope mapping, which had been a third copy listing only
`chat`. The frontend parses the list as plain strings regardless, because a
display list must never be able to take down the page that documents the
platform.

The error table was wrong in two ways worth recording, since §4.4 makes that
page the contract. It claimed 403 always means the key lacks the capability,
but the geo filter raises `country_not_allowed` at 403 too — an integrator
blocked by location would have reissued keys forever. And "every failure
carries `error.code`" is false for a body the schema rejects: only `DomainError`
has a handler, so a malformed request gets FastAPI's `{"detail": [...]}` at 422.

Both were the same failure as the capability list itself: **documentation and
controls describing an intent the code did not implement.** The tests added
alongside them assert the behaviour rather than the intent, which is the only
version that stays true.

### The documentation audit that followed, and the two claims that had rotted

Propagating the day's work turned up staleness older than any of it, in both
places that describe what exists.

[backend.md](./architecture/backend.md) §2 said "everything under
`application/use_cases/` other than `route_chat_request.py` and
`authenticate_local.py` is unwritten, as is every router except `chat.py` and
`health.py`". Twenty use cases and eighteen routers later, it still said that.
[ARCHITECTURE.md](./ARCHITECTURE.md) §3 was worse, because it was a table: "None
of the admin API exists yet", with almost every module marked *frontend only*
and routing policies, logs and usage marked *no*. All of them had been built and
exercised against a real Postgres, several of them months of work ago.

Both are the same failure and it is worth naming: **a status written once is
worse than no status**, because it is read as current. The fix is not only to
correct them but to say in each what happened, so the next reader knows the
column drifts and where the maintained answer lives.

Three smaller corrections came out of the same pass. The architecture diagram
advertised `/v1/embeddings`, which has never existed — replaced with
`/v1/models`, which now does, and §2.3 gained the honest version: `embedding`
and `rerank` can be issued on a key and named in a policy, but the gateway
mounts only `/v1/chat/completions`, so they have no endpoint whose shapes fit
them. [backend.md](./architecture/backend.md) §5 gained the 422 case its own
error table implied did not exist, the two statuses that carry two codes each,
and `ContextTooLongError`. And a claim written during this very audit — that a
`jobs.py` router exists — was wrong and caught before it landed; download
progress is served by the router that starts the download.

### What is still not done

`api_keys.debug_logging_until` remains a column nothing writes and nothing
reads. Pepper rotation still has no completion path: the previous pepper is
accepted at verification, but nothing re-signs a key with the new one (the
gateway account has no write on `api_keys`, so it could not), nothing reports
which keys are still on the old one, and no runbook covers it. There is still
no reissue-with-the-same-settings action, and `keyStatus` has no
expiring-soon state, so rotation is still forced by expiry and unaided by the
UI.

---

## 2026-07-27

### A generation that answered nothing looked identical to a malfunction

Reported live: reasoning finished, no reply came, and the clock vanished. The
generation was real and so was the outcome — **16,384 tokens, 10m 53s, zero answer
tokens, `completed = f`**. The raised ceiling did exactly what it was predicted to do
for this class of question: it did not rescue it, it made it cost eleven minutes of a
concurrency slot instead of four.

The defect is that the screen could not say so. `readChatStream` read the terminal
frame's `finish_reason`, branched on it, and **threw it away** — so `length`, the
platform's own ceiling reporting itself honestly, never reached the UI. A truncated
generation and an ordinary completion that happened to be empty rendered as the same
blank bubble. The elapsed time disappeared too, because the live message carrying the
clock is replaced by the finished turn, which had nowhere to put it.

Both now travel with the turn, and an answerless turn says which of the two it was.
The reason is passed to `onDone`, kept in the snapshot and on `ChatTurn`, and rendered
as one line — including the suggestion that follows from the measurements, since
`think: false` answers the same question in 49 seconds.

Worth naming as a pattern rather than a bug: **the backend was honest and the
interface discarded it.** `finish_reason` exists precisely so a client can tell
"stopped early" from "finished"; the wire carried it correctly all along.

### The Docker build was blocked by a locked keychain, not by Docker

The workaround recorded earlier — a `DOCKER_CONFIG` with no `credsStore` — turned out
to be one instance of a class. The root cause:

```
security show-keychain-info login.keychain-db
  → User interaction is not allowed.
```

`docker-credential-desktop` reads the macOS keychain, the keychain wants a GUI session
to answer an unlock or allow prompt, and **this machine is headless by design** —
display off, operator on SSH. Nobody can answer, so the helper waits forever. Buildkit
takes its registry auth from the CLI over the session, which is why `build` failed the
same way `pull` did, and why restarting Docker Desktop changed nothing.

Fixed by removing `credsStore` from `~/.docker/config.json` (backed up alongside it).
`auths` was empty and every image this project pulls is public, so the helper was
hanging in order to return nothing. The cost is conditional and small: a future
`docker login` to a private registry would store its credential base64-encoded in that
file rather than in the keychain — but on this machine the keychain path does not work
at all, so the real choice was plaintext or unusable, not plaintext or protected. Every
actual secret continues to live in Docker file secrets under `./secrets`. Verified with
no environment variables set: `docker pull` and `docker compose build` both complete.

**The generalisation is the part worth keeping.** ARCHITECTURE.md's first paragraph
says this Mac Studio is treated as a 24/7 server rather than a personal computer. Any
tool that expects someone at the screen is structurally broken here, and it will not
announce itself — it hangs. Recorded in the runbook's gotchas appendix, because the
next occurrence will not look like Docker.

### Auditing the documents found four things that were already wrong

Not drift from this week's work — drift that predated it and had never been caught,
because nobody re-reads a document to check it against the code:

- `backend.md`'s port example imported `CompletionChunk` from `entities/model`, where
  it has never lived, and its `generate` signature had neither `max_tokens` nor
  `thinking`.
- `frontend.md` §1 described the `/admin` proxy as a `next.config.js` `rewrites()`
  entry. That was replaced by middleware on 2026-07-26 *because* standalone builds
  bake it at build time — so anyone debugging the proxy from this document would have
  opened a file that no longer does the job.
- `security.md`'s guardrail table gave the deadline as "for example 600 s" and sized
  concurrency by loaded model count rather than by users.
- `ARCHITECTURE.md` and `ROADMAP.md` carried the same numbers a layer up.

A second pass at the end of the day caught one more, this time genuinely fresh: both
`frontend.md` and `backend.md` still described the `Thinking` toggle as omitting the
field when checked, which is the behaviour the review had already overturned hours
earlier. **The document was accurate when written and wrong by the time it shipped.**
That is the argument for the cross-file test added alongside the proxy timeout: an
invariant a comment cannot enforce should be asserted by something that runs.

### Ollama's five-minute timer had been overruling the registry all day

`load` sends `keep_alive: 10m`. `generate` sent none — and Ollama applies its own
default to any request that omits the field, so **every generation reset the model's
residency to five minutes**, and the configured ten never took effect once. Measured:
**14 loads in one day**, five of them in the last seventy minutes of use, each one a
gap longer than five minutes.

The cost per occurrence is small — a cold load of the 31.8 GB model is **2.3 s** with
the file in page cache — but the shape is this file's recurring defect again, in its
fifth instance: a setting that was chosen, written down, and silently overwritten by
the next request the same component made.

**The deeper issue is that `loaded` was never true.** The registry says a row is
loaded, the memory budget reserves its weights, and `unload` is the release path —
three components modelling residency, all of them overruled by a timer that knows
none of it. `qwen7b` had read `loaded` for hours while absent from memory entirely.
So the default is now `-1`: resident until something asks otherwise, which is what
the other three already assume.

**One trap worth the conversion code.** Ollama takes a duration string (`10m`) or a
number of seconds, where negative means forever — but the *string* `"-1"` is refused
with `time: missing unit in duration "-1"`. The environment supplies strings, so the
adapter converts a numeric setting to a number before sending. Left alone it would
have been a 400 mapped to `NoAvailableModelError`, i.e. an operator who set the value
correctly reading "No model is currently available" and going to look at routing
policies.

**Not done, and deliberately.** Nothing reconciles the registry's state against what
is actually resident, so `loaded` remains an assertion made once at load time. A
reconciler belongs with the Phase 2 `MetricsPort` work, which has the same shape —
reading real state back from the runtime — rather than as a half of it now.

### The wait before the reasoning appears was drawn as nothing at all

Reported as "the pause before thinking shows up is too long". The pause is not long:
a cold load of the 31.8 GB model measures **2.3 s** with the file in page cache. What
was wrong is that the interval rendered **empty** — no placeholder, no cursor, no
clock.

The placeholder written for exactly this (`Thinking...`) is guarded by
`status === 'streaming'`, and the store's status only left `idle` when the first
delta arrived. So the one interval the placeholder existed for was the one interval
it could not render in. Three seconds of an empty box reads as a hung application.
`begin()` now marks the request in flight and stamps `startedAt`, so a placeholder
and a running clock appear on submit. **This is the fourth instance of this file's
recurring defect** — written, marked done, never reachable — and the first one on the
frontend.

The reasoning block became a **one-line ticker**: elapsed time and the tail of the
current deliberation in the summary, full text behind the disclosure. A block that
grows for four minutes pushes the page down for four minutes, and the reader's real
decision during a long deliberation — stop and re-ask with thinking off — is answered
better by a clock than by paragraphs. It shows elapsed seconds and not a token count,
because the client can only count frames and 6625 frames measured 8192 tokens; a
figure labelled "tokens" derived from frames would be precision that is not there.
Still not markdown, deliberately: scratch work should not read with the authority of
a conclusion.

It also stopped snapping shut. `open` was a controlled prop derived from whether an
answer had started, so the block closed in the reader's face on the first answer
token.

### Review found two live defects, and one hypothesis worth writing down as refuted

**`StubRuntime` in the integration suite never grew the port's new argument.** Every
fake in the unit suite did; this one is behind `skipif(not TEST_DATABASE_URL)`, so it
passed by not running. Against a real Postgres it fails 7 of 12 with a `TypeError`
inside `sse.prime`, surfacing as a 500. Fixed, and confirmed by running the suite
both ways: 7 failed before, 12 pass after. A skipped test is not a passing test, and
this repository's own history says so twice already.

**The `Thinking` checkbox could not turn thinking on.** The request omitted `think`
when the box was checked, on the reasoning that `true` should not override the
deployment default. That is backwards: with `OLLAMA_THINKING=false` the panel drew
the box checked, sent nothing, the server applied `false`, and the control displayed
the opposite of what happened with no way to correct it. Both positions are now sent.
Safe, because the asymmetry is one layer lower: the adapter maps `thinking=True` to
sending *no* `think` field, so a caller's `true` never reaches a runtime as a demand.

**Refuted: context shifting is not why the model fails to converge.** The proposal was
that `num_ctx` is never sent, Ollama therefore serves a 4096-token window, and a
16384-token generation silently discards its own earlier reasoning — which would
explain the re-derivation the analysis above describes. It is a good hypothesis and
the logs do not support it: `n_ctx_slot = 202752` on every load, `truncated = 0` on
every release including the 23,632-token run (`n_tokens = 23746`), and **zero**
context-shift events in the entire log. Ollama reads this model's own context length
rather than a default. The non-convergence stands as measured.

What the observation does leave standing is narrower and worth keeping: the platform
does not *control* the window, so Ollama sizes the KV cache from the model rather
than from `MAX_CONTEXT_LENGTH`, which is only a character bound on input. That is
accounted for empirically today — the 38.3 GB resident figure includes it — but it is
unbudgeted, and `n_slots = 1` is the only reason four concurrent requests do not
multiply it.

### The first thinking model went in, and three layers written for non-thinking models all failed at once

**GLM-4.7-Flash replaced nothing — it joined.** `glm-4.7-flash:q8_0` (31.8 GB, the
official Ollama library) registered as `glm47-flash`, downloaded and loaded in 14m25s
end to end, and took `chat` at priority 200 with `qwen7b` left at 100 as a fallback.
It is the best GLM this machine can hold: the flagship GLM-4.7's smallest quantisation
on HuggingFace is 84.5 GB at one bit, above the 64 GB of physical memory, and Flash's
own `bf16` at 59.9 GB would be refused by the budget (51.2 GB) and rightly so.

**The measurements.** `ollama ps` reports 38.3 GB resident, all of it VRAM — 6.5 GB
above the 32 GB registered, so the KV cache and overhead run about 20% of weights
here, comfortably inside the 20% headroom. 60.8 tok/s generating, 117.9 tok/s prompt
eval, against qwen2.5:7b's 91.7 — a model four times the size at two thirds the
speed, which is what the MoE shape buys. Wired memory 40.6 GB of 64, swap untouched.

**Then the first hard question came back as a 500, and the cause ran through three
layers, none of which knew thinking models existed.**

1. **The adapter dropped the reasoning.** Ollama puts a thinking model's deliberation
   in `message.thinking` and leaves `message.content` empty until it is finished.
   `ollama_adapter.py` read `content` only, so for 93 seconds it yielded no chunk at
   all. A trivial question ("explain caching in one sentence") spends 800+ tokens
   thinking; the three-guards logic puzzle spent all 4096 and produced no answer.
2. **`sse.prime` pulls the first chunk before choosing a status code.** That is
   deliberate and correct — it is what lets a routing failure be a 503 instead of a
   200 containing an error frame — but combined with (1) it meant the response headers
   were not sent for the whole generation.
3. **Next.js applies a 30-second socket timeout to a proxied request.**
   `server/lib/router-utils/proxy-request.js` resolves `proxyTimeout || 30000`, and
   `/admin/*` is proxied by `middleware.ts` with `NextResponse.rewrite`. It cut the
   idle socket at 30 seconds exactly; the browser saw a 500 and **the backend logged
   nothing**, because the reset happened between the two containers.

The earlier question in the same session — "who are you" — survived at **29.2 seconds**.
The failure was 0.8 seconds of margin away from never being noticed.

**What was changed.** `CompletionChunk` gained a `reasoning` field, kept separate from
`delta` at every layer: merging them would put the model's scratch work into the answer
and then into the history a client sends back. It reaches the wire as `reasoning_content`
inside the delta, the spelling DeepSeek and vLLM already use, so an OpenAI client that
does not know it ignores an unrecognised key. The chat panel shows it in a block —
which later the same day became a one-line ticker, see below — and
`use-chat-stream` neither replays it as history nor sends the empty `content` of a turn
that produced only reasoning. `proxyTimeout` is now 660 s, above the backend's own
600-second generation deadline, so the guardrail that fires is the one that can report
a reason. `MAX_TOKENS_CEILING` went 4096 → 8192, since `eval_count` counts thinking.

**Three things worth keeping separate from the fix.**

*`think: true` is unsendable on a mixed registry.* Ollama answers `"qwen2.5:7b" does
not support thinking` and fails the request. So the operator switch is one-directional
by necessity: `OLLAMA_THINKING=false` sends `think: false`, and `true` sends no field
at all. There is no way to ask for thinking globally while a non-thinking model is
registered.

This is about what reaches Ollama, not about what a caller may send. The API accepts
`think: true` and the UI sends it — it resolves to "leave the model alone" one layer
down. Conflating the two is what later made a checked box display the opposite of
what it did.

*The ceiling raise was almost inert.* `config.py` carries the default, but `.env`
sets `MAX_TOKENS_CEILING` explicitly and compose loads it, so the code default is
outranked in every real deployment. Changing the default alone would have shipped a
fix that did nothing and tested green. `.env`, `.env.example` and the deployment table
now agree. This is the same shape as the four controls recorded on 2026-07-26 —
designed, written down, marked done, never actually in force.

### Thinking became a per-request choice, after four attempts to make the model converge failed

**Every lever that leaves the decision to the model does nothing.** Measured on the
three-guards puzzle, which GLM-4.7-Flash will not stop reasoning about:

| lever | result |
|---|---|
| ceiling raised to 24576 | 23,632 tokens, 20 minutes, **no answer** |
| `think: "low"` | accepted by Ollama, **behaviour identical to the default** — 8192 tokens, 228.8 s, no answer |
| a prompt-level reasoning budget ("limit deliberation to 800 characters, then answer") | **ignored**, 6144 tokens, no answer |
| `think: false` | **49.5 s, 2532 tokens, a complete answer** |

Graded thinking is a null option here: Ollama takes `low`/`medium`/`high` without
error and nothing changes, so the adapter deliberately does not offer them.

**It is not a loop, which rules out the obvious detector.** The 23,632-token
reasoning was analysed: 93 sentences recur, some five times, but novelty across ten
equal segments decays 100% → 78% → 55% → **39%** rather than to zero. The model is
re-deriving the same sub-cases with variations, not cycling. Anything that cuts on
"it started repeating" would never fire.

**So the switch is per request, and per request is the only place it can live.**
Not per model: `ix_models_node_ref` is unique on (node, runtime, ref), so the same
weights cannot be registered twice under two aliases — and if they could, the memory
budget counts each loaded row's `memory_gb` and would see 64 GB where 32 GB is
resident, refusing the second load. One copy has to serve both kinds of request.

`think` is on both request schemas, an extension on the OpenAI one because there is
no standard field and the alternative is a caller who cannot reach the behaviour at
all. It resolves request-over-default in the use case, which owns the default so no
adapter holds a second copy of it. **Omitted means omitted**: a request with thinking
on sends no `think` field at all rather than `true`, because `true` would pin the
request even after an operator turns the deployment default off, and because Ollama
refuses `true` outright for a model that does not support thinking.

Verified on the deployed stack: `think: false` on the puzzle returns 1424 content
frames, zero reasoning, `stop`, in 30.7 s; omitting the field on an ordinary question
still produces 827 reasoning frames and an answer.

**The guardrails were resized for the actual deployment** — a lab whose peak is four
people. `MAX_CONCURRENT_INFERENCE` 2 → 4, which buys queueing depth rather than
throughput since the GPU serves one generation at a time; `MAX_TOKENS_CEILING`
8192 → 16384, which buys room for long legitimate answers and explicitly does not
rescue the non-converging case. A test that pinned the literal `2` for the slot gauge
was changed to assert the configured value: it failed on a default move and said
nothing about the gauge it was written to protect.

**The wall-clock deadline followed, and it could not move alone.** 600 → 900 s,
because at the measured throughput decay a full 16384-token generation takes roughly
700 seconds and the deadline would have cut a legitimate long answer before its own
ceiling did — a limit firing ahead of the one it backstops reports the wrong reason.

But the frontend's `experimental.proxyTimeout` was deliberately set just above the
old 600, so raising the deadline alone would have handed the cut back to the proxy:
**the same silent reset that started all of this, moved from 30 seconds to 11
minutes.** It went to 960 s with it. The ordering now has a test that reads both
files — `next.config.js` and `.env.example` — and fails if the proxy's value drops
below the deadline's, since a comment in each file cannot enforce an invariant that
spans two languages. It was checked by breaking it: at 300 s the test fails.

`GENERATION_DEADLINE_SECONDS` was also absent from `.env`, `.env.example` and the
deployment table entirely, existing only as a code default — the same
discoverability gap `OLLAMA_THINKING` had. All three now carry it.

**What was decided against.** An automatic fallback — detect reasoning past a budget
with no answer, then silently re-issue with `think: false` — was designed and
dropped. Three reasons, and the second is the one that matters: it generalised from a
single pathological prompt; it trades "no answer" for a *confident wrong* one, since
the `think: false` answer to this puzzle does not actually close the random guard;
and it puts a second upstream request inside one client request, in the function that
owns the concurrency slot, the token ceiling, the deadline and the disconnect
contract. The per-request switch gives the same capability with none of that.

### Deploying that fix cost a Docker Desktop restart, and the restart proved the 2026-07-26 failure repeats

**The build was blocked by something that was not the build.** `docker compose build`
failed on `DeadlineExceeded` loading metadata for `node:22-alpine` and
`ghcr.io/astral-sh/uv` alike, and `docker pull hello-world` produced *no output at
all* — not even `Pulling from`. The daemon was healthy throughout: `docker ps`
answered, containers ran, and a container in the VM fetched a ghcr token and manifest
by hand.

**The cause was `docker-credential-desktop`, which hangs.** Pulling through the daemon
API directly — `curl --unix-socket … POST /images/create` — worked instantly, which
put the fault on the CLI side of the socket. The CLI resolves registry credentials
before issuing the request, so a hung helper produces exactly what was seen: silence
with no output, and a buildkit metadata load that sits until its deadline (buildx
takes its auth from the client over the session, which is why the build failed the
same way). The workaround is a config with no `credsStore`:

```
DOCKER_CONFIG=/tmp/dockercfg DOCKER_HOST="unix://$HOME/.docker/run/docker.sock" \
  docker compose build      # config.json is {}, cli-plugins symlinked from ~/.docker
```

Every image this project needs is public, so no credential is required at all. **This
is worked around, not fixed** — a plain `docker compose build` still hangs.

**One diagnostic step cost a false lead worth recording.** The helper was first probed
with a `kill -9` after 15 seconds, and the wrapper's exit status was read as the
helper's: it looked like a clean exit 0 and the credential path was wrongly cleared.
It was only caught by timing three registries in a loop and having the loop itself
time out. A probe that kills its subject cannot report on it.

**The restart reproduced 2026-07-26 exactly: Docker Desktop came back with zero
containers.** `restart: unless-stopped` restored nothing, which is the same failure
that entry recorded and the reason the reconciler exists. `docker compose up -d`
brought all nine back with port bindings byte-identical to the snapshot taken before
the restart — tailnet addresses included — and `migrate` exited 0. So the repair path
works; what does not work is anything that assumes the platform survives a Docker
restart on its own. **This is now two for two, and it should stop being called a
surprise.**

### The fix, measured against the failure it was written for

| | before | after |
|---|---|---|
| first byte, hard question | 93 s of silence, then a 500 at 30 s | **0.23 s** |
| longest surviving generation | 29.2 s | **228 s**, `finish_reason: length` |
| ordinary question | worked, blank for 29 s | 0.29 s to first byte, 773 reasoning + 32 content frames, `stop` |

Usage rows are written for all of them, thinking tokens included, with `completed=f`
on the truncated ones.

**The ceiling raise did not rescue the question that started this.** Twice, at the
full 8192, GLM-4.7-Flash produced 8192 tokens of reasoning about the three-guards
puzzle and **zero tokens of answer**. 8192 is enough for the model not to be cut off
mid-thought on ordinary work; it is not enough to make this model answer that
question, and no ceiling this machine can afford would be. For that class of prompt
the lever is `OLLAMA_THINKING=false`, which is why the switch exists.

**One failure did not reproduce and is not explained.** The first long run ended, at
6625 chunks and 230 s, with an `no_available_model` error frame instead of a finish
reason — the adapter saw the upstream stream end without a `done` event, while Ollama
logged that same request as 200 in 3m50s having generated its full 8192. The
identical request 20 minutes later completed cleanly, and a direct 8192-token stream
from Ollama ends with a proper `done_reason: length`, so Ollama is not the suspect.
Worth noting for the next occurrence: the adapter's two failure modes — an `error`
event mid-stream, and a stream that ends without `done` — both raise
`NoAvailableModelError` and **neither logs anything**, so both reach the operator as
"No model is currently available", which points at routing policies rather than at
the transport. Neither is distinguishable after the fact. That is the thing to fix
before trying to diagnose it again.

---

### A Claude Code session left running through screen-off was reachable again over a remote login, memory intact

**This closes the loop the 2026-07-26 remote-operability audit opened.** That entry established the
machine boots and recovers unattended; the open question was whether a long-lived interactive
session — specifically a Claude Code CLI session, left running with the display off rather than
the machine asleep — would still be there, and still be itself, when reached again from off-site.
It was. The session had been started on 2026-07-26 with the screen turned off (not full system
sleep, which would have suspended the process); today's remote login reconnected to it, and it
answered with its prior conversation memory recalled correctly rather than starting cold.

**What this does and does not prove.** It confirms display-off is a safe mode to leave an
interactive Claude Code session in on this machine, and that a remote login is a working way back
in — consistent with the SSH posture §11 already settled (tailnet-only, no second listener). It
does not test full system sleep, which suspends processes and would be expected to behave
differently, and it was one session over roughly a day, not a stress test of duration or of
concurrent sessions.

---

## 2026-07-26

### Auditing "can this be run entirely remotely" found one real hole and one contradiction between two files

**The question was whether the project can now be worked on entirely from off-site, and the
answer is yes with one exception that had been sitting unmeasured on a checklist.** What holds:
FileVault off, so a boot needs nobody at the screen; automatic login as `rcslmac1`, so the GUI
session returns; Docker Desktop `AutoStart: true`, which needs that session; the Tailscale node
key set to never expire, so the host cannot quietly fall off the tailnet; `sleep 0` and
`womp 1`; and both reconciler and health-check daemons installed, with both repair paths now
exercised at boot. The 21:51 reboot is the end-to-end evidence: the platform came back 51
seconds in with nobody at the machine.

**The hole was `pmset autorestart 0`.** Runbook §1's checklist has asked for "starts up again
after a power failure" since the beginning and nothing had ever read the value back. On a
machine with no out-of-band management that setting is the difference between a power blip and
a trip to the building: `autorestart 1` now, verified. Setting it also flipped
`autorestartatconnect` from 1 to 0, which is a laptop key with no effect on a desktop —
recorded only because it was measured.

**The contradiction: runbook §1 said turn macOS Remote Login on, security.md §11 says keep it
off, and §11 is right.** The runbook item still carried the pre-Tailscale instruction — enable
Remote Login before unplugging the monitor, harden it later per §11 — while §11 had since
decided the requirement to listen only on the Tailscale interface is met by *not running a
second SSH server at all*, since macOS Remote Login binds every interface including the LAN and
accepts passwords. Following the runbook would have undone the decision. The old item did name
a real problem — after Part 1 there is no way in yet — but the fix is ordering, not a daemon:
do not unplug the monitor until Part 4's Tailscale SSH has actually connected once. Both items
are now marked done with the verification §11 specifies, which was measured today and holds:
nothing listening on `127.0.0.1:22`, `com.openssh.sshd => disabled`, tailnet SSH working.

**This is the third time the two derived files have drifted from this one**, and the first two
were caught the same way — by checking a claim against the machine rather than against another
document.

---

### The container bring-up path ran 51 seconds into the boot, and that same boot falsified a number the reboot argument rested on

**§1.1b was run and it passed on the first attempt.** The script refused nothing, stopped the
nine services at 21:50:38, the machine was rebooted by hand, and the reconciler brought the
whole platform up on the boot that followed. The four expected lines came out in order and
nothing else did. The row that seven natural boots and one address injection could not fill is
filled.

| Time | Event |
|---|---|
| 21:50:37 | preconditions pass; the guard reads the *previous* boot's reconcile correctly (`ran 7s into this boot`) |
| 21:50:38 | nine services stopped, read back and confirmed |
| 21:51:23 | boot (`kern.boottime`) |
| 21:51:30 | `reconcile starting` — 7 seconds into the boot, the same as §1.1a |
| 21:51:45 | `tailnet address present` (15s wait) |
| 21:51:46 | `docker daemon responding` |
| **21:52:01** | **`not running:` all nine → `docker did not restore the stack; bringing it up`** |
| **21:52:14** | **`stack up: all expected services running` → `all published bindings intact`** |

**Boot to recovered: 51 seconds.** Script to recovered, which is the real outage window: 1
minute 36 seconds. §1.1a's was 2m55s from boot, and that comparison is the point of the whole
exercise — this fault is cheaper in every dimension including the one that matters to whoever
is using the platform.

**Docker Desktop restored exactly zero of the nine, which is the mechanism the test rides on.**
`restart: unless-stopped` promises this and the compose file has said so all along, but until
now nothing had watched the *unless* survive a reboot on this machine. It did, completely: the
missing set was all nine on the first sample and all nine on the last.

**The settle loop hit its structural floor, and that retires a worry §1.1a raised.** It took 15
seconds — four samples with three five-second sleeps between them, which is the minimum the loop
can take and still be the loop. §1.1a measured 27 seconds for the same code against a healthy
boot's 16, and the open question was whether the loop is expensive at boot. It is not: what was
expensive was inspecting a *running* stack while everything else on the machine was moving.
Against an empty one the four `docker compose ps` calls cost nothing measurable. The same
contrast shows in the scan — 40 seconds in §1.1a, absent here because there were no running
containers to sweep.

**Of the 44 seconds the reconciler spent, 31 were waiting and 13 were working**: 15s for the
address, 1s for the daemon, 15s for the settle loop, 13s for `up -d` to take nine services from
nothing to all-running including the postgres health gate and `migrate` running to `Exited (0)`.
The one hand test of this path took 16 seconds for a single already-imaged service, essentially
all of it the settle loop; the bring-up itself is what boot conditions were never measured
against, and it costs 13 seconds.

**The last line was `all published bindings intact`, exactly as predicted before the run.** No
`can't assign requested address` appears in the Docker backend log for this boot — the newest
such lines are still §1.1a's trio at 21:02:56 — because the reconciler waits for the address
first, so by the time `up -d` ran the address had been on the interface for 16 seconds and the
forwards were built correctly the first time. The two injectors test two paths and neither
substitutes for the other; this run is the evidence for that rather than the assertion of it.

**The monitor stayed silent, and only half of that was by design.** Boot grace covered
21:51:23–21:55:23, so the `RunAtLoad` run was suppressed and the 51-second recovery finished
well inside it; the first real check was 21:56:30, which is also the worst-case detection
latency had the reconciler failed — about five minutes, not the ten quoted for §1.1a, because a
240-second grace against a 300-second interval suppresses exactly one run. But the platform was
also down for the 45 seconds *before* the reboot, and nothing guarded that: the previous boot's
schedule had fired at 21:47:43 and would have fired next at 21:52:43, by which time the machine
was gone. **That was luck of timing, not a control.** Run the script a minute later in the
interval and the monitor mails a true `failing` — correctly, since the platform really is down.
The runbook now says so; it is not a failure of the test.

**One accidental confirmation, recorded because it could otherwise be misread.** The full check
was run by hand at 21:53:29, 126 seconds into the boot, and exited 0 having checked nothing —
it took the boot-grace path and rewrote the state file, which is what that path is for. It was
rerun at 21:56:35, outside the grace, and *that* is the pass: exit 0, nine services, six
bindings requested-equals-actual, six entrances 200, no state change. An `exit 0` inside the
grace window is not evidence about the platform.

**The boot also settled an open prediction that had nothing to do with why it was run, and half of it was wrong.** The netmap alternation model predicted the next boot would miss the disk cache and take 9 seconds to bring the address up. It missed the cache — the fifth consecutive confirmed prediction, which is where load-without-rewrite stops being provisional — and the address took **11 seconds**, not 9 (`tailscaled` 21:51:30, `peerapi` on 100.108.250.62 at 21:51:41). Cache-miss boots therefore measure 9, 9, 9, 11, 17, not a constant, and the runbook's "no spread at all" was three samples mistaken for a value. That number was load-bearing: the argument for injecting rather than rebooting ran `10.3 − 9 = 1.3s` and concluded the margin *cannot* go negative. It can — though the honest version of the correction is weaker than the arithmetic suggests, because `10.3 − 11` subtracts the extremes of two distributions measured on different boots, and this boot produced no margin observation at all since Docker bound nothing. What survives: the margin distribution is wider than three samples made it look, 16:45's 17-second address is the top of that distribution rather than a retired outlier, and "rebooting cannot lose" was overstated. The conclusion is unchanged and better grounded — inject because a 90-second hold is repeatable, not because rebooting is guaranteed to win.

**And the reconciler is not a stopwatch.** Its log says the address took 15 seconds; it samples every 5. Both this and §1.1a's off-by-one were the same mistake in different clothes — reading a number off an instrument built for a different question. Address timings belong to `tailscaled`'s log.

**What this does not establish is unchanged from what was written before it ran.** It does not
show Docker Desktop's restore failing on its own — that happened once, after the macOS 26.5.2
update, and why is still unknown; the state is reproduced, not the cause. And it does not
replace round two, which tests the update reboot as a whole: automatic login, `pmset
autorestart`, and what Docker does afterwards. None of those were touched.

---

### The second repair path turned out to be injectable too, and the claim that it was not was mine

**Yesterday's entry and three other files said the container bring-up path could only be
filled by rerunning round two, because the injector "withholds the address, not Docker
Desktop's restore". The first half of that is true and the conclusion does not follow.** The
mechanism was sitting in `docker-compose.yml` the whole time: every long-lived service carries
`restart: unless-stopped`, and the *unless* is the entire lever — a container that was
explicitly stopped is not restored when the daemon comes back. Stop the stack, reboot, and
Docker Desktop faces nine containers it will deliberately leave alone. The reconciler then
wakes to exactly what the 19:09 boot left it: everything present, nothing running.

**`launchd/stop-stack-once.sh` and runbook §1.1b.** It is a hand-run script with no plist, and
that absence is deliberate: §1.1a needed a boot-time job because its fault had to be injected
*during* boot, whereas this fault is set beforehand and simply persists, so a plist would be a
moving part with nothing to do.

**It is an order of magnitude cheaper than §1.1a, which is the point.** The host stays on the
tailnet for the whole window — SSH, `tailscale serve`, everything — so no person has to be at
the machine and a failed test is recoverable from anywhere with `docker compose up -d`. The
cost is that the platform is down from the moment it runs until the next boot recovers it.

**Most of the script is refusals, and one of them is the reason the rest can be trusted.** It
declines to run if §1.1a's plist is installed (both faults at once blocks each one's recovery
path), if the nine services are not all running, if any requested binding is already unbound,
if the reconciler's plist is missing — and, the one that matters, **if the newest
`reconcile starting` in the log is older than the current boot**. A plist on disk is a
necessary condition that proves nothing about whether launchd loaded it, and rebooting with
the stack down and nothing scheduled to raise it is the single way this injection becomes an
outage rather than a test. The log answers the question actually being asked — did this daemon
run on *this* boot — and that is evidence rather than configuration. After stopping it reads
the result back, because a half-stopped stack would have Docker restoring some containers and
the reconciler meeting a set that is neither empty nor complete: a fault nobody designed.

**Eight branches were run rather than read**, against the live platform without ever stopping
it: all five refusals fired, the healthy-precondition path passed, the success path printed
its instructions, and the half-stopped guard caught a stop that had been replaced by a no-op.
The one branch not separately exercised is the already-unbound refusal, which is the same six
lines as in `check-platform-health.sh` and `reconcile-port-bindings.sh`.

**What it will and will not prove, stated before it is run so the result cannot be read
generously.** It will show the reconciler bringing the platform up at boot, with everything
moving at once — the part a hand test cannot reproduce, and §1.1a measured how much that
matters: the same code that settles in 16 seconds on a healthy boot took 27, and a scan that
finishes inside a second took 40. It will *not* show that Docker Desktop's restore fails on
its own; that happened once, after the macOS 26.5.2 update, and why is still unknown. It
reproduces the state, not the cause — §1.1a's limit exactly. And it does not replace round
two, which tests the update reboot as a whole: automatic login, `pmset autorestart`, and what
Docker does afterwards. None of those are touched here. The expected outcome is the third row
and only the third row: `all published bindings intact`, not `OK: all bindings restored`,
because the reconciler waits for the address before it runs `up -d`.

---

### The injected boot filled the row seven boots could not, and settled two things the last entry left open

**§1.1a was run and it passed on the first attempt.** The plist went in, the machine
rebooted at 21:02:36, and the injector deleted its own plist and held `tailscaled` down
from 21:02:43. Docker Desktop bound at **21:02:56** — seventy-eight seconds before the
address existed — and failed on exactly the three services that name it, `:8000`, `:3001`
and `:8002`, no more and no fewer. The reconciler waited the hold out, saw the address at
21:04:14 (one second after the release), found all three bindings dropped, and logged
`recreating: admin-public frontend-public gateway` → **`OK: all bindings restored` at
21:05:31**. Afterwards: nine services running with `migrate` at `Exited (0)`, all six
requested bindings equal to actual, all six entrances at 200, Ollama on loopback and
nothing on the tailnet address, and the plist gone. The row that stayed blank for seven
boots is filled, and it is filled with manufactured weather rather than a boot that lost
the race on its own — that second claim still rests only on 16:45.

**The margin was −78 seconds against a natural ceiling of +1.3.** That is the ninety-second
hold doing what it was sized to do, sixty times over, and it is the whole reason the row
could be filled at all.

**The repair costs about twice at boot what it costs by hand, which is the part the hand
test could never have told us.** The named-set precondition took 27 seconds against a
stable 16 on four healthy boots; the binding scan took 40, with twelve seconds between each
of the three detections, where on a healthy boot the identical scan finishes inside one
second. `broken_services()` has no sleep in it, so that is pure `docker inspect` latency on
a machine that is still busy. Of the 77 seconds from address to restored, more than half
was spent looking rather than repairing. "Its cost is stable at sixteen seconds" was a
statement about healthy boots only.

**The boot grace suppressed a real failure for the first time, and it was right to.** For
the 2m35s between 21:02:56 and 21:05:31 the platform was genuinely broken and no mail went
out, because all of it fell inside the window the reconciler owns. That is precisely the
behaviour the grace was written for, and it had never once been exercised: before 20:45 the
greedy `sed` meant it could not fire at all, and after the fix there had been no failing
boot. Had the repair failed, the 21:07:43 run would have caught it — worst-case detection
is ten minutes.

**And the fix that was "tested in parts" is now tested whole — but not by the evidence the
last entry said to look for.** That entry predicted "a state mtime within seconds of boot
and no mail". The mtime half of that is unusable: `StartInterval` counts from load either
way, so the first scheduled write lands at load+300 whether `RunAtLoad` fired or not, and it
overwrites the boot-time write. The unified log does separate them — four spawn/exit pairs,
21:02:43.356→.473, 21:07:43.678→44.286, 21:12:44.309→.838, 21:17:44.858→45.386. The first
ran at an uptime of seven seconds and finished in **117 milliseconds** against 528–608ms for
the three full-path runs, and the full path cannot be done in a tenth of a second: six curl
probes, a `docker info`, a `docker compose ps` and ten `docker inspect` calls. Exit 0, no log
line, no mail. `launchctl print`'s `runs` counter was the first instrument reached for and it
is the wrong one — it carries no timestamp, so `runs = 3` cannot be distinguished from
`RunAtLoad` plus two intervals without separately recovering when it was read.

**The 240-second grace turned out to have been chosen with seven seconds to spare.** The
first scheduled run of that boot fired at an uptime of 307 seconds. At the old grace of 300
it would have evaluated by seven seconds; eight seconds more launchd latency on the same
healthy machine and it would have been skipped, pushing the first real check to ten minutes.
The coin flip that argument was built on has now been observed landing, close to its edge.

**A check that came back clean was a false negative, for the third time in one day and the
second time from log rotation.** `grep "can't assign requested address"` over
`com.docker.backend.log` returned nothing, which reads as "the injection did not work". The
three lines are in `com.docker.backend.log.20260726-210850.988`: Docker rotated the file at
21:08:50 and the grep ran around 21:09. The runbook now specifies the glob. This is the same
shape as the 20:12:32 rotation noted in the previous entry and as `tailscale status --json`
answering a question it had no field for — a check whose scope is smaller than it looks,
read as a statement about everything.

**Finally, the netmap cache model took its first exception, from the rehearsal rather than
the test.** Before injecting, `tailscaled` was restarted by hand to confirm §1.1a's recovery
command works. It came up at 21:00:27 on `netmap cache is not available` — thirty-one minutes
after the 20:29:15 write that the model says should have been waiting for it. A TTL does not
explain it, because 18:08:23 wrote and 19:10:00 loaded sixty-one minutes later. The one clean
distinction is that this was a daemon restart inside a running session and every recorded hit
followed a reboot; so either the model is wrong or restart and boot are different events for
this cache, each with one observation. Until they are separated the alternation applies to
boots only. The standing prediction — that the boot after 20:29 would be fast — was never
tested, because the injector held `tailscaled` down through it; the daemon that started at
21:04:13 loaded the 21:00:30 cache and logged no rewrite, making load-without-rewrite four
observations and predicting a **cache miss on the next boot**.

**The injector misreported its own measurement, and that is now fixed.** It logged
`tailnet address ... is back within 10s of the release` for an address the reconciler had
independently seen one second after the release. It printed the loop counter times five,
which charges the sleep *following* each check to the check itself — five seconds of
off-by-one on top of five seconds of polling granularity. A tool whose entire purpose is
measurement, wrong on the one line of it that is a number. It now measures elapsed seconds
and polls every second; both branches, address-present and address-absent, were run rather
than read.

**Writing that count down found the runbook had been over-reporting it.** §1.1 said "round
one has passed six times" in three places. Six is the number of *attempts* — 16:45, 17:21,
18:08, 19:43, 20:24, 20:29 — and the first of them is the failure the whole reconciler exists
because of, so it cannot also be a pass. Round one has passed **five** times out of six. The
file could already have caught itself: it labels 19:43 "round one's fourth", which only adds
up if 16:45 was the first. The error is small and it runs in the direction that flatters the
record, which is the direction worth being suspicious of.

**What is still blank.** The container bring-up path has never run at boot, and the injector
cannot produce it — it withholds the address, not Docker Desktop's restore. That row needs
round two rerun. Round one stands at five passes in six attempts; round two remains one run,
failed. The injected boot is not a round-one pass: it is a boot deliberately made to fail,
which then recovered.

---

### Two more boots proved the lever cannot work, and the liveness record had a hole where it is read

**Round one was run a fifth and sixth time, back to back, and both passed on the
first outcome.** 20:24:21 and 20:28:58, 4m37s apart, hands off both times. Nine
services running with `migrate` at `Exited (0)`, all six requested bindings equal
to actual, all six entrances at 200, Ollama on `127.0.0.1:11434` and nothing on
the tailnet address, `all expected services running` → `all published bindings
intact` on both. The named-set precondition decided in sixteen seconds both times,
the same as 19:43 — its cost is stable.

**This was the runbook's own lever, pulled deliberately, and it failed.** The
instruction was to reboot twice and watch the second, because a boot that loads
the netmap cache does not rewrite it and hands the next boot the slow path. The
mechanism worked exactly as described: 20:29 found no cache, waited 9 seconds for
the address, and its margin fell from 8.3 seconds to 1.4. It still won.

| boot | `tailscaled` start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |
| 20:24, passed | 20:24:22 | 20:24:24 (+2s, cache hit) | 20:24:32.3 | **+8.3s** |
| 20:29, passed | 20:29:06 | 20:29:15 (+9s, cache miss) | 20:29:16.4 | **+1.4s** |

**And the reason it will keep winning is now arithmetic rather than hope.** The
claim that Docker is the stable side at 11 to 14 seconds was the small sample
talking: the six boots where it bound are 14.0, 11.0, 11.0, 11.7, **10.3**, **10.4**
seconds, and the two lowest are the two newest. Cache-miss boots, meanwhile, put
the address up at exactly 9 seconds — three observations, zero spread. `10.3 − 9`
is the entire protection, so the lever's ceiling is a 1.3-second margin and it
cannot go negative. Only 16:45 ever lost, on a 17-second address that has not
recurred in six boots. **Rebooting repeatedly is not a test, it is waiting for
weather.**

**The netmap model made its third and fourth predictions and both held, so the
alternation is now seven boots with no exception.** 19:43 wrote, so 20:24 loaded
(+2s) and logged no write in its session; 20:24 loaded without rewriting, so
20:29 missed, waited 9 seconds and wrote at 20:29:15. Load-without-rewrite rests
on three observations now (17:21, 19:09, 20:24). Next boot is a fast one.

**So the blank row gets filled by injecting the fault.**
`launchd/delay-tailscaled-once.sh` and its plist hold `tailscaled` down for 90
seconds at boot — six times the margin Docker needs to lose by — so Docker binds
before the address exists and the reconciler has to walk the binding repair path
with everything else at boot moving at the same time, which is the part a hand
test cannot reproduce. It is a test tool and is deliberately not in the runbook's
install list. Two properties are the ones that matter: it deletes its own plist as
its very first action, before anything that can fail, so whatever happens it
affects exactly one boot; and it uses `launchctl bootout`/`bootstrap` rather than
`tailscale down`/`up`, because `up` can reset prefs not named on the command line
and the prefs here include Tailscale SSH — the remote access path. The residual
risk is stated rather than engineered away: the release runs from a trap covering
EXIT, INT, TERM and HUP but not SIGKILL, and during the hold the host is off the
tailnet entirely, so this is a with-a-person-at-the-machine procedure. Runbook
§1.1a.

**Then the monitor's own liveness record turned out to have a hole exactly where
the runbook reads it.** The state file's mtime is the only evidence the daemon is
alive — the log is events-only — and the criterion is "under five minutes old".
With the plist at `RunAtLoad=false` and a 300-second interval, *no run happened in
the first five minutes of a boot*, so the freshest mtime in that window predated
the boot: three to eight minutes old, depending only on where the reboot fell in
the previous interval, against a five-minute criterion. The runbook tells the
operator to wait two or three minutes after a reboot and then check exactly this.
These two reboots demonstrate it: no run happened across either of them, and the
20:26 check passed with thirteen seconds of margin, by luck. This is the second
wrong version of this one criterion — the first said "mtime within ten minutes of
boot" — and both were wrong in the same direction, describing when the file gets
written rather than what the reader needs to know.

`RunAtLoad` is now true, and the boot-time run is suppressed by the boot grace,
which rewrites the state file verbatim and exits: the signature is unchanged
because nothing was checked, so it cannot mail, and the only thing it updates is
the one thing it is entitled to claim — *this ran, and deliberately asserted
nothing*. If the file did not exist it writes the empty-signature sentinel, so the
first real run still mails `baseline` and not a false `recovered`.

**The boot grace it now relies on had never once fired.** It parsed
`sysctl -n kern.boottime` — `{ sec = 1785068938, usec = 428375 } ...` — with
`s/.*sec = \([0-9]*\).*/\1/`, whose leading `.*` is greedy and matched through to
`usec`. `BOOT_SEC` was the microseconds field, uptime came out as the whole Unix
epoch, and the comparison could only ever answer "not in grace". **That is the
fourth instance of this log's recurring defect, and this time it was inside the
check whose entire job was to have two answers.** It also put a nine-digit
`uptime` line in every alert mail sent before the fix, including the 19:15 one.
`RunAtLoad=false` had been load-bearing by accident: it was the only thing
actually suppressing the boot-time run. The pattern is anchored at the start of
the line now, and the grace is 240 rather than 300 so it sits clearly below the
interval instead of on the boundary, where whether the first scheduled run of a
boot evaluated or was skipped came down to how many seconds launchd took to load
the job — a coin flip deciding whether the first real check is at five minutes or
ten.

All three paths were run rather than read: the grace path rewrites the file
byte-identically with a fresh mtime and exits 0 silently; the normal path still
evaluates fully and mails nothing when the signature is unchanged; and with no
state file at all the grace path writes the `\n0\n` sentinel that reads back as
"no previous state".

**Two of those three were forced rather than observed, and the distinction is the
same one §1.1 makes about the reconciler.** The grace path was exercised by running
a copy with `BOOT_GRACE` raised past the current uptime, because the machine had
been up for twenty minutes and there is no way to be five minutes into a boot
without booting. The reload at 20:53 proved the other half: `bootstrap` fired the
`RunAtLoad` run, it wrote the state file, and — uptime being well past 240 seconds
— it correctly took the *full* path and mailed nothing. **What has not been
observed is the two acting together at a real boot**: `RunAtLoad` firing inside the
grace window, taking the silent rewrite, and the first scheduled run five minutes
later evaluating for real. The prediction is a state mtime within seconds of boot
and no mail, and the next reboot for any other reason will settle it. Until then
this is a fix that has been tested in parts.

**One check of the operator's own turned out to be scoped smaller than it looked.**
`grep "can't assign requested address"` over `com.docker.backend.log` came back
empty, which is true and covers only these two boots — Docker rotated that log at
20:12:32. The original failure's three lines are in
`com.docker.backend.log.20260726-172120.413` at 08:45:29Z, for `:8000`, `:3001`
and `:8002`, which is the same three services the injector above is expected to
break. Reading that grep as "this has never happened" would be the same shape of
error as everything else on this page.

**Six boots of round one, one failed round two, and the two outcomes worth having
are still blank.** What changed is that one of them now has a procedure that can
produce it instead of a lever that cannot, and the other — the container-restore
path — still needs round two rerun, which is the most overdue test on the machine:
the 19:09 boot is the reason that code exists and nothing has exercised it at boot.

### The fifth boot passed and proved nothing, and the two checks written that day could each only say yes

**Round one was run a fourth time and passed.** Plain `sudo reboot` at 19:42:59,
machine back at 19:43:20, hands off. Nine services running with `migrate` at
`Exited (0)`, all six requested bindings equal to actual, all six entrances at
200, Ollama answering on `127.0.0.1:11434` and nothing on the tailnet address.
The reconcile log reads `all expected services running` → `all published bindings
intact`, which is the **first** of the runbook's six outcomes: Docker restored the
stack itself and `tailscaled` won the race, so neither repair path was walked.
**Five boots in, both of the outcomes worth having are still blank.**

It did prove one thing that had no evidence behind it an hour earlier: the
rewritten reconciler is what ran. The fix was committed at 19:41 (`4d8401c`) and
the daemon executes the file in the working tree, so 19:43 is the first boot on
which the named-set precondition, and not the count, decided anything. It decided
correctly and cheaply — `docker daemon responding` at 19:43:39, the container set
already complete, `all expected services running` at 19:43:55, sixteen seconds,
which is three stable samples and no more.

**The margin table gains a fifth row, and the netmap prediction held a second
time — this time stated in advance.**

| boot | `tailscaled` engine start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |
| 19:09, failed for another reason | 19:09:59 | 19:10:00 (+1s) | *never* | *no race* |
| 19:43, passed | 19:43:28 | 19:43:37 (+9s) | 19:43:39.7 | **+2.7s** |

19:10 loaded the cache and never rewrote it; 19:43 found `netmap cache is not
available` and wrote one at 19:43:38. **The rule that caches do not chain now
rests on two observed load-without-write rather than one**, and the prediction it
makes — the boot after a fast one is a slow one — was written down before this
boot and held. Docker remains the stable side: 11.7 seconds from `tailscaled`
start to the first `exposer.Add`, inside the same 11-to-14 band as the other four.

**The lever this hands the acceptance test is weaker than it read.** The runbook
says to reboot twice and watch the second, because the second has no cache. Both
cache-miss boots on record now pass by roughly two seconds (18:08 +2s, 19:43
+2.7s); the 17-second address that produced the one real failure has not recurred.
It is still the best available bet and it is not a reliable one — a +2s pass is
what "the slow kind" now means.

**The monitor's first real alert cycle is on the record, and it belongs to the
19:10 failure rather than to a drill.** `failing` at 19:14:59, `recovered` at
19:30:03, both mailed. What sat between them was a person: `migrate`'s `StartedAt`
is 19:28:26, which is a hand-run `docker compose up -d` and nothing else. So the
recovery on record is a human's, the reconciler's stack-up path was written after
it, and five boots in that path has still never been walked by a boot. The monitor
is the only part of the chain that has now been exercised end to end by a real
failure rather than by a rehearsal.

**Then both of the day's new checks were tested rather than read, and both had a
defect of the shape this document keeps recording.**

**1. `check-platform-health.sh` counted paused and restarting containers as
running.** It asked `docker compose ps --format '{{.Service}}'`, and `--all` is
documented as adding *stopped* containers — so paused, restarting and created ones
were in the answer all along. Not academic on this host: Docker Desktop's Resource
Saver pauses containers, and the 19:04:18 shutdown path issued an `/unpause`,
which is how we know it had. `postgres`, `redis` and `prometheus` have no probe in
check 6, so check 4 is their only coverage, and paused they would have been silent
in the one place that could have said so. Demonstrated rather than argued: with
`prometheus` paused, the old script exits 0 with the state file still reading `OK`
and sends nothing; the fixed script logs `failing: services,` at 20:01:29 and
mailed at 20:01:32. Unpaused, `recovered: OK` at 20:01:48, mailed at 20:01:51. The
fix is `--services --status running`, which is the question the reconciler was
already asking; the two now agree.

**2. The reconciler's read-back could have no time left to read anything back.**
`DEADLINE` is absolute, and one of the two ways into the repair branch is the
settle loop timing out — the 19:10 boot's exact path. Reached that way, the loop
that verifies `up -d` worked has zero budget, so the first sample, taken in the
gap between `up -d` returning and Compose reporting the container running, prints
`FATAL: still not running` about a stack that is starting. Shown with fault
injection, one lagging sample in a copy of the script: without the fix,
`FATAL: still not running after up -d: grafana` in the *same second* as
`Container rcsl-ai-nexus-grafana-1 Started`, exit 1. With it, one retry and
`stack up: all expected services running`, exit 0. The branch now takes 120
seconds of its own rather than the remainder of a budget that may be spent.

Both fixes are live rather than merely committed, and that was checked rather than
assumed: the plists name the files in the working tree, and the health daemon's
20:03:29 tick ran the fixed script under launchd — `OK`, no mail, nothing in the
log, which is what a quiet tick is supposed to look like.

**The stack-up path itself was walked by hand under normal timing too**, which is
the closest thing to evidence available without a boot that needs it:
`docker compose stop grafana`, then `not running: grafana` →
`docker did not restore the stack; bringing it up` → `stack up: all expected
services running` → `all published bindings intact`, sixteen seconds, exit 0.
**And it restored the binding without recreating anything** — afterwards
`127.0.0.1:3002` requested equals actual and `/login` returns 200. That refines
the recreate rule rather than contradicting it: `up -d` is a no-op against a
container that is already *running* with a stale forwarding table, which is the
case that needs `--force-recreate`; against a *stopped* container it starts it,
and the forward is established then. The two failure modes need the two different
repairs, which is why the script has both.

**What is still unproven, unchanged by all of this.** `OK: all bindings restored`
has never been produced by a boot, and neither has `docker did not restore the
stack; bringing it up`. Both now have hand tests and neither has a boot test, and
a hand test cannot exercise the thing that makes boot hard, which is that nothing
is holding still. One more thing worth knowing before the next run: a hand run of
either script writes to the terminal, not to the log — the redirect lives in the
plist — so `nexus-health.log` legitimately contains no trace of the drills above,
and the state file and the mail are their record.

### Round two, the OS update: nothing brought the containers back, and the reconciler called that a success

**Round two was run — the macOS 26.5.2 update — and it failed.** Legitimately run:
round one had passed three times, which is the gate the runbook sets. Shutdown
19:04:18, machine back at 19:08:46, `macOS 26.5.2` recorded in
`/Library/Receipts/InstallHistory.plist` at 19:09:47, hands off. `docker compose
ps` was empty. Not a dropped port forward this time: no containers at all.

**The two checks round two exists for both passed.** `autoLoginUser` was still
`rcslmac1` and `pmset autorestart` still 1 — the reset that has precedent did not
happen. The failure was somewhere nobody had thought to look, which is the
argument for running the test rather than reasoning about it.

**They were not broken.** All ten are present under `docker compose ps -a`, each
`Exited (0)` from a clean shutdown SIGTERM at 19:04:18, `restart: unless-stopped`
still on every one of them. Docker Desktop simply did not restore them. The engine
reported `running` at 19:10:37 and the backend log has **not one `exposer.Add`**
after it — against a full nine at the same point in the 18:08 boot. Two boots kept
the promise, this one did not. `restart: unless-stopped` is a promise the Docker
daemon makes, and this is the entry that records it is not a property of the
machine.

**Nothing on this host was responsible for the stack being up.** That is the real
finding, and it was true all day without anyone noticing, because Docker had
always happened to do it. The reconciler's repair path fires only for containers
that are *already running* with an empty `NetworkSettings.Ports`; `docker compose
up` appears nowhere in launchd. The whole recovery chain was one layer thinner
than it read.

**And the reconciler reported success while standing in the middle of it.** Its
third precondition waits for the container count to stop changing, and required
`COUNT > 0` before it would settle — so with a count of zero it spun to its
ten-minute deadline, logged `container set settled at 0 running`, swept zero
containers for dropped bindings, found none, and printed `all published bindings
intact; nothing to do` before exiting 0. A script written to repair boot,
reporting a healthy platform at a moment when there was no platform. **This is the
fourth instance of the day's recurring defect and the first one that was inside
the code written to fix a previous instance**: a check whose scope lets it produce
only one answer. Its own header comment warns about exactly this shape, one
precondition earlier.

**The monitor was the only thing in the chain that told the truth.** At 19:14:59
`check-platform-health.sh` flagged all seven — six entrances plus `services` — and
mailed at 19:15:02. It got that right for the reason recorded when it was written:
it compares against a named expected list instead of enumerating what happens to be
running, so a service that is entirely gone still appears. The reconciler had the
opposite property, in the same repository, on the same day.

**The fix is that the reconciler now waits for a named set rather than a count.**
A count cannot tell "not restored yet" from "not coming back"; a list can, because
an absent service is still in the list. Anything missing is brought up with
`docker compose up -d`, the result is read back rather than assumed, and a platform
that is still incomplete now exits non-zero even when every binding that does
exist is correct — otherwise a true statement about part of the platform would go
on standing in for a statement about the platform. Run by hand against the empty
platform it took 28 seconds to bring nine services back with all six entrances at
200, and a second run is a no-op. **That is a hand test, not a boot test.** The
outcome that proves this path is `docker did not restore the stack; bringing it up`
→ `stack up: all expected services running`; runbook §1.1 now lists all six
outcomes and what each one means.

**Why Docker did not restore is not established, and it is left that way on
purpose.** The obvious reading is that an update reboot is not an ordinary reboot:
the two boots that restored were plain reboots, this one carried an OS install
across it, and an update reboot has its own staging rather than being one clean
stop and start. A weaker second reading is in the logs — Docker Desktop appears to
have been in Resource Saver pause when the shutdown began, since the shutdown path
issued `/unpause` at 19:04:18.253 and the containers were SIGTERM'd 0.5 seconds
later. Both are one correlation on one boot, the same size of evidence that
produced the wrong logtail diagnosis recorded below, and neither has a mechanism
anyone here has verified. **Nothing depends on choosing between them**, which is
the point: the repair covers a stack that is not running, whatever stopped it from
being restored. What follows from the update reading is only a test instruction —
§1.1 has to be re-run in full after an update, not just the two settings checks —
and that is worth doing whether or not the reading is right.

**One thing this boot did prove, cheaply.** The netmap-cache model predicted the
next boot would be a fast one, because 18:08:23 wrote the cache. It was:
`Start: loaded netmap from disk cache` at 19:10:00, address up at +1 second, the
widest margin of the four. The prediction has now held once, so the model has two
observations behind it rather than one. It also means the *next* boot is the slow
kind — the one most likely to force `OK: all bindings restored`, the last outcome
still never produced by a boot. The same boot also showed the margin table's
framing is only half right: it measures a race, and a race needs both runners.
The address won by a mile and the platform was dead anyway.

### The third boot: the last unproven link, and the diagnosis that did not survive it

§1.1 was run a third time — `sudo reboot` at 18:07:46, back at 18:08:06, hands
off. **It passed.** The tailnet was up, nine containers running with `migrate` at
`Exited (0)`, all six requested bindings equal actual, all six entrances returning
200, and Ollama answering on `127.0.0.1:11434` with `lsof` confirming it listens
nowhere else. The reconcile log's last line is `all published bindings intact;
nothing to do` — the second outcome for the third boot running, so **the repair
path has still never been walked by a boot.**

**What is new is the one thing the entry below said had no evidence behind it at
all: the health daemon survived a reboot.** It was installed at 17:56, after the
17:21 boot, which made it the only link in the chain never exercised by one.
`nexus-health.state` was rewritten at 18:43:17; launchd loaded the job at 18:08:17
and `18:08:17 + 7×300 = 18:43:17` exactly, so it has been cycling on its interval
since 18:13:17. The boundary worry recorded alongside it turns out not to apply:
launchd cannot load the job before `kern.boottime`, so the first fire is always at
uptime ≥ `BOOT_GRACE` and can never be the one that is skipped. This boot's was at
311 seconds.

**The daemon's own mail path is proven too, and it had not been.** Every mail so
far — the baseline and the three from the `grafana` drill — came from a hand run:
the heartbeat field in the state file read 17:55:30 and the plist was installed at
17:56. Under launchd the environment is a different one (no TTY, no login session,
`PATH` only what the script exports), and an unexercised link of exactly that shape
is what this project keeps being caught by. Forced by ageing the heartbeat field to
an old timestamp so the next tick would owe a heartbeat: the daemon fired at
18:53:18 and logged `mailed heartbeat` at 18:53:20. Two seconds, and
`nexus-health.log` has its first content since it was created.

**The margin table gains a third row, and it is the narrowest pass yet:**

| boot | `tailscaled` engine start | address usable | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 (+17s) | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 (+0s) | 17:21:59 | **+11s** |
| 18:08, passed | 18:08:14 | 18:08:23 (+9s) | 18:08:25 | **+2s** |

Docker is the stable side: it binds 11 to 14 seconds after `tailscaled` starts, on
all three. The entire variance is how long the address takes to arrive — 0, 9 and
17 seconds. The budget is about eleven seconds.

**The cause recorded for that variance was wrong, and this boot is what shows
it.** The entry below and [deployment.md](./architecture/deployment.md) §9 both
say the failing boot stalled in a logtail bootstrap-DNS retry loop while the
passing one went straight to `Starting`. The 18:08 boot ran the full loop —
twelve DERP hosts for `log.tailscale.com`, then a second round for
`controlplane.tailscale.com` at 18:08:20 — and still won by two seconds. The loop
is not slow: every attempt fails inside the same second with `network is
unreachable` or `no route to host`, which return immediately instead of timing
out. All four boots in the log ran it. It was correlation read as cause, from two
data points.

**The variable is the netmap disk cache.** Every mention of it in
`tailscaled.log`, with nothing omitted:

| time | line | |
|---|---|---|
| 14:12:41 | `writing netmap to disk cache` | |
| 14:42:24 | *(the tailnet ACL is applied — commit `17939ed`)* | |
| 15:53:06 | `netmap cache is not available` | boot |
| 16:45:15 | `netmap cache is not available` | boot, **failed, −3s** |
| 16:45:32 | `writing netmap to disk cache` | |
| 17:21:48 | `Start: loaded netmap from disk cache; 1 peers` | boot, **+11s** |
| 18:08:14 | `netmap cache is not available` | boot, **+2s** |
| 18:08:23 | `writing netmap to disk cache` | |

With the cache the address is up in the same second `tailscaled` starts, because
it does not need control at all — at 17:21:52 it was still reporting `You are
logged out ... failed to resolve controlplane.tailscale.com` with the address
already on `utun0`. Without it, the address waits for control: 9 seconds on this
boot, 17 on the failing one.

**The rule the log supports is that caches do not chain.** The cache is written
when a new netmap arrives from control, and a boot that loads it does not rewrite
it — 17:21 loaded and never wrote, and 18:08 duly found nothing. So a boot that
wins by eleven seconds leaves the next one with nothing and sets up a slow one.
The single apparent exception fits the same rule: 14:12:41 wrote a cache and the
15:53 boot found none, with the tailnet ACL applied at 14:42:24 in between, which
changes the packet filter the netmap carries.

That last step rests on one observed load-without-write, so it is a model rather
than a proven mechanism — but it makes a prediction that costs nothing to check.
18:08:23 wrote a cache, so the **next** boot should be the fast kind and the one
after it slow again. If the margin alternates, this is right.

**It is also the first thing that says how to force the outcome the acceptance
test actually wants.** `OK: all bindings restored` needs a boot that *loses* the
race, and the losing boots are the ones with no cache — which is to say the boot
immediately following one that read the cache. Back-to-back reboots, watching the
second, is a far better bet than rebooting repeatedly and hoping. Recorded in the
runbook §1.1.

Two smaller things. **The §1.1 pass criterion for the state file was written in a
form that cannot be checked after the fact**: it said the mtime should be within
ten minutes of boot, but the file is rewritten every five minutes forever, so at
18:43 the mtime was 18:43 — thirty-five minutes after boot, which reads as a
failure and is not one. What the check is actually asking is whether the mtime is
recent, and it now says so. And `tailscaled.log` is being filled by the ASUS
peer's Dropbox LAN-sync broadcast to port 17500, dropped by the ACL every 31
seconds and logged each time — 389 lines and 111 KB already. The ACL is behaving
correctly; the cost is to the readability of the log that the original fault was
found by reading, so it is on the roadmap rather than ignored.

### Something now watches the state nothing was watching, and what it still cannot see

The entry below ends on the observation that nothing monitored any of this: the
only reason the boot's state was known is that four logs were read by hand. So
`launchd/check-platform-health.sh` and `online.rcsl.health-check.plist`, running
every five minutes and mailing on a change of state.

Seven checks: `TAILNET_IP` readable from `.env`, the address on an interface, the
daemon answering, every expected service running, every requested host binding
actually bound, all six entrances answering over their published ports, and Ollama
answering on loopback while *not* answering on the tailnet address.

**The service check compares against a fixed list rather than enumerating what is
running, and that is the whole design rather than a detail.** Enumerating would
mean a container that is entirely gone never appears in the list being checked, so
the sweep would look at what remained, find it healthy, and report success. That
is the reconciler's missing third precondition again, and `tailscale status
--json` answering "no SSH host keys" to a question it has no field for. Three
times in two days the same shape. The Ollama check is likewise two assertions and
not one: that it answers is availability, that it does not answer on the tailnet
address is §7.1, and the value holding it on loopback lives in a plist that an
upgrade could replace.

Mail goes out on a change only — a failure once, the same failure never again, a
recovery once — and any mail resets the heartbeat clock, so a recovery is not
followed by a redundant "OK" the moment the old timestamp ages out. That is the
shape that teaches people to filter the alerts.

**The daily heartbeat is load-bearing, and it is also the weak point.** A monitor
running on the host it watches can report "up but not serving", which is the
failure that actually happened, and can never report "powered off". A mail
expected daily is what makes silence mean something. But it relies on a person
noticing a mail that did not arrive, and people are far worse at that than at
noticing one that did. The real answer is an external dead-man's switch that
notifies when a ping stops. Not built: it would be the only thing on this machine
that initiates an outbound connection to a third party, which is a decision worth
taking deliberately rather than as a side effect of wanting an alert.

**Verified in that order, against the live stack, rather than assumed.** All seven
pass in the current state. Stopping `grafana` produced `services` and
`probe:grafana` with the detail naming both; an immediate re-run stayed silent;
starting it produced the recovery; the next run was silent again. Then with the
credentials in place the same drill was run for real and three mails were
delivered — the baseline, the failure and the recovery — with the duplicate still
suppressed. Then it was installed as a LaunchDaemon and left alone: the state file
was rewritten at 18:01:38, 300 seconds after the load, by nothing anyone typed.

**The log is events-only, so `did it run` is answered by the state file's mtime.**
Right after installation the log was empty, which is simultaneously "nothing has
gone wrong" and "this never ran" — exactly the ambiguity that made the original
fault invisible, reappearing in the monitor built to catch it. The state file is
rewritten every run precisely so those two readings separate.

**Two things that would have cost an afternoon each.** A Google app password is
displayed as four groups of four and the obvious thing is to paste what is shown;
`tr -d '\r\n'` kept the spaces, and Gmail's answer to a wrong password is a bare
rejection that names no cause. It strips all whitespace now, with a comment saying
why that is right here and wrong in general. And the boot grace and the
`StartInterval` are both 300 seconds, so at boot the first fire lands on the
boundary and the first effective check may be the second one, ten minutes in. That
is deliberate — the first five minutes belong to the reconciler, and alerting
inside them would mail a failure that is about to be repaired — but it means "no
mail eight minutes after a reboot" is not yet evidence of anything.

**The sender is the operator's own Gmail account, which is not what the
documentation recommends.** `secrets/README.md` says to use a dedicated sending
account, because these files are plaintext on a host with FileVault off and that
mailbox is both where every password-reset link arrives and the platform's first
administrator. The deployment went with the personal account anyway, which is a
reasonable call given that an app password cannot log into the web account and can
be revoked on its own. It is recorded as an accepted risk in §15.7 rather than
left as a silent divergence, which is the pattern this file has now warned about
four times.

What is still unproven is that the health daemon survives a reboot. It was
installed after the last one.

### Round one passed, and the margin it passed by turned out to be measurable

§1.1 was re-run against the repaired chain: `sudo reboot` at 17:21:40, hands off,
then the checks. **It passed**, every item. The tailnet was up, Ollama answered on
`127.0.0.1:11434` and nothing on the tailnet address, nine containers were running
with `migrate` at `Exited (0)`, and `/readyz` on the tailnet address returned 200
with all three checks true. The full §7 port table was run rather than just the
one `readyz`: all six bindings requested equal actual.

**Grafana's `127.0.0.1:3002` bound at boot for the first time in the machine's
life.** The backend log shows six clean `exposer.Add` lines at 17:21:59, no
`can't assign requested address` anywhere, and Grafana's destination now
`172.26.0.2:3000` where every previous attempt had been the invalid
`127.0.0.1:0`. The `viz-ingress` change is proven by a boot rather than by hand.

**The reconcile log's last line is `all published bindings intact; nothing to
do`, which is the runbook's second outcome — the one it warns is luck rather than
proof.** The daemon ran 7 seconds into the boot, waited out its three
preconditions, found nothing to repair and exited 0. So the repair path has still
never been walked by a boot, which remains the whole property being claimed.

**How narrowly it passed is measurable, and the two boots bracket it:**

| boot | `tailscaled` engine start | address on `utun0` | Docker's `exposer.Add` | margin |
|---|---|---|---|---|
| 16:45, failed | 16:45:15 | 16:45:32 | 16:45:29 | **−3s** |
| 17:21, passed | 17:21:48 | 17:21:48 | 17:21:59 | **+11s** |

> **Superseded by the 18:08 boot — see the entry at the top of 2026-07-26.** The
> two paragraphs below name the logtail bootstrap-DNS loop as the cause. A third
> boot ran that loop in full and still passed with two seconds to spare; the loop
> completes inside one second on every boot in the log. The actual variable is
> whether the netmap disk cache loads. The timings and the conclusion that the
> reconciler stays load-bearing are unaffected; the mechanism is not.

The seventeen seconds between those two is identifiable rather than random. On the
failing boot `tailscaled` entered a logtail bootstrap-DNS retry loop the moment it
started — `dial "log.tailscale.com:443" failed: no such host`, then bootstrap
attempts against derp2d, derp7, derp4c, derp12c and derp10 in turn — because no
DNS was up yet. `NoState -> Starting` came only after that loop, at 16:45:32, and
the address arrived with it. The second boot went straight to `Starting` and had
the address in the same second.

**The address needs neither the network nor the control plane, which is what makes
the variance startup-side rather than reachability-side.** At 17:21:48 `utun0`
already carried `100.108.250.62`, while at 17:21:52 `tailscaled` was still
reporting `You are logged out ... failed to resolve controlplane.tailscale.com`
and `en1`'s default route did not appear until 17:21:53. The address is restored
from the cached prefs in `/Library/Tailscale`. So what decides the race is only
whether `tailscaled`'s own startup stalls before it runs its state machine.

**That makes the failing boot the ordinary cold-boot path, not an anomaly.** A
cold boot with DNS not yet up is exactly the condition that runs the bootstrap
loop. Nothing in the configuration made this boot skip it, so nothing guarantees
the next one will. The reconciler stays load-bearing, and unproven at boot: round
one has passed, and unattended recovery is an observed property of one boot rather
than a guaranteed one.

Two smaller things. **Nothing monitors any of this.** An outcome of `STILL
UNBOUND`, or a daemon that never ran, would leave the platform down and silent,
which is the property that made the original failure worst — and the only reason
this boot's state is known is that someone sat and read four logs. Prometheus is
already running, so a blackbox probe over the six bindings is the shape of the
fix. And the 17:10 line in the reconcile log that lacks `container set settled` is
not an anomaly: it is the first draft, run by hand before the third precondition
was added, and it is what a check that could only produce one answer looks like in
the log it left behind.

Round two, the 26.5.2 update, is unblocked by the runbook's own gate. Whether to
spend more reboots first, trying to force the `OK: all bindings restored` outcome,
is a separate call — and the odds are not remote, since one of the two boots so
far lost the race.

### The reboot test, which the chain failed in the one way nobody would notice

§1.1 round one was run: `sudo reboot`, hands off, then the checks. **It failed.**
Almost every link held — automatic login, both LaunchDaemons, Docker Desktop's
autostart, nine containers running with `migrate` correctly at `Exited (0)`,
`tailscale serve` config intact, Ollama on `127.0.0.1:11434`. What did not come
back were four of the six published ports. `gateway`, `admin-public` and
`frontend-public` had no host binding at all, so the platform was unreachable
from the tailnet: `curl http://<TAILNET_IP>:8000/readyz` returned `000`.

The cause, from the Docker backend log at 21 seconds after boot:

```
listen tcp4 100.108.250.62:8000: bind: can't assign requested address
```

Docker Desktop restores containers before `tailscaled` has put the address on
`utun0`. The bind fails, **the backend logs one warning and does not retry**, and
because nothing exited, `restart: unless-stopped` never fires. The container runs,
reports healthy, and publishes nothing.

**This is the exact failure the previous entry predicted, and it arrived with the
one property that makes it worst: every casual check says fine.** SSH still
worked, because Tailscale SSH is served by `tailscaled` on the tailnet interface
and never touches a Docker binding. The tailnet admin UI still worked, because
`tailscale serve` forwards to loopback and loopback binds reliably at boot. So
you log in, run `docker compose ps`, see nine containers `Up` and the gateway
marked `healthy`, and conclude the reboot was clean. Only something that actually
crosses the published port finds out. The natural experiment is clean: every
entrance reached through `serve` → loopback survived, 2 for 2; every entrance
binding the tailnet address directly did not, 0 for 4.

**Two proposed fixes were wrong before the third was right, and both were wrong
in the same way — assumed rather than tested.** `docker compose up -d` is a no-op
against a container already running with a matching config; it reported everything
`Running` and restored nothing. `docker compose restart` reuses the container and
leaves the backend's forwarding table alone; grafana came back still unbound. The
forward is created when a container is *created*, so only `--force-recreate`
re-establishes it — verified, and `/readyz` returned 200 immediately after. Had
the reconciler been written to the first design, it would have run every boot,
logged success, and fixed nothing.

So `launchd/reconcile-port-bindings.sh` and its LaunchDaemon. It waits for three
preconditions instead of racing them: the address actually on an interface
(`ifconfig`, not `tailscale status`, because the bind needs the former), a
responsive daemon, and the container count holding steady across two samples ten
seconds apart. The third was missing from the first version and is the same error
again, caught before the test rather than by it — the daemon answers well before
the last container is restored, and at boot they come back one at a time, so
checking on the daemon alone would enumerate only the containers that had already
returned, find those intact, and exit reporting success without ever looking at
the ones still to come. A check whose timing lets it produce only one answer.
Waiting for the count to stop moving avoids picking a fixed delay, which would
have been another guess. It then recreates only the containers whose requested
`PortBindings` have an empty `NetworkSettings.Ports`, which is the precise
signature of the dropped forward. It verifies once and stops. It is deliberately
not `KeepAlive`: it exits non-zero when a binding is beyond repair, and under
`KeepAlive` that would become a container recreated every few seconds forever.
`TAILNET_IP` is read from the same `.env` compose interpolates, so the address it
waits for cannot drift from the address it binds. Written for bash 3.2, which is
what macOS ships — the first draft used `mapfile` and would have failed at boot.

### Grafana's host port had never bound, and the reboot only made it visible

Chasing the above turned up a fourth unbound port that was not a reboot fault at
all. Grafana's `127.0.0.1:3002` had never worked once: the earliest log on the
machine shows `exposer.Add(... 127.0.0.1:3002 -> 127.0.0.1:0)` followed
immediately by `removing`, a forward to an invalid destination.

`metrics-viz` is `internal: true`, and Docker cannot publish a host port into an
internal network — no gateway address means no route from the host, and the
daemon declines with `no suitable container IP found`. That is a *warning*, so
the container starts, reports healthy, and the port is simply absent.
`docker-compose.yml` stated the contradiction in two adjacent comment lines —
"All internal: nothing here is published", then "Grafana is the sole member with
a host port" — and neither the checklist nor anything else ever loaded that port,
so nothing contradicted it.

Publishing requires a non-internal network, and a non-internal network
necessarily grants egress; no Docker bridge configuration gives one without the
other. Grafana now has a dedicated `viz-ingress` for the host port and stays on
`metrics-viz` for the datasource, so Grafana alone pays that cost. The one-line
alternative — dropping `internal` from `metrics-viz` — would have handed the same
egress to Prometheus, which is the single container spanning the gateway and
admin trust tiers and therefore the worst place to put it. Verified after the
change: Grafana reaches `prometheus:9090`, Prometheus answers `Network is
unreachable` to an off-host address, and 3002 returns 200.

**Round one has not been re-run at the time of writing.** The fix is in place and
tested by hand against a live fault, but the property being claimed is that a
*reboot* recovers, and no reboot has happened since the reconciler was installed.
Everything in the previous entry about a chain of individually correct settings not
being evidence applies unchanged, and now with a worked example. Round two, the
26.5.2 update, stays blocked behind a passing round one. *(It was re-run later the
same day and passed without the reconciler having anything to repair; the entry
above records the result and the margin.)*

The runbook gains the check that would have caught this in section 7 — the six
expected bindings, compared as requested-versus-actual rather than read off
`docker compose ps` — and §1.1 now says why `readyz` is the one line in the
acceptance run that cannot be skipped, and why getting in over SSH proves nothing
about whether the platform is serving.

### FileVault deferred, and the headless prerequisites the runbook was missing

The Mac Studio was powered on for the first time, which turned the first-deploy
runbook from a document into something being executed and immediately surfaced a
decision the documents had stated but never sequenced.

`security.md` §9.3 says to keep FileVault enabled and argues it well: physical
theft in a shared facility is worth more than reboot convenience. What it
assumed was the UPS that makes the reboot cost rare, and the UPS is Phase 3 and
does not exist yet. On a headless machine with no UPS, an encrypted disk means
every power cut takes the platform down until someone walks to it, because the
pre-boot unlock happens before there is any network, Tailscale, or SSH. So
FileVault is off for the first deployment, and the UPS is the trigger to turn it
on. Recorded as an accepted risk in §15.6 rather than left as a silent
divergence from §9.3, which still holds as a position.

The decision has a consequence chain worth writing down, because two of its
three links are invisible until something fails to come back after a reboot:
FileVault off is what makes automatic login available, automatic login is what
produces a logged-in desktop session, and that session is what Docker Desktop
needs in order to autostart. Without it the containers' `restart: unless-stopped`
never gets the chance to matter. Enabling FileVault later breaks the first link
and restores the second by a different route, since the pre-boot unlock doubles
as the login.

Working the question through turned up three prerequisites the runbook did not
have, all of which must happen before the monitor is removed rather than after:
remote login, restart-after-power-failure, and startup security. The last one
changes weight rather than appearing from nowhere. §11 already required Full
Security, but with FileVault off it becomes the main control against booting
from external media instead of a second layer behind encryption.

---

## 2026-07-26

### FileVault off, and the unattended-recovery chain that is built but not yet proven

§15.6's sequencing decision was acted on: `sudo fdesetup disable`, and
`fdesetup status` now reports `FileVault is Off`. `supportsauthrestart` returned
true beforehand, so the `authrestart` path exists whenever it goes back on.

The decision was taken with the trade stated rather than assumed. What the
machine now holds unencrypted is the eleven plaintext credential files under
`secrets/`, the TOTP encryption key among them, and whatever research data passes
through the platform; the protection of all of it now rests on Full Security
startup and a locked room, which §15.6 already names as load-bearing rather than
defence in depth.

**Two things in that section's reasoning needed extending, and now say so.** It
treats the UPS as the trigger and the bound on cold boots, which is true for
power cuts and false for everything else that reboots a machine — a kernel panic,
a watchdog reset, a failed update. Each of those lands at the pre-boot unlock
screen just the same, so installing the UPS lowers the frequency of losing
unattended recovery rather than restoring the property. There is no clean way to
have both an encrypted volume and unattended recovery on hardware with no
out-of-band management, and a Mac Studio has none. The second addition is that
this is a constraint on remote operation and not only on data at rest: with
FileVault on, remote access has no fault tolerance, and the one failure that ends
it is the one nothing remote can repair.

**The chain now exists end to end and is not yet proven.** Every link is in
place — the two LaunchDaemons in `/Library/LaunchDaemons` starting without a
login, Docker Desktop's start-at-login, `restart: unless-stopped` on all nine
long-lived services with `migrate` correctly left at `no`, and `pmset autorestart
1` — with automatic login the last piece. What has not happened is a reboot. A
chain of individually correct settings is not evidence, and the failure mode is
silent: the service is simply gone, with nothing to say which link broke.

So the runbook gains §1.1, the one test in it that must be run with a person at
the machine. Two rounds, deliberately separate: a clean reboot first, because it
has one variable, and the pending macOS 26.5.2 update second, because combining
them makes a failure unattributable. The post-update check includes re-reading
`autoLoginUser` and `pmset autorestart`, since macOS updates have been known to
reset exactly those, and they are two links of this chain. Until both rounds
pass, remote system updates should not be attempted: an update that stops at an
interactive screen cannot be cleared remotely.

The runbook also now states the general rule the whole day kept running into.
The dividing line for what is safe to do remotely is whether the action can
affect the next boot. Development, platform administration, container
operations, ACL and membership changes: all safe. FileVault, automatic login,
major upgrades, anything touching `tailscaled`'s ability to start: one-way doors
on a machine with no remote console.

### Remote access, and a diagnostic that invented the wrong conclusion

The machine is headless, so it needs a way in. It is Tailscale SSH, gated by the
`ssh` block that was already sitting in §3.4, with `action: check` forcing
re-authentication every twelve hours. macOS Remote Login is off: `tailscaled`
serves SSH on the Tailscale interface only, so §11's "listening on the Tailscale
interface only" is satisfied by not running a second SSH server rather than by
editing `sshd_config`, and there is no password or key that can leak. Remote
Login had been enabled during the attempt and was binding every interface,
including the LAN, accepting passwords — the exact shape §11 exists to prevent.
Nothing answers on `127.0.0.1:22` now, which is the useful check precisely
because Tailscale SSH does not bind loopback.

**The detour is worth recording, because the wrong turn was mine and it was a
measurement error.** Concluding that Tailscale SSH does not run on macOS, I read
`tailscale status --json` for SSH host keys and found none. That field does not
exist in the JSON, so the probe returned "absent" no matter what the truth was,
and the conclusion followed confidently from a check that could only ever produce
one answer. Acting on it, the `ssh` block was removed from the ACL — which was
the only thing authorising SSH — and the next attempt failed with `tailnet policy
does not permit you to SSH to this node`. The banner is precise and says exactly
what happened; the earlier reasoning had made it look like confirmation of the
platform theory instead. `RunSSH` in `tailscale debug prefs` is the field that
answers the original question, and it had been `true` throughout.

The generalisable part: a probe that cannot distinguish "absent" from "I asked
the wrong question" is worse than no probe, because it converts uncertainty into
false confidence. That is the same failure mode as the day's other six, arriving
from the diagnostic side rather than the configuration side.

**Two properties came out of it that are now in the documents.** Tailscale SSH
needs both halves — port 22 in `acls` to carry the connection and the `ssh` block
to authorise the session — and the two failures look nothing alike: without the
port the connection never arrives, without the block `tailscaled` answers and
refuses. The runbook now carries that split as a table, plus the log line that
tells them apart (`handling conn` in `tailscaled.log` means the connection
reached the server, so the problem is authorisation, not networking).

And a tagged node has no user identity, which reaches past SSH: `tailscale whois`
for `tag:ai-server` lists tags and no user, so `tailscale serve` has no
`Tailscale-User-Login` to inject for a connection from the server itself. The
tailnet management entrance cannot be exercised from the machine it runs on. That
is a property of tagging rather than a misconfiguration, and it is now stated in
both §3.4 and the runbook's bootstrap step, because the obvious first test is the
one that cannot work.

### Inference served end to end, and a model that could never leave its initial state

`POST /v1/chat/completions` now works on the target hardware, streaming and not,
from socket through key verification, quota, the trusted-proxy check, the country
filter, the routing policy, the GPU, SSE framing, and back out to a usage record.
That is Phase 1's stated goal observed rather than argued.

Non-streaming returned in 0.51s with `finish_reason=stop`. Streaming produced
twelve frames in the OpenAI envelope — a role frame, content deltas, a terminal
frame carrying `finish_reason`, then `[DONE]` — and reassembled correctly.
`usage_records` holds one row per successful request, stamped with the default
tenant; the two requests that were refused earlier in the path recorded nothing,
which is right, because neither reached the use case. The gateway's `/metrics`
reports `nexus_inference_requests_total 2` and `nexus_inference_tokens_total 33`,
matching the two completions exactly. The admin chat panel had produced two
further usage rows and no gateway metrics, which is also right: it is served by
the admin entrance, not the gateway.

Two things about the request shape are worth writing down, because both looked
like faults for a minute. The OpenAI `model` field carries the **capability**,
not a model alias — `RouteChatRequest` resolves a policy by capability and the
policy chooses the model, so `"model": "qwen7b"` is refused with
`no_available_model` while `"model": "chat"` succeeds. And in production the
gateway refuses anything that did not arrive through the proxy, so testing before
nginx exists means presenting `X-Nexus-Proxy` and an `X-Forwarded-For`. Both
refusals were the design working; neither is documented anywhere a caller would
look, which the API reference should fix when it exists.

**Before any of that, a registered model could not be downloaded at all.**
`model-table.tsx` offered `Unload` when the state was `loaded` and `Load` in every
other case — including `not_downloaded`, where the use case's precondition
guarantees a 409. A freshly registered model was therefore a dead end: the only
button available was the one that could not work. The backend endpoint, the
`startDownload` client, the `useStartDownload` hook, the `useDownloadJob` poller
and the `DownloadProgress` component all existed; the hook and the component were
never referenced from anywhere. The whole download UI was built and never wired
in, which is why `ROADMAP.md` could carry `features/models: download progress via
useDownloadJob` as done, and why this file could claim the models table polls that
endpoint. It does not; nothing did.

The actions now mirror the use cases' own preconditions, so a button that is
present is a button that can succeed: `Download` unless the model is loaded,
`Load` only from `downloaded`, `Unload` only from `loaded`. The table also owns
the job now, because `useDownloadJob` stops polling at a terminal state without
telling anyone, so the row would otherwise sit at `downloading` until a reload.

A measurement worth keeping: the loaded model is 5.7 GB resident against 4.7 GB of
weights, where the same model measured 6.6 GB this morning under a hand-started
`ollama serve`. The difference is `OLLAMA_KV_CACHE_TYPE=q8_0`, which the committed
plist carries and an ad-hoc run does not — so the KV cache the memory budget's
headroom has to absorb is about 1.0 GB here, not 1.9 GB.

### The stack is up on the Mac Studio, and the frontend could not reach its backend

First full `docker compose up` on the target hardware. `migrate` exited 0 having
logged `database roles provisioned: nexus_gateway(gateway), nexus_admin(admin)`,
all ten containers came up, and the gateway's `/readyz` returned all three checks
true — including `runtime`, which means the container reached the native Ollama
through `host.docker.internal` for real rather than in a test.

**The account split is now enforced by the deployed database, on this machine.**
`pg_stat_activity` shows the gateway connected as `nexus_gateway` and the two
admin entrances as `nexus_admin`. As `nexus_gateway`: `SELECT` on `api_keys` and
`routing_policies` succeeds, `INSERT` into `usage_records` succeeds, and `INSERT`
into `api_keys`, `users` and `audit_log` are each refused with `permission
denied`. That is the §6 property proven where it finally matters. The published
ports match §3.2 exactly: gateway and admin-public on the tailnet address only,
admin-tailnet on loopback only, nothing on `0.0.0.0`.

**Then the management UI turned out to be unreachable, for a reason that
`docker inspect` actively hides.** Every `/admin/*` call from either frontend
failed, the log reading `Failed to proxy http://localhost:8001/admin/me
ECONNREFUSED`, while the container's environment plainly carried
`ADMIN_API_URL=http://admin-tailnet:8001`. The rewrite lived in
`next.config.js`, and `output: 'standalone'` serialises the resolved config into
`.next/required-server-files.json` at build time — so `process.env.ADMIN_API_URL`
was read during `pnpm build`, where the Dockerfile never sets it, and the
`?? 'http://localhost:8001'` fallback was compiled into the image. Confirmed by
grepping the shipped bundle: it contains `http://localhost:8001` and nothing
else. The runtime variable was correct, present, and ignored.

The fallback is what made it silent. Without it the build would have failed and
the defect would have been caught on the machine that built the image; with it,
the image builds clean, starts clean, reports healthy, and fails only when a
human tries to sign in.

The fix is `frontend/src/middleware.ts`, which resolves the destination per
request. That was chosen over build args because the two entrances need
different destinations while sharing one image, which is the arrangement
`docker-compose.yml` documents; baking would have forced two images. The env is
read inside the handler rather than at module scope, since module-scope access
is the shape a bundler can constant-fold — the same failure in a different
place. An unset variable now logs and returns 500 instead of defaulting.
Verified: both entrances now reach their own admin API (401 and 400 from the
backends respectively, not 500), with no ECONNREFUSED.

**A tagged server cannot sign in to its own tailnet entrance.** Testing the
bootstrap from the machine itself returns 401, and correctly so: `tag:ai-server`
was applied earlier today, `tailscale whois` for the node lists Tags and no User,
and the `Tailscale-User-Login` header `tailscale serve` injects is derived from
the connecting node's owner. A tagged node has none. The runbook said to use
"your device" without saying why the obvious first attempt cannot work, so it now
says so, and gives the loopback curl that tests the backend directly.

That curl also demonstrates §5.1 rather than describing it: adding the header by
hand to a request against `127.0.0.1:8001` authenticates as an administrator,
which is exactly why that entrance binds loopback and why a shared Docker network
with the gateway was a defect worth the network split. It also bootstrapped the
first administrator as a side effect — `users` now holds
`leolove3very@gmail.com` as `admin` in the `default` tenant, and `audit_log`
holds one `bootstrap.first_admin | success` row, which is §12's requirement
observed on a live deployment rather than in a test.

### The tailnet ACL, which the runbook never told anyone to apply

`ROADMAP.md` has carried a checked box reading "Tailscale ACL including
`tag:ntnu-proxy`, so members cannot bypass the proxy" since the architecture was
written. It described a template in `security.md` §3.4. There was no tailnet to
apply it to until today, and the runbook — which is the document that exists so
nothing gets skipped — never mentions applying it or tagging the server at all.

Following the runbook exactly therefore ends here: `sudo tailscale up` joins the
tailnet under the default policy, which for a new tailnet is
`{"src": ["*"], "dst": ["*"], "ip": ["*"]}`. Every rule in §3.4 hangs off
`tag:ai-server`, and a device that joined without `--advertise-tags` carries no
tag, so none of them matches. The failure mode is not that nothing works; it is
that everything is reachable. Any device subsequently added to the tailnet could
open `100.x.y.z:8000` or `:8002` directly and bypass every control the proxy
applies — the exact sentence §3.4 opens with, latent for as long as the tailnet
had one member and live the moment it had two.

There is a sharper consequence downstream. §8 asks the NTNU proxy administrator
to join under `tag:ntnu-proxy`, but a tag cannot be applied unless `tagOwners`
already names it. Without the ACL step, that request fails on the other person's
machine, for a reason nothing in the runbook explains.

**Applied, and then pinned.** The policy is now live on the real tailnet, and the
machine carries `tag:ai-server` with key expiry disabled — Tailscale's 180-day
default would otherwise have dropped a 24/7 server off the tailnet half a year
in. The part worth keeping is the `tests` block added to §3.4: Tailscale runs it
on every policy save and rejects a policy that fails one, so "a human member
cannot reach the data-plane ports" and "the proxy cannot reach the management
endpoints" are now assertions rather than prose. Both pass. The runbook gained
the two missing steps in the order they have to happen, since tagging before the
ACL exists cannot work.

The pattern is the same one this file recorded twice already today, and the
header warns about generally: a control that was designed, written down, marked
done, and never actually in force. The account-split test asserted nothing; the
Ollama loopback bind would not have survived a reboot; the pnpm allowlist was
inert; this ACL was a file nobody had applied. None of them looked wrong.

### GPU inference, verified at last, and two runbook steps that were quietly wrong

Runbook §3 and §4 are done, and the claim the whole machine exists for is no
longer a claim: `ollama ps` reports **100% GPU** for `qwen2.5:7b`, generating at
91.7 tok/s with prompt evaluation at 180 tok/s, at the 32768 context that
`MAX_CONTEXT_LENGTH` already configures. A container reaches it through
`host.docker.internal` and gets a completion back, so §0.1's whole bet — runtimes
native, containers calling out to them — is now measured rather than reasoned.

**A number the memory budget will want.** The model's weights are 4.7 GB and its
resident size while loaded is 6.6 GB; the difference is the KV cache at 32k
context. `MemoryBudgetService` counts only `resource_profile.memory_gb`, which is
the weights, and leaves the rest to the 20% headroom — so the headroom is
carrying about 40% of weight size per loaded model at this context on this
architecture. That ratio is not linear in model size and must not be extrapolated
to the 51.2 GB the budget currently permits, but it is the first real measurement
of the quantity §4.3 has been guessing at, and it is what the deferred
`MetricsPort` ingestion should be calibrated against.

**The runbook's Ollama service step was a silent security failure.** It said to
run `launchctl setenv OLLAMA_HOST 127.0.0.1` and then `brew services start
ollama`. `launchctl setenv` writes to the boot session domain and does not
survive a reboot, and Homebrew's plist carries no `OLLAMA_HOST` of its own — so
the first restart would drop Ollama back to its `0.0.0.0:11434` default and
publish inference to the LAN, with nothing to indicate it had happened. The bind
required by §7.1 has to survive a reboot without help, so the value now lives in
a plist committed at `launchd/online.rcsl.ollama.plist`. Two further corrections
came with it: a LaunchDaemon rather than Homebrew's LaunchAgent, because an agent
waits for a login that a headless machine after a power cut will not get; and an
explicit `UserName`, because a daemon defaults to root and would look for models
in `/var/root/.ollama` and find none. §7.1(d)'s dedicated service account is the
later hardening step, and that key is where it will land.

**§4 had a smaller version of the same gap.** It opens with `sudo tailscale up`,
but `brew install tailscale` starts no daemon, so the step fails with `failed to
connect to local Tailscale service`. `sudo brew services start tailscale` comes
first, and the `sudo` is load-bearing for the same reason it is on Ollama: it
makes the difference between a system daemon that boots and a user agent that
waits for a login.

The machine is on the tailnet at `100.108.250.62`, MagicDNS
`rcslmac1demac-studio.tail68e30b.ts.net`, and `.env` now carries that address and
the bootstrap login with no placeholders left. `tailscale serve` waits for the
frontend to exist. The only thing still blocking a first `docker compose up` is
the GeoLite2 database, which `ENV=production` with a non-empty
`ALLOWED_COUNTRIES` refuses to start without.

### The Mac Studio exists, and a test that had stopped testing anything

The deployment host is real now, and the first thing it did was falsify a claim
this file has been making for a week.

The machine is the one [ARCHITECTURE.md](./ARCHITECTURE.md) §0.2 describes: M4
Max, 64 GB unified memory, macOS 26.5. It arrived bare, so this started at
runbook §2 — Homebrew, then git, tailscale, ollama, uv, node and pnpm, then
Docker Desktop. Compose parses against the real `.env` and the real file
secrets, and the §1/§3.2 network invariant holds here as it did on the dev
machine: the intersection of the gateway's networks with each admin entrance's
is empty. `host.docker.internal` resolves from inside a container, which is the
whole of §0.1's bet that runtimes stay native.

**`test_db_role_grants.py` had been failing since 968b2ee, in the way that
hides itself.** The integration suite runs only when `TEST_DATABASE_URL` is
set, and nothing had set it since multi-tenancy landed, so the first full run
here was the first run since. The test opens with the gateway's one legitimate
write — an INSERT into `usage_records` — before asserting the six writes it
must be denied. Multi-tenancy made `usage_records.tenant_id` NOT NULL and did
not update that INSERT, so the test aborted on a constraint violation at its
first statement and **none of the six denials was ever asserted**. The same
staleness sat in the admin positive control on `users`.

The property itself is sound: with `tenant_id` supplied, all six denials pass
and the server refuses the gateway account an INSERT into `api_keys`, `users`,
`routing_policies` and `audit_log`. So this was a test defect, not a security
defect. What it cost was the evidence — and this file and `ROADMAP.md` have
both been citing that evidence by name. The multi-tenancy entry below calls the
account split "undisturbed" and reasons its way there correctly, but reasoning
is the thing the test existed to replace. This is the drift the header of this
file warns about, caught by the first machine that actually ran the suite.

**Two toolchain divergences, from the same first run.** `uv` had no
`.python-version` to read and `requires-python` says only `>=3.12`, so it built
the environment on 3.14 while `backend/Dockerfile` ships `python:3.12-slim`:
local verification and the deployed artifact were different interpreters. The
pin is now `backend/.python-version` and the suite was re-run on 3.12.
Separately, ruff 0.16.0 flags S608 on the tenant backfill's `UPDATE {table}`,
where the only interpolation is a table name from a literal tuple in the same
module and the value is bound. Suppressed inline with its reason rather than by
widening the existing per-file ignore, so it stays greppable.

Verified on this machine: 359 tests pass on Python 3.12 against a real Postgres
17 (299 unit, 60 integration — the integration half for the first time on Apple
Silicon), ruff and mypy clean over 127 files, `docker compose config` resolving
the real secrets. What still waits is everything needing the stack actually up:
GPU inference, MLX, `tailscale serve`, nginx, the GeoLite2 database, and the
live free-memory figure the memory budget is still standing in for.

**An operational note that is not a code change.** The host is configured as a
personal computer rather than a server: FileVault on, which makes auto-login
unavailable and stops an unattended reboot at the unlock screen; `pmset
autorestart` off, so it does not come back after a power cut; and Docker
Desktop's VM was sized at 8 GB against a memory budget whose 20% headroom is
meant to cover the OS, the containers *and* inference working memory. The VM is
now 4 GB. The rest is §15.6's sequencing decision and waits on the UPS.

---

## 2026-07-25

### Logs UI and usage charts, and a chart library chosen by not choosing one (Phase 2)

Two frontend Phase 2 items, both needing a backend read path first. Neither the
audit log nor the usage table had one: auditing was write-only (its adapter
commits each row in its own transaction so a failed request still leaves a
trail), and usage had only the dashboard's 24-hour totals. So the work is a
read path on each, then the screens.

**The audit read is an ordinary scoped query, kept away from the writer.** A new
`AuditEntry` entity and `PostgresAuditLogRepository` read the append-only table on
the request session, tenant-scoped by the same `_scope` helper every other read
uses, with `ReadAuditLog` behind `logs:read` (a scope that already existed in the
enum, unused until now). The write side stays on `AuditPort` and its independent
transaction: reading must not borrow that machinery. The page is bounded (a
default 50, a hard 200) because an operator UI never needs the whole table and an
unbounded limit is a memory lever on a table that only grows. The frontend
`features/logs` is server-paged rather than a client-side table over one fetch,
for the same reason, with action and outcome filters that reset to the first page
so an offset cannot point past a smaller filtered set.

**Usage analytics reads the accounting table, which is not what Grafana shows.**
The distinction from the observability commit earlier today matters: Prometheus
reports live operational state to an operator over Grafana; this reads
`usage_records`, per tenant, for the management UI. Different audience, data, and
access path. A `date_trunc` aggregation (`bucketed_usage`) groups by time bucket
and capability in one query, and `ReadUsageAnalytics` (behind `usage:read_all`,
the scope the dashboard totals already use) folds the rows into per-bucket totals
and per-capability series. The window is a small closed set (24h, 7d, 30d) that
fixes the bucket granularity with it, so the query's cardinality is bounded and
the range picker maps to exactly three shapes; time comes from an injected clock
so the windowing is testable.

**The chart-library question, which the codebase had deliberately deferred, is
settled: no library.** The `MetricChart` placeholder had recorded the open
decision (Tremor had shifted to copy-in source with the §10 supply-chain caveat;
Recharts was the fallback but a real dependency with a React 19 version
constraint). The data these screens show is simple magnitude-over-time, so the
charts are inline SVG instead: a component that draws lines and an area with axes
and a hover tooltip, and the pure geometry (scales, path building, nice-max
rounding) in `chart-geometry.ts` where it is unit-tested with no DOM. Series
colours read the theme's computed `--chart-1..5` ramp through `currentColor`, so
they follow light and dark without a second palette. The trade is that axes and
the tooltip are ours to maintain; that is acceptable while the charts stay simple
time series, and a richer visualisation would be the point to revisit it. One
series renders as a filled area, several as plain lines with a legend.

The dashboard's two chart placeholders now carry real 24-hour data from the same
endpoint, and its note no longer promises Phase 2: it points at usage records for
counts and at Grafana for the live operational metrics.

Verified: 6 new backend unit tests (the two use cases' authorization, the page
clamp, and the fold from buckets into totals and per-capability series) and 3
integration tests against real Postgres (the audit read's tenant isolation and
newest-first ordering, and that `date_trunc` buckets by hour and capability while
excluding another tenant's rows); the full backend suite passes, mypy and ruff
are clean. On the frontend, 9 new tests (the chart geometry and the two response
schemas), `pnpm test`, `eslint`, and `next build` with the `/logs` and `/usage`
routes generating. One small structural consequence worth noting: extending
`UsageRepositoryPort` with `bucketed_usage` meant the `MeteredUsageRepository`
decorator from this morning had to delegate it too, which mypy caught rather than
leaving for runtime.

### Observability: the emission side, and the word "metrics" pulled apart (Phase 2)

The Phase 2 item read "MetricsPort with Prometheus and Grafana; live metrics
replace the static memory budget," and the first useful thing was noticing it
conflates two different things the codebase already keeps apart. There is a
`MetricsPort` in the domain, and it is the *ingestion* side: `free_memory_gb`, a
live hardware figure the memory budget would consult instead of static capacity.
And there is the thing every deployment actually wants first, the *emission*
side: the process exposing what it is doing so Prometheus can scrape it. This
change ships emission in full. The ingestion half stays deferred on purpose,
because a real free-memory number for the node exists only on the Mac Studio, and
`security.md` §4.3 already says the budget must not wait on metrics: so the budget
stays static and authoritative until the figure is real, which is the
conservative reading of that rule rather than a gap.

**The instruments are derived from what the code already produces, so the
delicate paths are untouched.** HTTP series (request count, duration, in-flight)
come from one pure-ASGI middleware. Pure ASGI rather than `BaseHTTPMiddleware`
because the gateway's reason for being is streaming, and `BaseHTTPMiddleware`
returns once the response object exists, which for an SSE stream is before a
single token has gone out: timing and the in-flight gauge would measure
time-to-first-byte, not the duration a request actually occupied a slot. Wrapping
`send` and recording when the response truly finishes fixes both. Inference series
(tokens, completion outcome, duration by capability and model) come from a
`MeteredUsageRepository` that wraps the usage repository and reads the same
`UsageRecord` the streaming use case already writes in its `finally` — so
`RouteChatRequest`, the most carefully ordered file in the tree, gains observation
without a line of instrumentation in it. The concurrency-slot gauge is read from
the live limiter at scrape time rather than tracked through the request path, so
it cannot drift out of step with the semaphore it reports.

**The route label is a template, never the raw path.** An id in a URL would make
each request its own time series, and a port scanner hammering 404s would turn
unbounded cardinality into a memory problem. The middleware reconstructs the
matched template from the router's path params and collapses anything unmatched to
a single `__unmatched__` label. No label carries a caller identity, tenant, or
key, for the same reason and because the exposition body is an information
disclosure if it ever leaks.

**Which is why /metrics is guarded, not merely placed on an internal network.**
The gateway carries `/metrics` on the same ASGI app that faces the proxy, so
network placement alone would rest on the operator's nginx being precise forever.
The endpoint requires a bearer token from a file secret — the same shared-secret
pattern the trusted-proxy check already uses — and returns 404, not 401, without
it, so a caller does not even learn it exists. On the admin entrances `/metrics`
is exempted from the geo/proxy perimeter (like health) so Prometheus can scrape
over the internal network; the token is the actual control there. Placeholder
tokens are refused in production exactly like the other secrets, but only when
metrics are enabled, so a deployment that runs no Prometheus is not forced to
invent one.

**Scraping does not reopen the gateway/admin isolation.** Prometheus scrapes all
three apps, so it sits on both a gateway-side scrape network and an admin-side
one, but the gateway and the admin entrances still share no network with each
other, which is the §1/§3.2 invariant (`docker compose config` confirms the
intersection is empty). The only node on both is Prometheus, and unlike Postgres
and Redis — also dual-homed but never initiating — Prometheus does initiate. What
makes it safe is that it is a scraper, not a forwarding proxy: it issues only the
fixed `GET /metrics` requests in its config, so a compromised gateway cannot use
it to reach an admin entrance. Grafana is on the Prometheus network only, binds
loopback, and is reached over `tailscale serve`; Prometheus publishes no port.
Grafana's default `admin`/`admin` is replaced from a file secret, with anonymous
access and self-registration off, which is the §6 requirement that had been
sitting unactioned.

Verified: 18 new unit tests (the token guard returning 404 on all three apps, the
disabled-endpoint case, a served request counted under its template, the slot
ceiling reported, a scanner's paths collapsing to `__unmatched__`, the label
reconstruction, and the metered repository emitting from a record while still
persisting it); the full unit suite at 290 passing; ruff and mypy clean; and
`docker compose config` renders with the network invariant intact. What waits for
the Mac Studio is what always does: real scrape traffic, and the ingestion figure
that would let the budget go live. The two dependent Phase 2 items, the logs UI
and in-app usage charts, are unstarted; Grafana covers the metrics view for now.

### mypy made honest, and put where it cannot drift again

Running `mypy app` over the whole package, which this log had repeatedly called
clean, turned up 24 errors. Two things had been hiding them.

There was no automation. pre-commit ran gitleaks and ruff but never mypy, and
there is no CI, so "mypy clean" was an impression from running it by hand on
whichever module was just written, never the whole package at once.

And the config's relaxation was inert. A block declared `strict = false` for
`app.adapters.*`, on the reasoning that adapters wrap third-party libraries with
incomplete stubs. But mypy silently ignores `strict` in a per-module override:
it is a global-only meta-flag, so the adapters were strict-checked the entire
time, and the comment describing them as relaxed was describing something that
was not happening.

The one error worth calling a defect rather than noise was a contract lie. Both
runtime adapters typed `generate` and `pull` as returning `AsyncIterator`, while
`ModelRuntimePort` promises `AsyncGenerator`. `AsyncIterator` is the wider type
and does not guarantee `aclose()`, which is the exact promise the port's own
docstring spends a paragraph on, because that promise is the streaming contract:
without it a disconnected client leaves the runtime generating and the slot held.
The behaviour was correct (an `async def` with `yield` is an async generator), but
the annotation was weaker than the code, and it was the mismatch mypy flagged at
`di.py` as the adapters not satisfying the port. Aligning the annotations closed
that and the port-conformance errors together.

The rest were ordinary: a missing `target: Model` and three unannotated function
parameters, a response-variable that needed widening to `Response`, and a
`type: ignore` that no longer suppressed anything. Genuine third-party stub gaps
(SQLAlchemy typing async `execute` as `Result`, which lacks `rowcount`; redis
returning `str` under `decode_responses=True` but typed `bytes | str | None`;
huggingface_hub not exporting two error classes) are pinned with targeted casts
and `type: ignore` at the call site, where they are visible and greppable, rather
than a blanket relaxation that would hide real errors alongside them. The inert
override is gone, replaced by a comment recording why it never worked.

To stop the drift recurring, a local pre-commit hook now runs
`uv run --directory backend mypy app` on any change under `backend/app`. Local
rather than mirrors-mypy so it type-checks against the project's real resolved
dependencies instead of a hand-maintained second copy, and whole-package because
mypy's cross-module inference is what makes it accurate.

One change surfaced a latent issue. Giving `chat_completions` a return annotation
(`ChatCompletionResponse | StreamingResponse`) made FastAPI try to build a
response model from a union containing a `Response`, which it cannot; the fix is
the documented `response_model=None`. It was caught immediately by the unit tests
that load the gateway app, not left for deploy, which is the payoff of the
annotation existing at all. Verified: `mypy app` reports no issues over 118 files,
ruff is clean, and 272 unit tests pass.

### The last resource guardrail: a wall-clock generation deadline

Auditing ROADMAP §120 against the code found the item mislabelled rather than
missing. Of the four guardrails it lists, three were already built and wired:
the concurrency cap (`SemaphoreConcurrencyLimiter`, held for the whole generator
in `RouteChatRequest`), the `max_tokens` output ceiling (min of the caller's
request and our cap, pushed to Ollama's `num_predict` so the model stops at the
source), and cancel on disconnect (`aclosing` throughout, so the adapter closes
its upstream HTTP request). A fourth, the per-request context bound, was wired
too, closing the `max_context_length` setting that an earlier review had flagged
as configured and read by nothing. Only "timeout" was partial: the adapter has a
per-read HTTP timeout, but nothing bounded the total wall-clock time of a
generation.

That gap is narrow but real. The token ceiling bounds a stream producing at a
healthy pace, and the per-read timeout bounds a stalled one (no bytes for the
interval). The uncovered case is a stream that keeps producing slowly enough to
stay under the read timeout yet never reaches the token cap, which on unified
memory near swap can hold one of only two concurrency slots for hours. With no
edge protection that is a genuine, if edge, denial-of-service lever.

So `RouteChatRequest._generate` now checks a wall-clock deadline in the yield
loop and cuts the stream with `finish_reason=length`, the same honest signal the
token-ceiling truncation already uses, so an OpenAI client is not told the model
finished. The deadline is `generation_deadline_seconds` (default 600, zero or
negative disables it, matching the heartbeat convention). Elapsed time comes from
an injected `monotonic` callable rather than the wall-clock `Clock`, for two
reasons: an NTP step must not move a live generation's deadline, and the seam
lets the deadline be tested without any real waiting. Two unit tests drive it: a
slow runtime that advances the injected clock ten seconds per token trips a 25s
deadline after three tokens and releases its slot, and a zero deadline falls back
to the token ceiling. 272 unit tests pass; ruff is clean and mypy shows no new
errors over the pre-existing baseline.

What waits for the Mac Studio is the same boundary inference has always had: the
guardrail's arithmetic and the truncation contract are exercised now against an
injected clock, but a real slow generation on the GPU is only observable there.
The pre-launch checklist item in security.md §14 that says to verify the
guardrails in practice still stands.

### Multi-tenancy, the isolation boundary made real (Phase 2)

The third Phase 2 item, and the most invasive: the platform was single tenant and
said so, and this makes the boundary exist. Every `users`, `api_keys`,
`usage_records` and `audit_log` row now carries a `tenant_id`, a migration
backfilled the existing rows into one default tenant, and the tenant-scoped
repositories filter every read and stamp every write by it.

**The filter lives in the adapter and is taken from the actor, never the caller,
which is the whole of section 7.3.** A tenant-scoped repository is constructed
with a tenant id, and the di builder takes that id from the authenticated actor
(`users.tenant_id` on the admin entrances, `api_keys.tenant_id` on the gateway),
so a use case receives an already-scoped repository and cannot read another
tenant's rows or forget to say which tenant it means. The use cases themselves
barely changed, which is the payoff: the boundary is structural, not something
each handler remembers. A scoped read adds `WHERE tenant_id = :t`; a scoped write
stamps the repository's tenant onto the row regardless of what the entity carried;
and the targeted updates (revoke, disable, edit) carry the tenant into their
`WHERE`, so a scoped operation cannot touch another tenant's row even by its id.
The integration test proves all of this against a real Postgres, which the unit
fakes cannot, because they have no filter to enforce.

**A few paths are deliberately unscoped, and each resolves a principal before any
tenant is known.** Authentication looks a user up by a globally-unique login, the
session resolver looks one up by id, the gateway looks a key up by its handle, and
bootstrap counts every user platform-wide. Reading exactly the one row a unique
handle names is not a cross-tenant enumeration, and the tenant is then read from
that row. These use an explicit `.unscoped()` repository, so the choice is visible
and greppable rather than a forgotten default.

**A review of these three Phase 2 commits caught where the scoping went one step
too far.** The invite flow's duplicate-login check had been left on the
tenant-scoped repository, but a login is a platform-global namespace: `users.login`
is globally unique, so a login already taken in another tenant would slip past a
scoped check and fail at the unique constraint as a bare 500 rather than the clean
409 the check exists to give. `get_by_login` is now never tenant-scoped, for the
same reason authentication resolves it globally: it answers only "does this login
exist anywhere", and the row it returns carries its own tenant. The review's other
findings were hygiene rather than logic: a docstring displaced onto the wrong
field, a stray UTF-8 BOM and mangled em-dashes that a scripted `.unscoped()` edit
had left in four integration test files, an unhandled promise rejection in the
tenant-create dialog, and a duplicated onboarding-link builder now shared between
the users and tenants routers.

**Shared infrastructure stays platform-global.** `models`, `nodes` and
`routing_policies` are the compute the tenants share (one loaded model serves
everyone), so they carry no tenant and are managed by any admin. Tenants
themselves are platform-global too: managing them is an admin operation, not
tenant data.

**Minimal but usable tenant management.** `ManageTenants` creates a tenant and,
in the same call, mints its first administrator's invitation into that new tenant
(a tenant with no admin cannot be populated), and lists tenants. The ordinary user
invite lands in the inviting admin's own tenant, stamped by the scoped repository.
There is no platform-super-admin versus tenant-admin split yet: admins are
platform-trusted, which suits a single research centre, and the stricter hierarchy
can follow if a genuinely external tenant appears. The knowledge base, the main
tenant-scoped consumer, is not built yet; it plugs into this boundary when it is.

One structural change made it clean: `current_actor` and `current_session` moved
from the identity middleware into `di.py`, so the scoped-repository builders can
depend on the actor without the middleware and the composition root importing each
other in a cycle. The middleware re-exports both, so routers and the entrance apps
are untouched.

Verified: the migration round-trips (it seeds and backfills the default tenant, so
the column is NOT NULL with no data-migration window); the account split is
undisturbed (the gateway's schema-wide SELECT already covers the new table, and it
still has no write on `api_keys`, `users` or `tenants`); 270 unit tests pass, with
four new for `ManageTenants` and a five-case integration test pinning the isolation
property against real Postgres; ruff and mypy are clean on the new code; and the
frontend gained a `features/tenants` screen (list plus a create dialog that shows
the first admin's one-time link) through `tsc`, `eslint` and `next build`.

### Node management, and the SSRF guard that had to ship with it (Phase 2)

The second Phase 2 item, and the one the security document had been holding a
rule over: a node write endpoint may exist only if the SSRF guard ships with it,
because a node's `address` is a value the platform makes outbound requests to,
and an attacker who can register `169.254.169.254` or `127.0.0.1` has turned node
management into internal probing (§7.2). Until now the rule was satisfied by the
absence of a write path: the single node was seeded from configuration and no
endpoint accepted an address. This change adds the write path and the guard
together.

**The guard is the core, and it validates on the way in, not only on the way
out.** `adapters/http/egress_guard.py` resolves an address and requires every
result inside the tailnet range (`100.64.0.0/10` and the Tailscale IPv6 ULA).
One range is the whole rule: loopback, link-local, the RFC 1918 LAN, and the
cloud metadata endpoint are all outside it, so none has to be enumerated. A
literal IP is checked without a DNS lookup, which also means the value stored is
the value connected to; a hostname is resolved and rejected if any answer falls
outside the tailnet, so a name that resolves partly off-net cannot pass on the
strength of one good record. The check runs at every node write, so an address
that could never be reached safely is refused before it is stored rather than
surfacing later as a failed probe. It reaches the use case through
`EgressGuardPort`, not a direct import, the same discipline that keeps
model-reference validation off the application layer.

**Status stopped being an assumption.** Phase 1 wrote every node `online` at
provision and never looked again, which made a routing requirement of
`node_status: [online]` inert, since it always held. A `NodeHealthPort` now
observes status by probing the runtimes a node declares (online when all answer,
degraded when some do, offline when none does or none can be probed), and a
heartbeat in the admin application runs it on an interval. So a policy that
demands an online node actually stops routing to one whose runtime has gone away.
The heartbeat runs in the admin app rather than the gateway because the §6
least-privilege split lets the gateway write only `usage_records`, never
`nodes`; both admin entrances run it, which is why the write is a targeted,
idempotent `set_status` and why a status is written only when it changed. The
loop sleeps before its first sweep, so the many tests that open and close the
admin lifespan cancel it before it ever touches the database. Single-node scope
is stated plainly in the adapter: the runtime adapters point at the configured
host runtime, so the probe is accurate for the one node they can reach and a
second node will need per-node runtime endpoints, deferred with multi-node.

**Deletion is guarded too.** `models.node_id` is a foreign key, so deleting a
node with models attached would fail as an IntegrityError at flush, which in
FastAPI is after the response has gone and has nowhere to report. The use case
refuses it first, naming the models, and the same shape gives a duplicate node
name a clean 409 instead of a unique-violation 500, matching how `ManageModels`
already reports a taken alias. Registration and removal are audited, as §12
requires.

`GET /nodes` moved from the models router to a new `routers/nodes.py` carrying
the full lifecycle: the read the model form needs plus register, edit, delete,
and an explicit health check for the UI's refresh action. The frontend gained a
`features/nodes` management screen (table with live status, a create/edit form
whose address field is validated server-side, delete, and check-now) and a nav
entry. The stale "node management is Phase 1 read-only" comments across the
models feature were corrected rather than left to mislead.

Verified: 27 new backend tests (the egress guard against loopback, LAN, metadata
and rebinding; `ManageNodes` for the guard running before a store, the
attached-models delete refusal, status as the probe's observation; the heartbeat
writing only changed statuses), the full unit suite at 266 passing, ruff and
mypy clean on the new code, and the frontend through `tsc`, `eslint`, and
`next build` with the `/nodes` route generating. Real probing of a runtime still
waits for the Mac Studio, the same boundary inference has; the guard, the write
rules, and the heartbeat's change-detection are exercised now.

### The second runtime adapter, which is the real test of the layering (Phase 2)

The first Phase 2 item, and the one worth doing first because it answers a
question the rest of Phase 2 assumes: did the hexagonal layering actually buy
what it was chosen for. The stated pass criterion was that adding a runtime
touches no use case and no interface. It held. The diff is one adapter file
(`adapters/runtime/mlx_adapter.py`), its per-runtime reference grammar
(`adapters/runtime/hf_validation.py`), and three wiring points: one entry in
`build_runtimes`, one setting, one Compose mount. `application/use_cases` and
`interfaces` are untouched, and the domain is too, because `RuntimeKind.MLX`
already existed. `route_chat_request` resolves the adapter from the model's
`runtime` field through the same dict it always did.

The value of the exercise was less the wiring than the three places MLX is
genuinely unlike Ollama, each of which the port absorbed without bending, but
only after a real decision.

**MLX has no download-with-progress endpoint, and its download lands somewhere
Ollama's never had to.** Ollama's daemon pulls on the host and streams NDJSON
progress back, so the adapter only relays. MLX models are HuggingFace snapshots
and `mlx_lm.server` downloads them lazily with no progress stream. So `pull`
here does the download itself, via `huggingface_hub` in a worker thread, and
reports real byte progress by polling the cache while it runs. The subtlety that
forced a decision: a download run inside the container would land in the
container filesystem, which the host-native server cannot read. The bytes have
to reach the host cache. So HF_HOME is a bind mount onto the host's HuggingFace
cache, and this is the one place in the deployment a container writes to a host
path. That does not contradict the section 0.1 rule that runtimes are not
containers: the rule is about GPU and compute, and a snapshot download is file
I/O whose only constraint is where the bytes end up.

**`mlx_lm.server` has no unload, so `unload` refuses rather than lying.**
Reporting success would move the registry to DOWNLOADED while the weights are
still resident on the host, and the memory budget would then stop counting a
model that is still occupying memory, admitting a later load that should be
refused. That is precisely the unified-memory over-commit the section 4.3 budget
exists to prevent. The adapter raises `ModelStateConflictError`, and
`ManageModels.unload` already does the right thing with it: the model is left
LOADED, which is the truthful state, and the operator gets a 409 that says the
runtime cannot evict. A silent no-op would have been the dangerous option, not
the convenient one.

**The token count is only authoritative at the end**, in the terminal usage
frame, exactly like Ollama's `eval_count`. Chunks are counted one apiece as they
stream so a disconnect still bills what was produced, and the final frame emits
only the difference rather than the whole figure, which would double-count.

The reference grammar is per-adapter, as `ModelRuntimePort.validate_ref` intends:
a HuggingFace repository id, not Ollama's `namespace/name:tag`. It rejects `..`
and anything that is not a plain repo id at the boundary, because the value
reaches `snapshot_download(repo_id=...)` and a repo id carrying path traversal
is the section 7.1 concern in a different runtime's clothing.

Verified with 12 port-conformance tests against a stubbed transport and stubbed
download seams, no MLX and no GPU in the loop: the OpenAI SSE stream maps to
`CompletionChunk` and reconciles the token total, the upstream request is closed
on client disconnect (the guarantee the streaming contract rests on), a bad
reference is rejected before any network call, a stream that ends without a
terminal frame raises rather than reporting a clean stop, `unload` refuses
without touching the network, and `pull` climbs monotonically from starting to
success. The full unit suite is 237 passing; ruff and mypy are clean.
`huggingface_hub` is imported lazily inside the download seams only, so the
inference path neither pays its import cost nor depends on the library being
present, and the mypy override mirrors the existing zxcvbn one.

What waits for the Mac Studio is real MLX inference and a real download, which
need Apple Silicon and cannot run on the Windows dev machine, the same boundary
Ollama inference has always had. The architecture claim itself does not wait for
that: it is the zero use-case, zero-interface diff plus the port-conformance
suite, and both are done now.

### A production smoke test on the dev machine, which moved the deploy risk down

Ran the whole stack once on Windows under `ENV=production` with generated
(non-placeholder) file secrets, which exercises the Compose wiring the account
split had only been structurally checked against. It held: `migrate` exited 0
having run the migrations and logged `database roles provisioned:
nexus_gateway(gateway), nexus_admin(admin)`, so `db_roles` created both roles
from the mounted URL secrets and applied their grants in the real flow. All
eight containers came up; postgres, redis and the gateway reported healthy, and
`/readyz` returned 200 on the gateway and both admin entrances. `pg_stat_activity`
showed the gateway connected as `nexus_gateway`, not the owner. And the boundary
is enforced by the deployed database, not just by the earlier unit and
integration tests: as `nexus_gateway`, `SELECT api_keys` and an `INSERT` into
`usage_records` both succeed, while `INSERT INTO api_keys` is refused with
`permission denied for table api_keys`.

What this does not cover, and still waits for the Mac Studio: the country filter
(run with `ALLOWED_COUNTRIES` empty, since there is no GeoLite2 database here),
GPU inference, `tailscale serve`, and nginx. The production config validators,
the role provisioning, the per-account connections, and the grant enforcement
are no longer first-run risks.

### A first-deploy runbook, and the GeoLite2 mount it turned up

Compiling the Mac Studio pre-deploy checklist ([runbooks/first-deploy.md](./runbooks/first-deploy.md))
surfaced a blocker: the Compose file mounted no `/data` into the backend
services, but `build_geo_filter` refuses to start in production when
`ALLOWED_COUNTRIES` is set and the GeoLite2 database is missing. So the stack as
written would have failed to boot on the first real deploy. The `x-backend`
anchor now bind-mounts `./data` read-only, and the runbook step is to drop
`GeoLite2-Country.mmdb` there. The runbook is written for someone who has not
used macOS: first boot, Homebrew, Docker Desktop, native Ollama bound to
loopback, Tailscale and `tailscale serve`, the secrets, and the §14 checks that
must be tested rather than assumed.

### The database account split, and secrets moved to file mounts

The last functional-to-operational Phase 1 item, and the deeper half of the
defence the network split (§15.5) only started. Until now every backend service
connected as one account that owns the schema, so a compromised gateway that
could not reach the admin socket could still write `api_keys` and mint itself a
key. Now there are three Postgres accounts: the gateway reads every table and
writes only `usage_records`; the two admin entrances share an account with full
DML and no DDL; the owner holds DDL and is used only by `migrate`.

The roles are provisioned in code (`infrastructure/db_roles.py`), run by the
`migrate` job after the schema exists. Three decisions carried it.

The grants are **declarative, not additive**: the gateway's table privileges
are revoked and re-granted on every deploy, so its writable set is always
exactly `GATEWAY_WRITABLE_TABLES` regardless of what a previous run left, and a
table added by a later migration is regranted without anyone editing SQL. The
one writable table is named in code, where it is under review, rather than in a
deployment file.

The account **name is taken from each service's own connection URL**, so the
URL secret is the single source of truth for both the name and the password;
this module never invents a name the deployment did not commit to. `migrate`
connects as the owner and reads the gateway and admin URLs to create those two
roles.

And the SQL is **built as text with hand-quoted identifiers and literals**,
because `GRANT`, `CREATE ROLE`, and a role password are DDL that no driver
parameterises. The quoting helpers are the standard minimal escapers, safe
under `standard_conforming_strings`; role names are additionally constrained to
a strict pattern because a name is an identifier we control. `exec_driver_sql`
rather than `text()` runs them, so a colon in a generated password is not read
as a bind parameter. Ten unit tests pin the security property directly: the
gateway is granted no write anywhere but `usage_records`.

Alongside it, secrets moved from `env_file` to Docker **file mounts**. This was
forced by the split as much as chosen: an environment variable outranks a file
secret in pydantic-settings, so a value left in `.env` would silently override
the mounted one. `.env` now carries only non-secret configuration; every
credential is a file under `./secrets` (git-ignored, with `.example` templates
and a README), mounted at `/run/secrets` and read through `secrets_dir`. Each
service mounts only what its role needs, except that the four crypto secrets go
to `migrate` too, because it calls `get_settings()` and production refuses the
placeholders. Postgres reads its password through `POSTGRES_PASSWORD_FILE`;
redis, which has no such convention, reads the file in its command.

**What is verified, and what waits for the deploy.** The security property
itself is now proven against a live Postgres 17: an integration test
(`tests/integration/test_db_role_grants.py`) provisions the two roles the way
`migrate` does and asserts the server refuses the gateway account an INSERT into
`api_keys`, `users`, `routing_policies` and `audit_log`, while keeping its reads
and its `usage_records` write, with the admin account as the positive control.
`docker compose config` resolves the secret mounts as intended and the unit
suite passes. What still waits for the Mac Studio is the full compose wiring end
to end: `migrate` creating the roles from the mounted URL secrets, and each
service connecting as its own account rather than the single-account
`AUTH_MODE=dev` default the Windows machine uses.

### A routing policy editor, so the one thing that makes the gateway serve is no longer curl-only

The routing policy API was complete and audited but had no screen, so the
single thing that decides what the gateway serves for a capability was
configured by hand. `features/routing-policies` now carries a table (one row
per capability, candidates summarised highest-priority-first to match how the
gateway evaluates) and a candidate editor: a `useFieldArray` over the candidate
list, each with a model alias, a priority, and the structured requirement as
checkbox groups over node status and model state plus an optional free-memory
floor.

Three decisions worth the note. The requirement stays a closed set of
structured fields rather than an expression box, exactly as the domain demands
(ARCHITECTURE.md section 2.4): the same reason the backend refuses one is the
reason the form does not offer one. Creating a policy is only offered for
capabilities that do not already have one, because a save is a full replacement
keyed by capability (`PUT`) and a "create" over an existing capability would
silently overwrite it. And the memory floor is backed by a text input where a
blank field means "no floor" and becomes null, kept out of a plain
`z.coerce.number()` because coercing an empty string yields zero, which would
read as a real 0 GB requirement rather than the absence of one; the schema test
pins that.

The response schemas parse against the same enums the models feature uses, so a
node status or model state the frontend does not know surfaces as a parse
failure rather than a candidate that silently never matches. Verified through
`tsc`, `eslint`, `next build` (the `/routing-policies` route generates), and ten
new schema tests.

### A frontend test runner, on the units where a defect is a security defect

The one Phase 1 gap most worth closing first, because the type checker had been
the only gate and two of the three defects it let through were security
defects. Vitest with jsdom, and 44 tests over the pure logic the adversarial
review had already found holes in: `safe-redirect` (the backslash open-redirect
that survives a prefix check), the chat SSE schema and reader (the OpenAI
envelope that an earlier flat schema silently stripped to nothing, plus the
error, malformed, truncation and abort frames), `api-client` (the CSRF header
attached only on mutations and only when the cookie is present, the 401 that
becomes an `UnauthorizedError` and an event, and the absence of any
`Authorization` header), and the password schema's length-and-strength
threshold.

Two decisions worth the note. The `@/` alias is resolved in `vitest.config.ts`
directly rather than through a tsconfig-reading plugin, so the test setup does
not depend on how that plugin parses config. And the jsdom environment runs on
`https://localhost/` because the CSRF cookie carries the `__Host-` prefix,
which jsdom's cookie jar correctly refuses to store over http, so a test on
http would have been asserting against a control that the browser also drops.
The test files are excluded from `tsconfig.json` so `next build` does not try
to type-check them.

What is not covered: nothing renders a component or drives a browser yet. The
sign-in and enrolment screens, which are the surface where a defect is a
security defect, are still only reachable through their schemas and hooks in
these tests. Playwright is the deferred increment, recorded in `ROADMAP.md`
Phase 3.

### Closed the network exposure the review left standing

The sharpest finding, recorded as accepted risk §15.5, is now fixed rather than
carried. The gateway and the tailnet admin entrance shared the `app` Compose
network, and the tailnet entrance trusts `Tailscale-User-Login` outright, so a
compromised gateway could reach `admin-tailnet:8001` by service name and forge
an administrator. Socket binding, the design's stated isolation, protects the
host-published port but not the Docker service name.

The single `app` network is split so the gateway shares none with either admin
entrance. The data plane gets `gateway-data` (internal, for postgres and redis)
and `gateway-egress` (for the host runtime); the control plane gets `admin-data`
and a per-entrance control network carrying the frontend and its admin API.
postgres and redis are the only members of both database segments, which is
safe because they accept connections and never open one — a shared datastore is
not a shared path. The same split also stops the internet-facing public frontend
from reaching the tailnet entrance.

The invariant is not a comment but something `docker compose config` can be
asked: the intersection of the gateway's networks with each admin entrance's is
empty. What remains open is the deeper §6 defence, per-service database
credentials, so a compromised gateway cannot read or write the control plane's
tables; the forged-header path specifically is gone.

### Five adversarial reviews, and the twenty-eight defects they found

The admin API was attacked by five independent reviews, each on one surface:
authentication and sessions, authorization and data exposure, persistence and
concurrency, the model lifecycle and jobs, and the frontend/backend contract.
Their findings were verified before acting, and the verification mattered:
several passed against the in-memory fakes while being wrong in Postgres, and
one review's headline claim needed a real database to confirm.

Most of these were introduced by the two admin-API commits above. The fixes
are in four commits after this one; what follows is why they existed.

**Four defects made the system unusable.** Every admin call 404'd, because the
Next.js rewrite keeps the `/admin` prefix and the routers mounted at the root;
nothing caught it because every test called the ASGI app directly, so they
exercised handlers and never the contract. No API key could be issued, because
the expiry field is an `<input type="date">` that sends a naive datetime and
comparing it to an aware `now` raised `TypeError`, a bare 500. Both create
paths destroyed their one-time secret, returning the unsaved entity whose
`created_at` is null, which the frontend's parse rejects after the row exists,
taking the plaintext key and the invitation link with it. And a compromised
gateway could authenticate as an administrator: it shared the `app` Docker
network with `admin-tailnet`, which binds `0.0.0.0` and trusts
`Tailscale-User-Login` outright, so §5.1's "isolation by socket binding" held
for the host-published port but not the bridge. (Closed since, by the network
split described in the entry above.) That last one is the sharpest lesson:
making the tailnet entrance a full API is what opened it, and it was invisible
while the entrance mounted only health.

**Controls the design claimed and the code did not deliver.** The login
throttle refused on a per-account count alone, which is the hard lockout §5.3
forbids because it is a denial-of-service lever against a named person, and a
successful login cleared the per-address counter so one valid account could
reset it. A `user` could mint an unmetered gateway key, because the gateway
reads `rate_limit_rpm <= 0` as no limit and quota zero as no quota, and expiry
had no upper bound. The country filter was absent from the public admin
entrance while four places said it was present, one of them a router comment.
CSRF was absent from the tailnet entrance on the false premise that it has no
ambient credential, when `tailscale serve` attaches the identity header to any
request a hostile page can provoke.

**State and data corruption.** A failed load wrote `error` and then raised,
and the raise rolled the write back, so a half-resident model read as
`downloaded` and the budget under-counted it. The three transient states were
permanent dead ends after a crash, escapable only by SQL. The download task
held one transaction open for the whole multi-hour pull. Two full-row `save`
calls could revert a concurrent revoke or disable. Each of these had a passing
test that used an in-memory fake with no transaction and no row lock, which is
why the new coverage runs against real Postgres.

The lower-severity findings — a `user` role wider than §5.2, a challenge that
outlived a disable, two CSRF paths that 500'd, `GET /api-keys` loading full
user entities, a double SSE terminal frame — are in the fourth fix commit.

**What was checked and found sound, so it is worth recording as tested:**
session fixation and the watermark invalidation, TOTP replay across every skew
case, the bootstrap atomicity, enumeration resistance, the model-reference
grammar (`fullmatch` closes the trailing-newline hole and the registry
allowlist rejects `hf.co.evil.com`), the streaming slot released within a
millisecond of disconnect, and the migrations round-tripping with zero ORM
drift.

**Residual items, accepted or deferred rather than fixed:**

- **Commit-after-response.** FastAPI commits the request transaction after the
  response is sent, so a create returns `201` with the body before the INSERT
  is attempted; a constraint violation then has nowhere to report. The
  narrow trigger is a TOCTOU on a uniqueness check under concurrent identical
  creates. Structural to how the yield-dependency session works; not changed.
- **A model stuck in a transient state by a bare container crash** (not a
  `compose` restart) is reconciled only at the next deploy, because
  provisioning runs in the `migrate` service. `restart: unless-stopped`
  brings the container back without re-running it.
- **The concurrent-load budget race** is narrowed, not closed: `LOADING` is
  now committed independently and counted, so the window is milliseconds
  rather than the whole load, but two loads landing in that window can still
  both pass. A node advisory lock would close it and is deferred.
- **`session_signing_key`** is enforced as a production secret and read by
  nothing: sessions are opaque Redis ids by design. Left in place, noted here.

### The rest of the admin API

Models and their lifecycle, downloads as background jobs, routing policies,
API keys, the remainder of `/users`, the dashboard, and `/admin/chat`. An
integration test now walks Phase 1's stated goal in one sequence: register a
model, bind a routing policy to it, issue a key, and read the dashboard back.

**A gap that only appeared once the endpoints existed: nothing could create a
node.** Models attach to one, and `security.md` §7.2 says a node write
endpoint must ship with the SSRF guard, because a node record is an address
the platform will then make outbound requests to. So a fresh deployment could
register nothing at all. Phase 1 is single-node by definition, so the node is
named in configuration and written at admin start instead. That keeps the rule
intact rather than working around it: nothing accepts an address from a
caller, and the write endpoint still waits for the guard.

**`last_used_at` is derived, not stored.** The frontend wanted the column, and
maintaining one would mean the gateway writing to `api_keys` on every request
— which is precisely what the least-privilege split in §6 exists to prevent.
The same fact is already in `usage_records`, written by the account that
should write it and indexed on `(api_key_id, at)`, so it is one aggregate at
list time. The dashboard's 24-hour figures come from there too; the frontend
schema had them as Phase 2, but Phase 2 is live metrics from Prometheus, and
request and token counts have been in the database since Phase 1.

**Model reference validation moved onto the port.** Registering a model needed
the same check the Ollama adapter already performs, and importing it into the
application layer would have been the layering violation fixed a day earlier.
Putting it on `ModelRuntimePort` is the better answer anyway: what counts as a
reference differs by runtime. Ollama takes `namespace/name:tag` from a small
set of registries, MLX takes a HuggingFace repository id, vLLM will take a
path. A shared helper would have to be the union of all of them, which is no
grammar at all.

**Where the state machine can lie.** Most of the model tests exist for
failures that leave a plausible-looking row. A failed load writes `error`, not
`loaded`. A failed *unload* writes `loaded`, not `error`, because as far as
anyone knows the weights are still resident and the memory budget has to keep
counting them. A crashed download writes `error` in a `finally`, since a row
stuck in `downloading` is one no later operation will touch and nothing sweeps
up. Deleting a model whose alias a routing policy names is refused: no foreign
key enforces that binding, and without the check inference starts answering
"no available model" with nothing in the registry to explain why.

The download job runs detached, in its own transaction, because the request's
session is closed the moment the response is sent. It does not survive a
restart, which is accepted rather than solved: a durable queue is a second
piece of infrastructure to run for one operation, and keeping progress in the
cache means an interrupted pull is visibly stuck rather than silently gone.
The set of strong task references in `infrastructure/jobs.py` is not
decoration — `asyncio` holds only weak ones, and a task nobody keeps can be
collected mid-await with nothing logged.

Two smaller things. SSE framing moved into one module, so the gateway and the
chat panel cannot drift into two envelope shapes; that drift is exactly what
made the chat panel display nothing the first time. And the runtime port now
declares `AsyncGenerator` rather than `AsyncIterator`, because every consumer
wraps it in `aclosing()` and only the former promises `aclose()` — the
promise the whole streaming contract rests on.

---

## 2026-07-24

### Admin authentication, end to end

Both admin entrances now resolve an identity, and a fresh deployment can get
from an empty database to a signed-in user on the public entrance. That path
is covered by an integration test which runs bootstrap, invitation, TOTP
enrolment, login and sign-out against a real Postgres, because none of the
unit tests would notice a composition root that wired the wrong adapter in.

Built: argon2id, pyotp, Fernet encryption for the TOTP secret, token issuing
and recovery codes, the audit adapter, sessions on the existing `CachePort`,
CSRF, the two identity resolvers, and the use cases behind them.

**Authentication was built before the CRUD, and the ordering paid off twice.**
Both times the shape of the existing schema rejected the first design rather
than accepting it quietly.

**The check constraint refused the obvious place to keep a pending TOTP
secret.** Enrolment spans two calls: one renders the QR, the other verifies a
code from the authenticator that scanned it, so the secret has to survive
between them. Writing it to the user row looked right, since
`can_use_public_entrance` already requires a password as well and a row with
only a secret authenticates nothing. But `users` carries
`(password_hash IS NULL) = (totp_secret IS NULL)`, added in the last review,
and it rejected the write. The constraint was right: a half-finished enrolment
is not an account. The candidate now waits in the cache for minutes, which is
better on its own terms. Abandoning a re-enrolment leaves the working
authenticator untouched, an unproved secret exists nowhere for 72 hours, and
the unauthenticated `begin` endpoint no longer writes to `users` at all.

**Creating an account and its invitation in one transaction violated a foreign
key.** The ORM models declare foreign key columns but no `relationship()`, so
SQLAlchemy's unit of work has no dependency graph to order a flush by, and
with `autoflush=False` — which production uses deliberately — the invitation
INSERT was emitted before the user it referenced. `PostgresUserRepository.save`
now flushes. This is the mirror of the defect found last time, where the tests
relied on an implicit flush that production does not do; here the production
code relied on an ordering nothing guarantees, and only a real database could
say so.

**A test-only hang that is worth recording.** The first end-to-end test opened
both entrances as concurrent `TestClient`s. It hung forever. `init_engine`
holds one engine per process and asyncpg connections belong to the event loop
that created them, so the second client's requests waited on futures from the
first client's loop. Production never meets this, because the entrances are
separate containers. The test opens them one after the other.

**And a latent ordering bug in the suite itself.** A unit test configures an
unreachable database to prove `/readyz` can fail, and cleared the `lru_cache`
on `get_settings` going in but not coming out. `alembic/env.py` overwrites
`sqlalchemy.url` with `get_settings().database_url`, so every integration test
that ran afterwards migrated against a dead host. It had never shown up
because the integration suite is skipped unless `TEST_DATABASE_URL` is set,
and the two had not been run together.

**Three decisions worth their reasoning.**

`PasswordHasherPort` is async, and the adapter runs argon2 in a bounded thread
pool. A hash occupies a core for tens of milliseconds, and login is
unauthenticated and behind no WAF, so a synchronous port would hand an
attacker a cheap way to stall every request in the process, including the ones
that would have rate limited them. anyio's default 40 threads at 64 MiB each
would then trade a CPU stall for an out-of-memory kill, hence the semaphore.

Audit rows are written in their own transaction. `session_scope` rolls back on
any exception, so an audit row sharing the request's session disappears
exactly when the request failed, and failures are what an audit log is for.
The cost is the mirror case, an audited action that later rolls back, which is
what `outcome` is for.

The entrances choose their identity resolver by dependency override, and the
placeholder raises. A branch on `settings.auth_mode` would have been a string
comparison deciding a trust model, which is the thing section 5.1 says the
isolation must not rest on. An application that installs neither resolver now
fails on its first authenticated request rather than defaulting to anything.

Two things changed outside the plan. `users` gained a `created_at` column,
because the frontend user schema already displayed one and no column existed.
And the invitation QR endpoint takes the token on its URL: the recipient is
not signed in, so there is no session to identify the enrolment from, and an
`<img>` cannot carry a request body.

Still absent, and the reason the frontend is not yet usable end to end: models,
routing policies, API keys, jobs, dashboard, `/admin/chat`, and the rest of
`/users`.

### Theme and progress tracking

Deep blue theme, a busy indicator, and this file.

The palette is computed rather than chosen by eye: `#1e40af` measures 8.72:1
against white, which clears AAA for body text, and dark mode moves up the ramp
to `#60a5fa` at 7.79:1 against the dark background rather than reusing a value
that would be unreadable there. Charts use a sequential ramp, because the
dashboard shows magnitude over time and a categorical palette would imply
categories that do not exist.

Two decorative elements adapted from Uiverse.io, credited in
[`ATTRIBUTIONS.md`](../ATTRIBUTIONS.md). Only two, and only decorative: that
collection is thousands of pieces by as many authors with no shared design
language and, being showcases, generally no focus or disabled states. Useful
for a spinner, wrong for anything a user operates.

**No logo.** A constructed wordmark and an N-as-routing-graph icon were drawn
and then discarded; the identity will come from elsewhere. There is no icon
asset in the repository, so the browser tab falls back to the framework
default until one is supplied.

### Everything the adversarial review found, fixed

Five independent reviews were run against the codebase, each attacking a
different surface. Their findings were verified before acting, which mattered:
the loudest one was wrong.

**The claim that did not survive verification.** A review argued that streaming
requests never commit their usage record, because FastAPI closes a
yield-dependency before a streaming response is produced. The reasoning was
sound and the conclusion was false for the installed version. An empirical test
showed both paths persisting. A second review found why: FastAPI 0.139 keeps
the dependency scope open until the response is sent, but the declared floor
was `>=0.115`, and versions in between do not. So the real defect was a
dependency range, not a design fault, and the fix was a pin plus the
regression test that had been missing.

**Live security holes, since the gateway is the only exposed surface.**
Scopes were computed and then never consulted, so any valid key could consume
the hardware regardless of what it was issued for. The per-key quota was dead
in two independent ways. `rate_limit_rpm` was stored end to end and enforced
nowhere. `TAILNET_IP` had no required-variable guard, so an unset value made
Compose bind the gateway to every interface, which was verified before and
after.

**The one worth remembering.** The quota read `tokens_used_today` off the key
repository through a `getattr` fallback that returned zero when the method was
missing. The method lives on a different class. The fallback had been written
to make the check stubbable in tests, and it was precisely what hid the
miswiring: the only object with that method was the test double, so the tests
passed while production never checked a quota at all. A defensive default
around a wiring mistake is worse than the crash it prevents.

**Frontend.** The chat could never display a reply: the frame schema described
a flat shape while the backend sends the OpenAI envelope, and zod strips
unknown keys rather than rejecting them, so every real frame parsed
successfully into an empty object. The login page was an open redirect via
`/\evil.example`, which the URL parser normalises to a second slash. One-time
secrets could be destroyed with the Escape key. `Me` carried no `id`, so two
callers substituted `login` and one of them left an admin able to delete
themselves.

**Persistence.** Single use was not single use: the atomic guard was correct
and its rowcount was discarded, so two requests reaching the same invitation
both believed they had claimed it. TOTP replay prevention compared a value
read earlier and wrote it back, which two concurrent requests both pass.
Invariants that existed only as Python properties are now check constraints.

**Documentation.** Several controls were described in the present tense and did
not exist. The worst was in `db.py`, whose docstring asserted that each service
connects with its own least-privilege account and that "the grants do the
enforcing", while Compose gives every service one account that owns the schema.
That is the same mistake `security.md` had already warned about for tenant
isolation: a claimed boundary stops people looking for the risk.

**Two defects were found by the new tests rather than by review.** Splitting a
use case into two generators reintroduced a missing `aclosing` one layer up,
caught immediately by the disconnect test. And aligning the test sessions with
production `autoflush=False` produced foreign key violations, because the tests
had been relying on an implicit flush that production does not do.

### Guardrails that were configured but never read

Four settings existed in `config.py`, in `.env.example` and in the
documentation, and were read by nothing.

`/readyz` returned hardcoded booleans, so it could never produce a 503, and its
test asserted only that the status was one of 200 or 503 and therefore passed
vacuously. Anything gating a rollout on readiness was gating on a constant. It
now probes the database, cache and runtime concurrently, each bounded by a
timeout, because a probe that hangs is worse than one that fails: the
orchestrator waits instead of acting.

The country filter did not exist at all. `geoip2` was a dependency,
`allowed_countries` and `geoip_db_path` were read by nothing, and
`CountryNotAllowedError` was defined and never raised, which is worse than
absence because a defined error implies a control. It now refuses to start in
production when its database file is missing, rather than silently serving
every country.

`max_context_length` was likewise inert, so a prompt of any size was accepted.
And `/docs` was gated on `not is_production`, but `ENV` defaults to development
and `.env.example` ships it, so a deployment that filled in its secrets and
left the top of the file alone was publishing its full internal schema.
Exposure is now an explicit opt-in, so forgetting fails closed.

### Phase 1 backend, end to end

Postgres repositories and the first migration, the Ollama adapter, and the
chat path wired from socket to SSE frames.

The runtime is stubbed in the end-to-end tests and nowhere else. Inference
needs a GPU and can only be verified on the Mac Studio; everything between the
socket and the port boundary is real, including the routing policy read from
the database.

Three defects found while building: `.env.example` shipped a `DATABASE_URL`
whose password did not match `POSTGRES_PASSWORD`, so a fresh checkout could not
connect; `alembic/script.py.mako` was missing, so revision generation failed
outright; and `key_id` was an independent random value that appeared nowhere in
the token, leaving verification no way to find the row short of scanning every
key.

### Scaffold

Backend hexagonal skeleton, Next.js management UI, Compose topology, AGPL-3.0.

The hardware constraint that shaped the deployment: **model runtimes cannot run
in Docker on macOS**, because containers there have no GPU access. A
containerised Ollama would be CPU-only and MLX would not run at all, which
defeats the point of the machine. Runtimes are native under launchd; containers
reach them through `host.docker.internal`.

Three image-build defects that only appeared by actually running
`docker compose build`, all of which `docker compose config` validated happily:
four services declaring `build:` while sharing one tag raced to write it,
`package.json` had no `packageManager` for corepack to activate, and neither
build context had a `.dockerignore`, so the host's `node_modules` and a Windows
x86 `.venv` were being copied into Linux images.

### Licence: AGPL-3.0

Chosen to match the sibling project, Smart-MultiAgent-Platform, so code can
move between them without a licensing question, and held by the research
centre rather than an individual so that people moving on does not create a
reattribution problem.

Section 13 is why this is not merely administrative here. Unlike the GPL, the
AGPL treats network interaction as distribution, and this platform exposes both
a public inference API and a public management UI. Anyone reaching those
endpoints is entitled to the source of the running version, which makes it an
operational obligation: keep the deployed revision published and identifiable,
not just ship a LICENSE file. Recorded in `deployment.md` section 8.1 for that
reason.

### The public entrance, and the risks accepted with it

The original plan was Cloudflare Tunnel. It was dropped after checking two
things rather than assuming them.

`rcsl.online` is served by Gandi nameservers and the domain is actively
receiving mail through Gandi, so moving nameservers touches mail delivery on a
shared domain maintained by someone else. And Cloudflare's free tiers fix the
origin response timeout at 100 seconds, which streaming survives but a long
non-streaming completion does not.

So public traffic goes through the existing openresty proxy at NTNU instead. A
wildcard DNS record already points every subdomain there, so no DNS change is
needed; what is needed is that the proxy host joins the tailnet and forwards
two hostnames. Three consequences were accepted deliberately and are recorded
in `security.md` section 15 with the conditions that should trigger revisiting
them: inference traffic passes through a third party in plaintext, there is no
edge WAF or DDoS protection, and the country filter is bypassable by anyone
with a VPS in the right country.

The second of those is why the resource guardrails matter more here than they
would behind a CDN. They are not one layer of several; they are the only one.

### Architecture documents

Six documents, and the decisions behind them.

The one that shaped everything else: the gateway and the admin API must be
separate containers, because the isolation has to come from socket binding
rather than from a path rule in a reverse proxy that one typo could undo. That
in turn made the two admin entrances separate ASGI applications, since the
tailnet entrance trusts an identity header outright and sharing a socket with
the public entrance would let a forged header grant administrator access.

Authentication moved from OIDC to invitation-only local accounts with mandatory
TOTP, on the reasoning that the platform was already invitation-only in effect
(the `users` table gates access, not the identity provider), so the real choice
was who verifies the password. The trade is explicit: no external dependency
and no account an administrator did not create, in exchange for owning password
storage, reset, lockout and second-factor handling permanently. Mandatory TOTP
is what makes that trade acceptable.

A hardware constraint found while writing these, not while coding: model
runtimes cannot run in Docker on macOS, because containers there have no GPU
access. It contradicted the stated goal of keeping the host clean and was
non-negotiable, so the documents changed rather than the plan.

---

## Where things stand

Phase 1's functionality is complete. Inference, authentication on both admin
entrances, and the management API are all built and tested, and every screen
in the frontend now reaches a real backend. The remaining Phase 1 items are
operational rather than functional.

**The Mac Studio is deployed and serving.** The first `docker compose up` ran on
2026-07-26; `migrate` provisioned the two least-privilege roles and the live
database enforces them, GPU inference runs at 100% GPU, and a chat completion
goes end to end through key verification, quota, the proxy check, the country
filter, the routing policy and back out to a usage record. The tailnet
management entrance is reachable and every screen works against the real backend.
The backend suite runs here too: 359 tests on Python 3.12 against a real
Postgres 17.

What is still unverified, and by what — **this paragraph is a summary and has
drifted from the dated entries below more than once; where they disagree, they
win**:

- **nginx and the network path to the public entrance**, which wait on the NTNU
  proxy administrator. The entrance's *application* is no longer part of this:
  its full login flow — password, TOTP, session, logout — was driven end to end
  on 2026-08-02 (PROGRESS 2026-08-02). What is untested is everything between a
  browser on the internet and that socket.
- **MLX**, which has an adapter and no model registered against it.
- The **unattended-recovery chain** is no longer on this list, and the earlier
  version of this paragraph said "the repair not yet through a boot" for a week
  after that stopped being true. Both of the reconciler's repair paths were
  exercised by real boots with injected faults on 2026-07-26 (21:05:31 and
  21:52:14). What remains is the **external dead-man's switch**: a monitor on the
  host it watches cannot report that the host is off.

**On the recovery chain specifically, because it is the item most likely to be
misread.** Four boots on 2026-07-26 found two independent faults, and the second
one is the reason the count above says "failed it" rather than "passed three
times".

The first: Docker Desktop drops the port forwards naming the tailnet address — it
restores containers before `tailscaled` has the address up, the bind fails, and the
daemon logs one warning and never retries. Nothing exits, so `restart:
unless-stopped` never fires; nine containers run, `healthy`, publishing nothing.

The second, on the 19:09 boot — which was round two, the macOS 26.5.2 update:
Docker Desktop did not restore the containers at all, and **nothing on the host was
responsible for the stack being up** — `docker compose up` appeared nowhere in
launchd, because Docker had always happened to do it. Worse, the reconciler swept
zero containers, found no dropped bindings, and exited 0 reporting an intact
platform.

`launchd/reconcile-port-bindings.sh` now covers both, and
`check-platform-health.sh` mails on a state change and did correctly catch the
second. **Neither repair path has been exercised by an actual reboot** — the
binding path has never once been triggered by a boot, and the bring-up path was
written after the boot that needed it. That is the whole point of the property, so
until round one is re-run and passes, the chain is repaired-but-unproven, not
proven.

### If you are picking this up cold

Read this section, then the 2026-07-26 entries above, then
[runbooks/first-deploy.md](./runbooks/first-deploy.md) §1.1. The single most
useful thing to know is that the day found **eight defects of one kind**: a
control designed, written down, marked done, and not actually in force — the
account-split test asserting nothing, the Ollama bind not surviving a reboot, the
pnpm allowlist inert, the tailnet ACL never applied, the frontend's admin URL
baked at build time, a registered model with no reachable download action,
Grafana's host port that had never once bound because it was declared on an
`internal` network, and the unattended-recovery chain itself, where
`restart: unless-stopped` was documented as what brings the platform back and does
not restore a dropped port binding. None looked wrong. Tests passed, images built
clean, health checks were green. They surfaced only when someone walked the whole
path for the first time. Assume the same class of thing remains in the parts that
have not been walked yet — the public entrance, MLX, and anything the runbook has
not made someone do end to end.

**Two of the eight were only found because a different investigation walked past
them**, which is worth knowing about the remaining surface: Grafana's port was
noticed while chasing the reboot fault, and the reboot fault itself was noticed
only because §1.1 says to `curl` the gateway rather than trust
`docker compose ps`. Nothing was monitoring either. There is no alerting on this
platform yet, so "it looks fine" currently means "nobody has asked it a question
it could fail."

**A related habit the day kept punishing: checking in a way that can only return
one answer.** Three times — the `tailscale status --json` probe for SSH host keys
that read a nonexistent field, `docker compose up -d` assumed to rebuild a port
forward when it is a no-op against a running container, and a first draft of the
reconciler that would have enumerated containers before Docker finished restoring
them. Each produced a confident wrong answer rather than an error. When a check
passes, it is worth asking what a failure would have looked like.

The machine has **no out-of-band management**. The dividing line for remote work
is whether an action can affect the next boot; the runbook states this after §1.1.

One thing still exists as an API with no dedicated UI: the download progress
endpoint, which the models table polls but no page surfaces on its own. The
routing policy editor now exists, so a policy is no longer curl-only.

Phase 2 is now largely complete: both runtime adapters, node management, the
multi-tenancy boundary, the logs and usage screens, the observability emission
stack, the knowledge base with retrieval, and — since 2026-08-02 — the audit and
authorization completeness sweeps. What remains there is the live free-memory
figure the budget would consume (which needs the hardware), prompt template
management, the logging boundaries and expiring debug switch, encrypted backups,
and the `/api-docs` gaps recorded on 2026-07-30.

**Using the knowledge base needs one piece of configuration that nothing
enforces at startup**: a routing policy on the `embedding` capability, naming a
registered embedding model on an Ollama node. Without it, uploads still parse
and store but indexing fails with a named error, and retrieval quietly returns
nothing. That is deliberate — a chat should not fail because the knowledge base
is unconfigured — but it does mean an operator who skips this step sees a
knowledge base that looks like it is working and never answers anything.

## What comes next

Written at the end of 2026-07-26 as four open items, in the order they should be
picked up. **Item 2 was closed on 2026-08-02** and is marked so below rather than
deleted, because the shape of the work is still the record. Items 1 and 3 remain
open, and item 3 — the proxy administrator's four items — is now the only thing
standing between this deployment and a public entrance.

**1. Re-run the reboot test, and force a boot that loses the port-binding race.**
[runbooks/first-deploy.md](./runbooks/first-deploy.md) §1.1. Where it stands: round
one passed three of four boots (16:45 failed, 17:21 and 18:08 passed), and **round
two, the OS update, failed** — 19:09, Docker Desktop restored no containers and the
reconciler reported success on an empty platform. That was a new fault rather than
a recurrence, and it is not a round-one failure: the gate was correctly observed,
round two just tested something the three passes could not. Both defects are fixed;
neither fix has been through a boot.

Two of the six outcomes in §1.1 have never been produced by a boot, and each
proves a different repair path. `docker did not restore the stack; bringing it up`
→ `stack up: all expected services running` proves the bring-up path written after
the 19:09 failure. `OK: all bindings restored` proves the binding path, which four
boots have now failed to trigger because `tailscaled` won the race every time it
was a race at all. **A person must be at the machine.**

The second of those is no longer a matter of rebooting and hoping. The losing boots
are the ones that start without a netmap disk cache, and a boot that reads the
cache does not rewrite it — so **reboot twice in a row and watch the second one**,
which is the one that will have to wait for control before the address comes up.
The model has now predicted correctly once (19:09 read the cache and won by the
widest margin of the four), and by the same rule **the next boot is a slow one** —
so the next reboot is already the high-probability attempt at the binding path,
before any doubling up. If the margin stops alternating the way this predicts,
that is worth knowing too.

Round two no longer needs scheduling — 26.5.2 is installed — but it has to be
*passed*, which means re-running §1.1 in full on the machine as it now is. The two
settings checks that round two was written for (`autoLoginUser`, `pmset
autorestart`) both survived the update; what did not survive was something nobody
had listed, so after any future update the whole of §1.1 is the test, not those two
lines. Nothing should be concluded about the platform surviving a power cut until
both repair paths above have been walked by a real boot.

**2. Give the first administrator public-entrance credentials. — Done
2026-08-02.** The account bootstrapped from a tailnet identity carried no
`password_hash` and no `totp_secret`; the public entrance requires both, so
nobody could have signed in there once nginx existed, and by then the reason
would not have been obvious. Closed through the Users page, and the login flow
itself was then driven with `curl` to prove the public entrance works before
nginx exists. See the 2026-08-02 entry at the top of this file.

**3. Send the proxy administrator their four items.** A drafted request with the
real values is not in the repository (it names a person's mailbox and carries
setup detail); the content is [deployment.md](./architecture/deployment.md) §5
plus the runbook §8, and the tailnet is now ready for it — `tag:ntnu-proxy` will
apply, which it would not have before the ACL was in place. The shared secret goes
by a separate channel from the configuration. This unblocks the public entrance,
which is the largest unverified surface left — though **the application half of
it stopped being unverified on 2026-08-02**, when its full login flow was driven
end to end without nginx. What these four items unblock is the network path to
that socket, not the socket's behaviour.

**4. Then the roadmap.** As written on 2026-07-26 this listed the knowledge base,
prompt templates, logging boundaries, full audit coverage, backups, and
`MetricsPort` ingestion. The knowledge base landed 2026-07-30 and the audit and
authorization sweeps 2026-08-02, so what is left of Phase 2 is **prompt template
management, the logging boundaries and expiring debug switch, encrypted backups
and a rehearsed restore, the `/api-docs` gaps recorded 2026-07-30, and the
`prompt_tokens` decision**. `MetricsPort` ingestion is half done via the residency
read-back and now has a real number to calibrate against (a loaded 7B model
measured 5.7 GB resident against 4.7 GB of weights, with `OLLAMA_KV_CACHE_TYPE=q8_0`
in the committed plist; without it the same model measured 6.6 GB).

Two smaller things worth not losing: the GeoLite2 refresh **script** now exists
(`launchd/refresh-geolite2.sh`, written 2026-07-30) but **its plist is not
installed**, because `secrets/maxmind_license_key` has not been placed — so the
country database is still ageing with nothing to stop it, which is the same
outcome the missing mechanism had. And the frontend test runner still covers
logic units only; Playwright over the sign-in and enrolment screens remains the
deferred increment, now with a live enrolled account to drive it against.

### Done: the first Mac Studio deploy

Carried out on 2026-07-26 and recorded in the dated entries above. The checklist
below is kept because it is still the shape of the work, and because everything
in it that has *not* been done is now visible by contrast: the proxy
administrator's four items and the §14 pre-launch checks are still outstanding,
and the runbook has gained the steps this deploy showed were missing from it.

- Install Ollama natively under launchd as a dedicated service account, bound
  to `127.0.0.1`.
- Ask the NTNU proxy administrator for four things, listed in `ROADMAP.md`:
  join the tailnet under `tag:ntnu-proxy`, add two nginx server blocks, issue
  Let's Encrypt certificates, and confirm no request-body logging.
- Populate `./secrets` from `secrets/README.md`: three distinct database URLs,
  the postgres password matching the owner URL, and real values for the rest.
- Confirm the account split holds against the live database, which nothing has
  exercised yet: `migrate` creates the two roles and their grants, each service
  connects as its own account, and the gateway's account is refused an INSERT
  into `api_keys`.
- Work through the pre-launch checklist in `security.md` section 14. Several
  items say to test rather than assume, and mean it: the forged
  `Tailscale-User-Login` case, the forged `X-Forwarded-For` case, and
  `AUTH_MODE=dev` refusing to boot under `ENV=production`.

### Phase 2 and beyond

Detail in `ROADMAP.md`. The parts that will need real design work rather than
implementation:

- **A second runtime adapter** (vLLM or MLX). Worth doing early even if unused,
  because it is the only real test of whether the hexagonal layering delivered
  what it was chosen for. If adding one requires touching a use case, the
  abstraction failed.
- **Multi-tenancy.** Done; see the 2026-07-25 entry. The knowledge base, its
  main consumer, now plugs into that boundary and enforces it in three more
  places (the two tables, the document path, and the Qdrant collection name).
- **Prometheus and Grafana** are now built on the emission side (see the
  2026-07-25 entry). What remains is the ingestion half: a live free-memory
  figure feeding the memory budget, which needs the Mac Studio to produce a real
  one.
- **A second compute node**, which is the point of the node abstraction and
  will be the first time routing has more than one place to send anything.

### Open decisions

- **Whether to move `rcsl.online` to Cloudflare**, or register a separate cheap
  domain for the data plane. Either removes the accepted risk in `security.md`
  section 15.1, where inference traffic passes through a third-party machine in
  plaintext. Deferred, not settled.
- **How long an audit entry and a usage record are kept, and who may delete
  one.** Both tables are append-only with nothing that prunes them, which is the
  right default and not a policy. Neither is near a capacity problem — 160 kB
  and 120 kB after nine days — so this is wanted before somebody asks the
  platform to forget something, not because of disk. The answer constrains the
  backup story too, and `usage_records` is what quotas are measured against, so
  a retention window shorter than the longest quota period would be a
  correctness bug rather than a cleanup. See the 2026-08-04 growth audit.
- **Where the identity comes from.** No logo; the drawn one was rejected.
- **Whether the admin API should be reachable publicly at all.** It is designed
  for it and the entrance exists, but nothing depends on it yet, and closing it
  would remove an entire attack surface. Worth asking again once the tailnet
  entrance is in use and it is clear who actually cannot install Tailscale.

### Standing risks to revisit

`security.md` section 15 records four accepted risks with the conditions that
should trigger reconsidering them. The one most likely to change is 15.1: if
the platform starts handling personal or IRB-regulated data, plaintext
inference traffic through a third-party proxy stops being acceptable and the
Cloudflare question above becomes urgent rather than optional.
