# Plan: Image Capabilities, and Why Drawing Is a Node Problem

**Status: survey, nothing decided and nothing implemented.** Written 2026-09-07
against `main` at `32b7648`. Everything in section 2 was established by reading
the tree at that commit and each claim names the file it came from; section 3
weighs options and takes no decision. Where something is an assumption from
outside this repository rather than something read out of it, it says so in
terms — section 5 lists every such assumption separately, because two of them
carry the recommendation and neither has been measured here.

This is a design record rather than a task list. It exists because "does this
platform draw?" is a one-word question with a one-word answer, and the useful
part is the shape of the gap rather than the answer.

## 1. The question, and the short answer

Asked: does the platform have image generation, and if not, what would it take.

**No, and not partially.** A search of the tree for `image_generation`,
`text-to-image`, `stable diffusion`, `comfyui`, `dall`, `flux`, `sdxl`,
`diffusers` and `automatic1111` returns three hits, all coincidental: a
frontend table-state hook, the doc-link checker, and an evaluation harness
module. There is no drawing code, no drawing dependency, and no drawing
container.

What the platform does have is `vision`, which is the opposite direction —
reading a picture, not making one — and which is **also not implemented**,
deliberately and with the reason recorded at the point where the implementation
would go.

### What this document concludes

| Question | Where it lands |
|---|---|
| Does image generation exist | No. Not started, not stubbed, not planned in `ROADMAP.md` |
| Does image *input* exist | The capability is sold; the path is not built. §2.4 |
| Is the gap an oversight | No. §2.4 and §2.9 — the refusal is written down and reasoned |
| What blocks self-hosted generation | **The single GPU and the single 64 GiB budget**, not the code. §2.5, §3.3 |
| Cheapest real gain | Completing `vision`. §3.2 |
| Where generation belongs | A dedicated node under Phase 3, using mechanisms that already exist. §3.3, §4 |
| Proxying an external drawing API | Conflicts with §6 and §7.2 of `security.md` by construction. §3.4 |

## 2. The inventory

### 2.1 The capability set is five names, and none of them is an image

`domain/entities/capability.py`:

```python
ISSUABLE_CAPABILITIES = frozenset({"chat", "code", "vision", "embedding", "rerank"})
ROUTABLE_CAPABILITIES = ISSUABLE_CAPABILITIES | frozenset({"assist"})
```

Four readers depend on it: `ManageApiKeys` at issue and at edit, the gateway's
capability-to-scope table, `ListCapabilities`, and `ManageRoutingPolicies.save`.
The file's own header records why it was collected into the domain — the set had
been defined in `manage_api_keys.py` and consulted only there, so a policy for
`chatt` stored and audited cleanly while no key could ever be issued for it.

**Adding a drawing capability starts here**, and starting here means answering
the two-set question first: routable, issuable, or both. The header is explicit
that there is deliberately no third name meaning "either", so the question
cannot be dodged.

### 2.2 The runtime port is token-shaped, and says so on purpose

`domain/ports/model_runtime_port.py` declares `generate`, `embed`, `pull`,
`validate_ref`, `load`, `unload`, `health`, `residency`. `generate` returns
`AsyncGenerator[CompletionChunk, None]`, and the docstring spends a paragraph on
why it is `AsyncGenerator` rather than `AsyncIterator`: only the former promises
`aclose()`, and that promise is the streaming contract that stops a disconnected
client from leaving the runtime generating with the concurrency slot held.

The decision that matters most for drawing is the one taken about `embed`:

> On this port rather than a separate `EmbeddingPort` so that an embedding model
> is registered, budgeted and routed exactly like a chat model: one registry, one
> memory budget, and a routing policy on the `embedding` capability decides which
> model answers. A second mechanism for naming a model would be a second place
> for the registry to be wrong.

Generation does not produce `CompletionChunk`s. So a drawing runtime forces a
genuine choice — widen this port and blur what it means, or open a second one
and accept the second naming mechanism this docstring argues against. **There is
no free answer, and it should not be pre-empted by a decision taken for some
other reason.**

`RuntimeKind` lists `OLLAMA`, `MLX`, `VLLM`, `LLAMACPP`. All four are language
model runtimes.

### 2.3 The gateway mounts four routers

