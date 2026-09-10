# Verified Baseline and Repository Impact

**Baseline:** `main`, `c890aa4546ec5e578d64b8144f8b166f06f9b0d0`, verified against
GitHub with `git ls-remote origin refs/heads/main` on 2026-09-10. The working tree
was clean before planning. No live Mac Studio, database, GPU, or provider was
exercised. Read this with the [plan](../image-generation.md).

## 1. Review scope

The review traced the HTTP entrances through authorization, application use
cases, runtime construction, persistence, and frontend consumers. It also
examined Compose, native launchd supervision, model observation, backups,
retention, generated contracts, CI, and existing tests. This is a cross-cutting
implementation-impact review, not a claim that every line or every dependency
has passed a security audit. Secret files and private production content were
not needed for it.

## 2. Capability and execution inventory

| Area and source | Verified behavior | Required construction consequence |
|---|---|---|
| [Capabilities](../../../backend/app/domain/entities/capability.py) | Five issuable names: chat, code, vision, embedding, rerank; assist is routable only | Add image_generation deliberately to both sets only when supported; feature-disabled deployments must not advertise it |
| [Capability discovery](../../../backend/app/application/use_cases/list_capabilities.py) | Lists issuable policies narrowed by caller; does not prove endpoint/model modality support or current readiness | Separate supported/configured capability from temporary availability; paused must not look unimplemented |
| [Policy writes](../../../backend/app/application/use_cases/manage_routing_policies.py) | Checks capability name, nonempty candidates, and alias existence | Validate endpoint/modality support; a policy alone must not promise vision or generation |
| [Routing](../../../backend/app/domain/services/routing_service.py) | Priority and structured requirements, including optional free memory | Preserve structured data; selection is not a runtime retry engine or atomic resource reservation |
| [Gateway](../../../backend/app/infrastructure/main_gateway.py), [chat routes](../../../backend/app/interfaces/http/routers/chat/route.py) | Business routes are chat/completions, responses, and models; separate health/metrics routes also exist | Add image routers without mounting management routers on the public process |
| [Chat schema](../../../backend/app/interfaces/http/schemas/chat_schemas.py), [domain messages](../../../backend/app/domain/entities/chat.py) | Text parts and string content; images are not transported | Vision needs a genuine multimodal representation, not just a frontend attachment button |
| [Responses schema](../../../backend/app/interfaces/http/schemas/responses_schemas.py), [tool translation](../../../backend/app/interfaces/http/routers/responses/tools.py) | Unknown tools are dropped and disclosed; active web_search is refused; message parts are text | Explicitly reject image_generation until implemented; account for both tools and additional_tools |
| [Runtime port](../../../backend/app/domain/ports/model_runtime_port.py) | generate emits CompletionChunk; embed and lifecycle share the port | Add a separate image execution contract while sharing registered identity |
| [Runtime construction](../../../backend/app/infrastructure/di/shared.py) | Only Ollama and MLX are constructed, keyed by RuntimeKind and configured global URLs | vLLM/llama.cpp enum values are not implemented adapters; resolve concrete node/runtime endpoints before multi-node support |
| [Chat orchestration](../../../backend/app/application/use_cases/route_chat_request/orchestrator.py) | Selects a Model, then gets an adapter by runtime kind; does not pass free-memory data to selection | Model.node_id alone does not route the connection; min_free_memory is not live admission |
| [Model entity](../../../backend/app/domain/entities/model.py) | ResourceProfile has memory_gb and context_length; observed state coexists with intent | Add workload-specific resource profiles, endpoint identity and verified support without imposing token context on images |

## 3. Every resource-consuming path matters

