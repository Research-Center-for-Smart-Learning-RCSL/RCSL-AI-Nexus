# Jev and local System One feasibility

Survey for [issue #20](https://github.com/Research-Center-for-Smart-Learning-RCSL/RCSL-AI-Nexus/issues/20),
checked on **2026-10-14** against Nexus `cb6f32c` (PR #55 included).
This is a documentation review, with no inference measurements on the Mac Studio.

**Recommendation: defer production integration.** Jev cannot replace the chat
models or the embedder. It can score retrieved passages, so an internal reranker
is a credible future experiment. Start with an isolated local evaluation if a
retrieval-quality problem warrants it; require measured benefit before adding a
service or public capability. This recommendation does not require Jev to match
general-purpose LLM accuracy on unrelated benchmarks.

## 1. Verified contract and evidence limits

TypeSafe's [introduction](https://docs.typesafe.ai/introduction) describes typed
decisions rather than generated prose. Its
[API reference](https://docs.typesafe.ai/api) documents authenticated
`POST /v1/systemone`, taking `model`, `state`, and a map of questions. Choice
selects a named option, Score rates ordered rubric levels, and Noul returns the
probability of yes. Responses contain answers and input/output token usage.
This is a different contract from Nexus chat completions and embeddings.

The [model documentation](https://docs.typesafe.ai/models) currently lists
`jev-1.13.0`: text input, 64k tokens per request and 32k for state plus the longest
question, $0.042 per million input tokens, and free output. These are provider
limits and prices as checked today. Pin a version for an evaluation; moving
aliases can change answers. The same page says English is strongest and CJK
needs workload-specific testing.

The [launch report](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
describes parallel output sampling and reports 70–500 ms end-to-end latency and
large speed/cost ratios on its System One workflows. Those are vendor results,
not measurements of Nexus, its network path, or its retrieval workloads. They
do not establish a sub-100 ms screening guarantee.

Schema validity does not establish decision correctness. TypeSafe's
[confidence documentation](https://docs.typesafe.ai/confidence) defines
Choice/Score confidence as a statistic of the returned probability distribution;
Noul has no separate confidence field. Do not treat a concentrated distribution
as a proven probability that an answer is correct in this domain. The provider's
[version-specific limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
include numeric precision, dates, indirection, irrelevant context, adversarial
content and option-order sensitivity. Keep exact arithmetic and authorization
in code; test uncertainty and rejection behavior on held-out examples.

The public documentation establishes a hosted API. No downloadable Jev weights
or Mac Studio deployment procedure was verified in the sources reviewed.
The [enterprise page](https://typesafe.ai/enterprise) advertises no training on
inputs and account-specific zero data retention. That does not establish that
an ordinary account has zero retention, that on-premises deployment is available,
or that this institution permits transferring research content. Obtain explicit
deployment and data terms if the cloud path is reconsidered.

## 2. Fit against the repository

The issue's statement that all capabilities generate text or vectors is too
broad: **reranking produces relevance scores/order, not embedding vectors**.
TypeSafe even documents a
[reranking workflow](https://docs.typesafe.ai/cookbooks/rerank_typesafe): score a
query/candidate pair with Noul and sort the shortlist. This establishes a
possible use, not quality on our corpus or compatibility with an existing Nexus
endpoint.

| Nexus surface | Current contract/evidence | Consequence |
|---|---|---|
| `chat`, `code`, `assist` | Chat messages and completion chunks through [ModelRuntimePort](../../backend/app/domain/ports/model_runtime_port.py) | Jev provides no free-form reply or summary; it cannot replace these models. |
| `vision` | A named capability in [the capability sets](../../backend/app/domain/entities/capability.py); actual support depends on the adapter/model | Jev's documented text-only input does not provide image inference. |
| `embedding` | `ModelRuntimePort.embed` returns ordered vectors | Jev's decision API cannot produce the existing index's embeddings. GLiFormer's separate embedding API is a different integration. |
| `rerank` | Issuable/routable name, but no rerank method on `ModelRuntimePort` | Semantic fit exists; a scoring contract and its callers still need implementation. |
| Knowledge retrieval | [SearchKnowledge](../../backend/app/application/use_cases/search_knowledge.py) embeds the query and returns vector-search passages; no reranking stage | A bounded internal passage scorer is the smallest useful extension. |
| Public API | [Gateway composition](../../backend/app/infrastructure/main_gateway.py) mounts chat, Responses, health and metrics routers; models listing is in the chat router | No `/v1/systemone` or rerank endpoint exists merely because a capability name exists. |
| Routing | [RoutingService](../../backend/app/domain/services/routing_service.py) compares policy/model/node fields | There is no ambiguous-intent decision in this selector that requires another model. |
| Runtime/usage | [RuntimeKind](../../backend/app/domain/entities/model.py) has four runtime kinds; [UsageRecord](../../backend/app/domain/entities/usage.py) records prompt/completion tokens and latency | A new decision service needs explicit accounting semantics; serializing an answer as chat text would misrepresent its operation. |

The local-runtime design in [ARCHITECTURE.md](../ARCHITECTURE.md) section 0.1
describes GPU placement and reachability, not a blanket ban on every outbound
connection. The [node egress guard](../../backend/app/adapters/http/egress_guard.py)
restricts registered compute-node addresses to the tailnet; it is not a general
cloud-provider policy. A cloud decision service would need its own explicit
egress and credential design. The decisive data issue is that it would receive
prompts or retrieved unpublished passages outside the existing research-data
boundary ([security context](../architecture/security/00-what-this-system-actually-is.md)).
Zero retention does not remove that transfer.

## 3. Local alternative: jeff

Review target: [jeff commit 34b32f9](https://github.com/logan-markewich/jeff/tree/34b32f99a727c47b679adde33f4702a001e02979).
Its [README](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/README.md)
describes a self-hosted TypeSafe-compatible API, CUDA/MPS/CPU support, and an MIT
server license. Protocol compatibility does not make its probabilities, quality
or resource limits equivalent to Jev's.

The pinned [server settings](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/src/jeff/server/config.py)
default to `0.0.0.0`, authentication off, and rate limiting off. They limit state
to 20,000 characters, questions to 64 and labels per question to 64. These are
not Jev's token/option limits. A Nexus experiment must explicitly bind loopback,
enable a dedicated bearer credential and set bounded requests/queueing; the
upstream quickstart defaults are unsuitable for this host's service boundary.

The [Torch backend](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/src/jeff/backends/torch_backend.py)
has an MPS path and uses eager attention off CUDA. Its actual loaded dtype and
process/accelerator memory must be recorded. The current
[GLiFormer large model card](https://huggingface.co/knowledgator/gliformer-large-v1)
reports **575.6M parameters**, Apache-2.0 weights and English evaluation coverage;
the jeff README calls it 400M. Resolve that version discrepancy by pinning the
checkpoint revision and inspecting it. Neither figure proves the issue's
“under 1 GB” or negligible-memory claim: weights, dtype, activations, batches
and framework overhead all matter. MPS support is not measured M4 Max acceptance.

The pinned [benchmark report](https://github.com/logan-markewich/jeff/blob/34b32f99a727c47b679adde33f4702a001e02979/bench/RESULTS.md)
records a September JevBench v1.2.2 result: jeff 66.9, ninth of 18, versus Jev
75.3. That run used a four-thread Ryzen CPU with an adjusted latency calculation
and estimated cost. It is historical evidence, not a current leaderboard or
Mac Studio latency comparison. Its task mix cannot establish Traditional Chinese
research-passage relevance or a safe moderation threshold.

## 4. Options and recommendation

| Path | Value | Cost and decision |
|---|---|---|
| Replace chat or embedding | No matching output contract | Reject for these capabilities. |
| Add a public decision endpoint | Useful to clients explicitly requesting typed decisions | Defer: no demonstrated consumer; requires scopes, schemas, limits, usage, error mapping and a provider/service abstraction. |
| Classify intent inside routing | Potentially useful before a caller chooses a capability | Defer: current clients already choose; keep eligibility, tenancy and authorization deterministic. |
| Gate every prompt with moderation | Possible semantic screening | Defer: changes availability and refusal semantics; neither published calibration nor speed proves safety on this workload. |
| Judge model evaluations | Could supplement qualitative labels | Defer: existing [evaluation harness](../model-evaluation.md) has programmatically checked tasks; judge bias would require separate validation. |
| Rerank retrieved passages locally | Concrete semantic fit with an existing retrieval seam | Preferred future experiment if relevance failures are demonstrated; keep it offline initially. |

If adopted later, keep application logic behind a narrow scoring port and put
provider I/O in an adapter. Do not force decisions through `generate` or invent
completion tokens. Preserve tenant/collection boundaries before scoring, bound
candidate count and bytes, define timeouts/cancellation and count actual scoring
calls/input usage. Local MPS work shares memory and GPU time with Ollama/MLX and
must participate in an explicit admission/resource plan. Proposed optional
reranking should fall back to the original ordered passages on a scorer outage;
a mandatory moderation gate needs a separately reviewed failure policy.

## 5. Reopening experiment and acceptance

These are proposed gates for a future experiment, not completed tests or a
scheduled runtime window. Reopen when a maintainer identifies retrieval failures
and accepts an added latency/resource budget, a client needs a decision API, or
approved deployment/data terms make a cloud experiment useful.

1. Pin the Nexus revision, jeff commit, checkpoint revision/hash, dependencies,
   device, dtype and question/rubric. For Jev, pin and record the returned model
   version. Use public/synthetic data for any cloud comparison.
2. Build a held-out relevance set of at least 200 queries, with English,
   Traditional Chinese, mixed code/text, near matches, no-answer cases and
   adversarial passages reported separately. Have relevance labels established
   independently of the scorer. Split rubric/threshold tuning from final testing.
3. Save the same tenant-scoped candidate lists for every arm. Compare unchanged
   vector order, a dedicated local reranker and jeff; optionally compare hosted
   Jev on approved data. Record Recall@k before reranking and nDCG@5/MRR after it:
   a scorer cannot recover a passage missing from the candidate list.
4. Report paired quality differences with uncertainty and per-language results.
   Require an improvement supported by the held-out comparison, with no material
   regression in the agreed language/no-answer strata. For automatic threshold
   decisions, report calibration, error rate at each threshold and abstention
   coverage; set acceptable error/coverage bounds before seeing final results.
5. On an operator-owned Mac Studio window, measure cold/warm p50/p95 latency,
   peak process/unified memory, queue behavior and concurrent chat impact at the
   chosen candidate/batch limits. Require the agreed latency and memory budgets,
   and no loss of resident-model availability. Record timeouts, overload and
   malformed/oversized-response behavior as failures, not excluded samples.
6. Before production, prove tenant isolation, bounded failure fallback, loopback
   binding/authentication, usage attribution and logging without passage text.
   Re-evaluate on a model, rubric, checkpoint or language-distribution change.

The survey is complete; integration and host measurements remain deferred.
No new runtime dependency or endpoint is needed to settle issue #20's feasibility
question. The recommendation and its reopening gates are indexed in
[decisions.md](../roadmap/decisions.md) and [the progress log](../PROGRESS.md).