`infrastructure/main_gateway.py` mounts `health`, `chat`, `responses` and
`metrics` — `/v1/chat/completions` and `/v1/responses` are the whole data plane
surface. There is no `/v1/images/generations`.

The file's first paragraph is worth keeping in view for anything that proposes
adding a route here:

> Mounts `/v1/*` only. No admin router is imported here, so there is no code path
> from this process to the management API even if it is fully compromised. The
> isolation is guaranteed by what is mounted and by socket binding, not by a path
> rule in a reverse proxy that one typo could undo.

`embedding` and `rerank` are in the same position: issuable, routable, and with
no endpoint to reach. `capability.py` classifies that as a missing route rather
than a capability that should not be sold, and closes it with the Phase 2
knowledge base.

### 2.4 `vision` is sold and not built, and the refusal is deliberate

`interfaces/http/schemas/chat_schemas.py`, `TextContentPart`, accepts
`type: "text"` and nothing else:

> Only `text` exists here. OpenAI's array form also carries `image_url` and audio
> parts, and a client sending one is refused by this `Literal` rather than having
> the part dropped: the `vision` capability is issuable, so a caller could
> reasonably send an image, and answering it from the text alone would look like
> the model had seen the picture and ignored it. When a vision path exists, this
> is the type that grows a member.

Downstream is equally empty: `adapters/runtime/ollama_adapter/` has no reference
to images anywhere, and the eleven files under `frontend/src/features/chat/`
contain one occurrence of the word "file", in prose about the tenant's uploaded
documents. The composer has no attachment control.

`frontend/src/features/api-keys/components/capability-picker.tsx` is where the
half-built state is made visible rather than hidden. All five issuable names are
rendered; the ones no policy routes are disabled and labelled, because hiding
them would leave an administrator wondering where `vision` went, while offering
them would keep selling keys that authenticate perfectly and then answer
`no_available_model` forever — an error deliberately indistinguishable from every
node being busy.

**So the gap is documented from three sides and closed from none.** That is a
debt with a known shape, not an oversight.

### 2.5 The machine is the constraint, and two of its numbers are load-bearing

`ARCHITECTURE.md` §0.2: Mac Studio M4 Max, 16-core CPU, **40-core GPU**, **64 GB
unified memory**, 4 TB SSD. The document then says which numbers carry weight:

- The 64 GB is unified across CPU and GPU, which is why `MemoryBudgetService`
  governs loads against a single figure (`NODE_TOTAL_MEMORY_GB=64`) rather than
  against a separate VRAM pool. Too high drives the host into swap; too low
  refuses models that would fit.
- `MAX_CONCURRENT_INFERENCE=4` "buys queueing depth rather than throughput,
  **since that one GPU serves a single generation at a time**".

`infrastructure/concurrency.py` implements the second as a semaphore whose
`slot()` is held around the whole generator body. A slot can legitimately be held
for up to 25 minutes, which is why a bounded queue wait was added on 2026-08-05:
without it a caller arriving with every slot busy sat producing zero bytes until
their own client timeout fired, which reads exactly like a hung deployment.

How tight the memory budget already is has been measured once: on 2026-08-07
Ollama predicted 55.8 GiB for a 262144-token context on a model this deployment
never sends more than 65536 to, and evicted every other resident model to make
room. That measurement is why `load()` takes a `context_length` at all.

**Both numbers point the same way.** A drawing workload is a second resident
model competing for the same 64 GiB, and a long GPU-exclusive job competing with
every language request for the same single-generation GPU.

### 2.6 Storage and uploads are text-shaped, and short on purpose

`adapters/storage/filesystem_documents.py` is a mounted volume, not MinIO, and
the header records the reversal:

> ARCHITECTURE.md listed MinIO for this. It is a volume instead […] What MinIO
> would have bought — presigned URLs, per-tenant credentials, horizontal storage
> — none of it is used here.

The layout is `<root>/<tenant_id>/<document_id>/` with fixed leaf names
(`original.bin`, `extracted.txt`) and **no caller ever supplies a path**.

`domain/services/upload_policy.py` caps an upload at 32 MiB and allows four media
types: PDF, DOCX, `text/plain`, `text/markdown`. No image type is among them, and
the allowlist is short by design — "every entry is a parser this deployment runs,
and adding one means accepting that parser's CVE surface."