| Entry or operation | Current path | Scheduling implication |
|---|---|---|
| Public chat and Responses | Routers -> RouteChatRequest -> runtime.generate | Existing process-local semaphore must be complemented by shared node admission |
| Admin chat | Admin actor -> same chat use case | An API-key-only pause would leave this route active |
| Management assistant | AssistOperator -> chat on assist | Keep configuration pages usable even if the assistant cannot generate |
| Tier 2 compaction | [DI summarizer](../../../backend/app/infrastructure/di/inference_runtime.py) -> [summarization](../../../backend/app/application/use_cases/route_chat_request/compaction_tier2.py) -> generate | Nested inference must share the admitted operation; do not deadlock on another exclusive permit |
| Knowledge retrieval | [GroundChat](../../../backend/app/application/use_cases/ground_chat.py) -> [SearchKnowledge](../../../backend/app/application/use_cases/search_knowledge.py) -> embedding before chat | Admission must precede this pre-inference work, not start after it |
| Document ingestion and reindex | [Jobs](../../../backend/app/infrastructure/jobs.py) -> [EmbedTexts](../../../backend/app/application/use_cases/embed_texts.py) | EmbedTexts deliberately takes no chat semaphore; finish/drain existing batches and prevent further dispatch |
| Model load/unload | [Lifecycle](../../../backend/app/application/use_cases/manage_models/lifecycle.py) -> runtime lifecycle | Must coordinate with generation mode; unloading based only on stale observation is insufficient |
| Runtime automatic load | Generation can make Ollama resident with keep_alive | Blocking admin Load alone cannot prevent a text model returning during an image window |
| Model pull and evaluation tools | [DownloadModel](../../../backend/app/application/use_cases/download_model.py), [evaluation harness](../../../scripts/model-eval/README.md) | Downloads compete for disk/RAM; direct runtime evaluation must be excluded during controlled windows or use the same dispatcher |

[SemaphoreConcurrencyLimiter](../../../backend/app/infrastructure/concurrency.py)
is an asyncio semaphore held for the generator lifetime. Each app creates its
own instance. It is not a distributed node lock, and its queue wait default is
now 1200 seconds in [runtime settings](../../../backend/app/infrastructure/config/runtime.py).
Its older 25-minute explanatory comment is not a reliable current timeout budget.

SearchKnowledge.execute_or_empty catches NoAvailableModelError and
VectorStoreError and falls back to no passages. A scheduled suspension must have
a distinct error path: encoding it as NoAvailableModelError risks converting a
deliberate service pause into an ungrounded answer. This is a real counterexample
to the historical survey's claim that every absent capability is always refused.

## 4. State, memory, and host operations

- [MemoryBudgetService](../../../backend/app/domain/services/memory_budget_service.py)
  uses capacity times headroom; resident cost is max(profile, observation).
  A target load uses its profile. It does not measure generation peak buffers,
  serialize every competing request, or stop runtime auto-loads.
- Model load checks effective state and can return early on a stale LOADED
  observation. Unload requires effective LOADED; registry updates can separately
  refuse intent LOADED. The 2026-09-07 intent/observation trap remains relevant.
  A mode controller needs authoritative readback and idempotent reconciliation,
  not repeated presses of the existing lifecycle endpoints.
- [ModelStateCommitter](../../../backend/app/adapters/persistence/model_state.py)
  logs and suppresses commit failures. Reusing that behavior for a scheduling
  claim could let a caller proceed without durable ownership. Admission/mode
  checkpoints must fail closed on persistence failure and must not copy this
  best-effort recovery-writer contract.
- [Heartbeat](../../../backend/app/infrastructure/heartbeat.py) observes local
  models and explicitly leaves remote models unobserved. Both admin entrances
  run observation loops. Missing observations may fall back to intent.
  [Node health](../../../backend/app/adapters/http/node_health.py) uses the same
  globally configured adapters; remote endpoint health is not implemented.
- The native runtime placement in [ARCHITECTURE](../../ARCHITECTURE.md) remains
  applicable: the macOS Linux VM does not provide the host's Metal runtime path.
  The image runtime and its GPU-owning dispatcher belong on the host for this
  deployment, not inside the existing application container.
- [Reconciliation](../../../launchd/lib/reconcile/expected_bindings.sh) restarts
  missing expected services. Planned suspension must not be implemented by
  stopping gateway/admin containers that reconciliation will revive.
- [September 9 recovery](../../progress/2026-09-09.md) found launchd log ownership
  and PATH errors. New native services require a real launchd start/stop/reboot
  rehearsal, not just successful bootstrap exit codes.

**Recorded, not live:** the final [September 7 measurements](../../progress/2026-09-07.md)
put registered text profiles at 51 GiB against a 51.2 GiB budget on the 64 GiB
host, with a 3 GiB Colima cap. The same day's 54 GiB capacity experiment was
superseded. The September 9 recovery record says Ollama was up with no models
resident. Neither record proves today's occupancy. Restore profiles must be
captured and measured rather than inferred from these dates.

## 5. Persistence, authorization, and delivery