`parser/main.py` runs those parsers as a fourth ASGI application with no volumes,
no secrets, no database and no egress, because §7.3 of `security.md` requires it.

Note what these two facts mean together for generation rather than for input: the
volume was sized and shaped for documents that are uploaded once and read as text,
and the reasons MinIO was refused ("presigned URLs — not used here") are the
reasons that would stop being true if the platform started **returning** binaries
it produced.

### 2.7 Metering counts tokens

`domain/entities/usage.py`: `UsageRecord` carries `tokens`, `prompt_tokens`,
`latency_ms`, `completed` and `requested_capability`. `adapters/metrics/prometheus.py`
exports counters labelled by capability and model, measuring requests, tokens and
duration.

A generated image has no token count. Usage analytics, the Prometheus series,
retention and per-tenant accounting would each need an answer for a unit that
does not exist yet. **Image input through a vision model does not have this
problem**, because a VLM turns pixels into tokens and `UsageRecord.tokens` keeps
its current meaning exactly.

### 2.8 The data plane does not make outbound requests, and this is enforced twice

`domain/ports/egress_port.py` and `adapters/http/egress_guard.py` validate a node
address before it is *stored*, because a stored address is one the platform will
later call. `docker-compose.yml` puts the gateway on its own `gateway-egress`
network.

The precedent that decides option D is already written, in
`interfaces/http/routers/responses/tools.py`, refusing the Responses API's
server-side `web_search`:

> `web_search` is the one thing here the platform genuinely cannot do: it is
> server-side, and performing it would mean the gateway making outbound web
> requests, against the data plane's segmentation (security.md §6) and its SSRF
> stance (§7.2). Refused only when the client actually wants it.

The same API's `image_generation` tool is server-side in exactly the same sense.
**Whatever is decided about drawing has to be decided about that tool at the same
time**, and today it would fall through `_assert_no_server_side_tools`, which only
inspects `WebSearchTool`.

### 2.9 One house rule governs all of this

The same judgement appears in at least six places, written out each time:

| Where | What it refuses to do |
|---|---|
| `model_runtime_port.py`, `embed` | Return a plausible vector from a runtime that cannot embed, because it would poison a knowledge base silently |
| `model_runtime_port.py`, `generate` | Generate without tools a runtime cannot call — prose where an agent loop expects a call fails far from the cause |
| `mlx_adapter/generation.py` | Serve tool-carrying requests until `MLX_TOOL_CALLING_VERIFIED` is earned |
| `chat_schemas.py` | Drop an `image_url` part and answer from the text |
| `responses/tools.py` | Serve `web_search` silently, leaving a model believing it can search |
| `capability-picker.tsx` | Offer a capability nothing routes |

**Announce the absence; never degrade quietly.** Any drawing work has to be built
this way or it will read as foreign to everything around it. In practice that
means the first thing a drawing capability needs is not a generator but a
refusal — the path that says "this deployment does not draw" in terms, at the
moment the caller asks.

## 3. The options

### 3.1 A — leave it, and make the half-built state legible

The only live risk in the current state is narrow: if a `vision` routing policy
is ever written pointing at a text-only model (nothing prevents it —
`ManageRoutingPolicies.save` validates the capability name and that the aliases
exist, not that the model can see), the picker stops disabling `vision`, keys get
issued for it, and callers meet a `422` from a `Literal` whose reasoning lives in
a docstring.

Cost: an hour. Gain: the gap stops depending on nobody writing that policy.

### 3.2 B — complete `vision`, which is image *input*

Not a new capability. It is a promise already in the issuable set, already shown
in the management UI, and already sold to any integrator reading `GET /v1/models`.
`chat_schemas.py` even names the type that grows a member.

What it touches, shallowest first:

1. `TextContentPart` gains an image sibling — the location the docstring points at.
2. `Message` carries image parts, so `ModelRuntimePort.generate` can receive them.
   This is the only change to the port, and it is **additive**: `embed`, `pull`,
   `load` and `residency` are untouched.
3. The Ollama adapter encodes them. (Assumption A1 — see §5.)
4. The MLX adapter **refuses** them, following `MLX_TOOL_CALLING_VERIFIED`
   exactly: raise `RuntimeCapabilityError` and name the fix, which is to route
   `vision` at Ollama. This is a mechanism that already exists rather than a new
   one.
5. A VLM is registered with an honest `resource_profile`, and a `vision` policy
   points at it. (Assumption A2.)
6. **The body limit is a decision, not a detail.** An inline base64 image goes
   straight at `gateway_max_body_bytes`, whose middleware is described in
   `main_gateway.py` as the only thing standing between an anonymous caller and
   an arbitrarily large allocation, because FastAPI reads and parses the body
   before it resolves the dependencies that authenticate. Raising it weakens that;
   an upload path instead means a second way for bytes to enter the data plane.
   Neither is free and the choice belongs to whoever starts the work.

What it does **not** touch: metering (§2.7), the document volume, the parser's
CVE surface, the upload allowlist, the egress posture, and the capability set.
It adds no long-running service and no container.

### 3.3 C — self-hosted generation

Everything in §2 that is shaped wrong is shaped wrong for this option: the
capability set (§2.1), the port (§2.2), the gateway surface (§2.3), storage
(§2.6) and metering (§2.7). A new native runtime under `launchd` is the one part
that is *easy* — `launchd/online.rcsl.ollama.plist` is the pattern and the
runtimes already live on the host rather than in Docker, because containers on
macOS cannot reach the GPU.

But the code is not what blocks it. §2.5 is:

- The GPU serves one generation at a time. A drawing job is GPU-exclusive for its
  whole duration (assumption A3), so every image would stall every language
  request behind it. `MAX_CONCURRENT_INFERENCE=4` buys queue depth, not
  parallelism, so the queue would absorb this as latency rather than refusing it.
- A resident diffusion model competes for the same single 64 GiB figure the
  language models are already sized against, and the 2026-08-07 eviction shows
  how little slack that figure has.

**This is a workload that wants its own node**, and the mechanisms for that
already exist and are unused: `Node` carries `total_memory_gb` and a `runtimes`
set, `MemoryBudgetService` works per node, and `routing_service` already supports
a `min_free_memory_gb` requirement per candidate. Phase 3 is literally titled
"Operations and Multi-Node".

### 3.4 D — proxy an external drawing API

This is refused by construction rather than by preference: it is the same
outbound request §2.8 declines to make for `web_search`, and it would have to be
made from the process whose isolation is defined by what it cannot reach. It also
contradicts the premise in §0 of `security.md` about what this system is.

If it is ever wanted, it is an architecture decision that belongs in
`ARCHITECTURE.md` and `security.md` before it is an adapter — not something an
adapter can introduce quietly.

## 4. Recommendation

**Do B now; hold C for a second node.**

B is cheap because it is additive everywhere and because the two hardest
questions in C — what unit to meter, and what a non-token runtime does to the
port — do not arise. It also pays back a debt the repository has already written
down three times.

The preparation C needs is not code. It is a Phase 3 item, and one restraint
while doing B: **keep `ModelRuntimePort` token-shaped.** Do not widen it toward
binary output in anticipation. The choice between widening that port and opening
a second one deserves to be made against a real drawing runtime with real
constraints in view, not pre-empted by a change made for image *input* that
happens to make the port look ready.

## 5. Assumptions this document did not verify

Everything in §2 is from the tree at `32b7648`. These are not, and two of them
carry §4:

- **A1.** That the Ollama HTTP API accepts images for vision models in a form the
  existing adapter can encode. Taken from outside this repository; nothing here
  exercises it, and it should be checked against the deployed Ollama version
  before §3.2 step 3 is scheduled.
- **A2.** That a vision model of useful quality fits the remaining budget beside
  what is resident. **Unmeasured.** The current registry and free memory can only
  be read on the Mac Studio.
- **A3.** That a diffusion generation on this GPU is exclusive and takes long
  enough for §3.3's queueing argument to hold. Plausible from the hardware but
  **not measured here**, and it is the load-bearing claim under the
  recommendation to defer C. A single timed run on the host would settle it.
- **Live state.** Whether a `vision` routing policy exists today — which decides
  whether §3.1's risk is latent or active — was not checked. It is a one-line
  read of the policy table on the deployment.