| Area | Verified baseline | Gap |
|---|---|---|
| [Key authentication](../../../backend/app/interfaces/http/middleware/api_key_auth/authentication.py) | Active key, source, geo, RPM and optional token quota checks | Image admission needs its own budget, including the session-authenticated path |
| [Quota](../../../backend/app/interfaces/http/middleware/api_key_auth/enforcement.py) | Historical rolling-24-hour token sum checked before execution | No atomic reservation for multiple concurrent image jobs |
| [Tenant repositories](../../../backend/app/adapters/persistence/repositories/shared.py) | Actor-scoped filters/stamps; explicit unscoped paths | Application isolation is not protection against a compromised broad database credential |
| [Database roles](../../../backend/app/infrastructure/db_roles.py) | Gateway broad SELECT minus denied tables; INSERT on usage, prompt logs, refusals | New job/prompt tables need explicit denied reads and narrow service grants; do not inherit blanket SELECT |
| [Job cache](../../../backend/app/adapters/cache/job_progress.py) | job:id keys and no tenant/owner in serialized progress | Never copy this authorization shape to image status, events, or previews |
| [Background execution](../../../backend/app/infrastructure/jobs.py) | asyncio tasks do not survive restart | Paid/durable image jobs need leases, dispatch reconciliation, and terminal accounting |
| [Document storage](../../../backend/app/adapters/storage/filesystem_documents.py) | Tenant directories and fixed filenames on an admin-mounted volume | No image asset metadata, binary delivery, thumbnails or image retention |
| [Uploads](../../../backend/app/domain/services/upload_policy.py) | 32 MiB; PDF, DOCX, plain text, Markdown | Do not broaden document parsers to smuggle in image uploads |
| [Usage](../../../backend/app/domain/entities/usage.py) | Input/output tokens, latency, completion and compaction | Add image/cost dimensions without redefining historical token columns |
| [Retention](../../../backend/app/domain/entities/retention.py) | Audit, usage, transcripts, refusals | Image content/jobs need separate retention and reference-aware garbage collection |
| [Backup](../../../launchd/lib/backup/documents.sh) | Captures documents volume through an admin container | New asset volume is not automatically backed up or restored |

The [network definition](../../../docker-compose.yml) gives gateway-egress a
non-internal network. [TailnetEgressGuard](../../../backend/app/adapters/http/egress_guard.py)
validates node addresses; it is not a universal outbound HTTP policy. Therefore
the old survey's assertion that external generation is blocked twice by
construction is too strong. External content transfer still requires an explicit
approved design under the existing research-data policy.

## 6. Frontend, contracts, and verification

[Chat schema](../../../frontend/src/features/chat/schema.ts) and
[composer](../../../frontend/src/features/chat/components/chat-composer.tsx) are
text-only. [useChatStream](../../../frontend/src/features/chat/hooks/use-chat-stream.ts)
aborts on unmount: this is right for existing chat and wrong as an implicit cancel
policy for durable image jobs. Add a separate feature rather than changing chat's
lifecycle globally.

[api-client](../../../frontend/src/lib/api-client.ts) uses same-origin admin
requests and CSRF, with no browser-held API key. [Middleware](../../../frontend/src/middleware.ts)
selects the admin upstream per request. Preserve both entrances for image assets.
The [model schema](../../../frontend/src/features/models/schema.ts) contains
hand-maintained capability/runtime enums, while
[generated contracts](../../../scripts/generate-api-types.sh) cover admin types,
role scopes and audit actions. Adding a feature touches both sources.

[CI](../../../.github/workflows/ci.yml) includes backend checks, real PostgreSQL
integration, frontend type/lint/unit/build checks, browser and full-stack tests,
documentation links, Windows tooling and advisory audits. The existing HTTP fake
runtime/full-stack harness is the right place to prove cross-entrance admission;
Linux CI cannot prove Metal memory release or launchd recovery.

## 7. Corrections to carry into implementation

1. No image generation is implemented: still true. Vision's advertised name is
   not working image input: still true.
2. A separate image port does not require a second model naming mechanism.
3. Multi-node registration is a foundation, not working per-node dispatch.
4. One GPU does not prove exclusive execution; safe coexistence is unmeasured.
   Time-sharing is the accepted product compromise, with explicit isolation.
5. Generated images may have provider-reported tokens. Image work still needs
   multiple accounting units; tokens alone are insufficient.
6. Vision input also needs visual resource accounting and compaction semantics.
   It is not automatically a cheap prerequisite for text-to-image.
7. Returning binaries does not by itself require MinIO. A private asset service
   can own a single volume and receive outputs from a remote worker.
8. Source comments that still describe observation as always including KV cache,
   or macOS containers as formerly native, are contradicted by later records.
   Use the implemented conservative budget and dated measurements, not those
   comments, as design evidence.

No runtime/model throughput, current occupancy, quality ranking, or provider
data-handling guarantee was established by this repository review. Those remain
release gates in the [delivery plan](./delivery.md).
