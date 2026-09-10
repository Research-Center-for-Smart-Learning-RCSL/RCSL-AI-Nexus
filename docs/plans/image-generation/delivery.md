# Delivery Plan, Acceptance, and Recovery

**Planning only.** The accepted product requirements are in the
[main plan](../image-generation.md). All slices below are unimplemented.
Use the [baseline](./verified-baseline.md) for existing source references and
[architecture](./architecture.md) for proposed contracts.

## 1. Delivery principles

Ship small reviewable slices with feature flags off until their gates pass.
Preserve existing chat/Responses streaming and cancellation behavior. Do not use
a production inference request, a runtime install, or a model reload as a
documentation check. Live rehearsals need their own scheduled execution window.

P0 and contract design come first. P1 precedes P2. P3 can be built against fakes
after P1 contracts settle; P4 joins P2 and P3. P5 depends on P4, P6 on P5.
P7-P9 are optional follow-on work, not first-release blockers.

No calendar estimate is honest before the runtime benchmark and dispatcher scope
are settled. P1/P2 carry the greatest engineering risk: they change every path
that can reclaim the shared GPU. P3 carries the greatest persistence/security
risk. Avoid presenting an image adapter as the majority of the work.

## 2. Dependency-ordered construction slices

### P0. Product contract and host feasibility

**Deliver:** an approved pause matrix, measured text restore profile, candidate
runtime/model report, quality corpus, resource envelope and operating limits.

- Confirm daily images, concurrent users, acceptable waiting time, maximum drain
  and image-window durations, and roles permitted to schedule a window.
- Identify which text services pause. Default to all local GPU consumers;
  management, stored content reads and asset delivery remain available.
- Inventory actual Ollama/MLX versions, current desired/resident models, context
  settings, runtime auto-load behavior, Colima limits, memory pressure, disk and
  backup capacity. Do not use September records as present telemetry.
- Benchmark one fixed ComfyUI workflow and a bounded alternative if needed.
  Record exact code/model revisions and license review. No arbitrary extension
  marketplace. Measure cold load, hot generation, validation, teardown and text
  restoration; image memory includes encoders, VAE, buffers and safety checks.
- Use a versioned corpus of teaching diagrams, slide illustrations, backgrounds,
  Traditional Chinese prompts, text-in-image, people and scientific concepts.
  Score prompt adherence, useful composition, educational correctness, lettering,
  safety, reproducibility limits, and percentage of outputs actually usable.
- Select explicit preset limits, quotas, retention and availability targets from
  results. The first release exposes one image per job.

**Gate:** the measured host can run an image profile after releasing the agreed
text profile and restore it within the approved interruption budget. If not,
reduce the proposed profile or reconsider another node; do not raise headroom to
hide pressure or assume external fallback is permitted.

### P1. Shared execution admission and dispatcher

**Deliver:** a native supervised dispatcher, concrete local runtime resolver,
shared node admission and operation handles. Initially TEXT_READY only.

**Existing boundaries affected:** infrastructure/di/shared.py, inference_runtime.py,
admin_composition.py, main_gateway.py, domain ports, runtime adapters, chat
orchestrator, ground_chat.py, search_knowledge.py, embed_texts.py, jobs.py and model
lifecycle. Update both admin entrances and all background producers.

- Audit every runtime.generate/embed/load/unload call, including nested assist
  summarization and tools/evaluation scripts. Document any trusted repair bypass.
- Register logical operations atomically, use epochs and dispatcher-enforced
  fencing, and preserve stream backpressure/disconnect cleanup.
- Ensure nested RAG/summary calls do not acquire a conflicting independent permit.
- Give scheduled suspension its own typed error; keep it out of the existing
  retrieval fallback and generic model-unavailable path.
- Separate inference and lifecycle credentials. Test that inference identity
  cannot change mode or send arbitrary upstream paths/model references.

**Gate:** simultaneous calls through gateway, admin-public and admin-tailnet
cannot bypass a shared admission decision. Existing text behavior passes against
real HTTP fake runtimes. No live image runtime is enabled.

**Rollback:** with no active transitions, return to the previously tested text
deployment. Never switch to legacy direct runtime calls while image work exists.

### P2. Time-sharing state machine and verified restoration

**Deliver:** operator-controlled bounded windows, mode checkpoints, restore
manifest, fresh observations and recovery UI/API. Use a fake image executor first.

**Existing boundaries affected:** model lifecycle/state committer, memory budget,
heartbeat, node health/configuration, launchd services, health check and reconcile
scripts. Add a mode entity/service separately from physical NodeStatus.

- Drain all admitted logical operations, checkpoint ingestion batches, and defer
  conflicting downloads/lifecycle actions.
- Add idempotent unload/reconcile semantics to handle stale observations and
  runtime eviction; retain conservative memory accounting until release is proven.
- Block affected registry/profile edits while a transition holds them.
- Verify image release before text reload. Restore only the agreed recorded
  profile, in the measured order, with exact context settings and readiness probes.
- Limit drain, image window and restore time. Lease loss or uncertain execution
  enters recovery; it never immediately transfers GPU ownership.
- Teach health reporting about intentional pause while preserving failure alerts.
  Keep gateway/admin containers running so existing repair scripts do not fight it.

**Gate:** no overlapping conflicting dispatch during drain/switch/restore;
transition crash recovery passes at every checkpoint. Actual launchd log ownership,
PATH, stop behavior and reboot behavior are verified in the scheduled rehearsal.

**Rollback:** stop accepting images, drain/cancel confirmed work, release image
runtime, restore text and verify it before disabling the controller. If release
cannot be proven, stay DEGRADED with management available and use the repair runbook.

### P3. Durable jobs, assets, quota and security foundation

**Deliver:** migrations, scoped repositories, dedicated service roles, private
asset storage, durable worker claims, idempotency, usage ledger and retention.

**Existing boundaries affected:** domain entities/ports, persistence models/mappers,
repositories, Alembic, db_roles.py, authorization catalog, usage/readers, retention,
error/refusal handling, backup manifests and restore procedures.

- Design effective grants for new private tables before creating them. The
  existing blanket gateway SELECT must not expose job payloads. Choose tested
  RLS/restricted database interfaces or a dedicated authorized service boundary;
  do not rely on a tenant prefix as the sole access control.
- Make acceptance plus reservation transactional; persist execution attempts and
  uncertain dispatch. Define tombstone/idempotency and approval retention windows.
- Build storage staging, validation, atomic publication, cleanup and orphan
  reconciliation. Include thumbnails and metadata in tenant/owner checks.
- Implement polling first, independent of worker process lifetime. Redis loss
  must not lose accepted jobs or reservations.
- Recheck permissions at dispatch/read; revocation prevents new execution and
  access. Define safe accounting for already-running work that cannot be stopped.
- Extend image-specific analytics without changing historical token meanings.
- Define backup consistency and restore-time garbage collection; document prompt
  payload sensitivity and retention separately from existing debug logs.

**Gate:** real PostgreSQL tests establish isolation, atomic budget reservation,
duplicate submission/settlement prevention and restart recovery; filesystem tests
prove no path traversal, premature publication or content resurrection.

**Rollback:** stop new submissions/workers; retain append-only metadata and assets
for investigation. Do not downgrade away accepted jobs or ledger records. Use
additive migrations and a text-compatible disabled feature state.

### P4. One approved self-hosted runtime

**Deliver:** one image adapter, one pinned workflow/model profile and bounded
decode/validation. Install GPU execution natively under a dedicated service account.

**Existing boundaries affected:** runtime registry/factory and validation,
settings/production validation, image worker composition, deployment and launchd.
Keep GPU packages out of the existing FastAPI application image.

- Wrap the runtime's actual progress/result/cancel behavior rather than guessing
  from connection closure. Map per-job ownership before allowing cancellation.
- Keep workflow and model acquisition under reviewed operator control.
- Charge peak resource use, enforce size/time/output-byte bounds and verify memory
  release after success, timeout, crash and cancellation.
- Test local safety checks and hold unsafe/unvalidated results out of asset reads.
- Finish the joint P2/P3 hardware rehearsal using representative image jobs.

**Gate:** end-to-end internal generation and restoration meet P0 thresholds;
ambiguous upstream execution is reconciled without duplicate generation or early
text admission. Failing this gate blocks the UI enablement, not just public API.

### P5. Private image workspace

**Deliver:** admin routes and schemas, prompt/preset form, job status, private
gallery, preview, download, regenerate and deletion. Polling survives refresh.

**Existing boundaries affected:** frontend feature directory, dashboard page,
navigation catalog, API client consumers, model/capability schemas, generated
admin/role/audit types, usage view and pause messaging in chat/knowledge/assistant.

- Keep existing chat cancellation unchanged; image navigation stops observation
  only. Explicit cancel communicates requested versus confirmed.
- Handle duplicate clicks, browser refresh after an uncertain submission, quota
  changes, session expiry and account switching without leaking cached content.
- Display actual phases and measured/optional progress; never fabricate percent.
- Keep image generation unavailable outside policy windows, with an actionable
  queue explanation. No generic endless spinner during model switching.
- Add keyboard/mobile/accessibility coverage and bounded thumbnail loading.

**Gate:** browser-to-admin-to-worker-to-asset behavior passes with a fake HTTP
runtime and real database; an authorized internal user completes the live rehearsal.

### P6. Public Images compatibility and operational release

**Deliver:** image job/asset public endpoints and the synchronous Images facade;
API documentation, metering, full deployment, backup/restore and alert acceptance.

- Keep asynchronous extensions separate from standard Images response shapes.
- Test real Python/JavaScript SDKs selected for support, requested model/capability
  semantics, unsupported fields, timeout/retry and base64 output.
- Verify external reverse proxy limits, no buffering where streaming is used,
  body limits, authenticated binary delivery and URL behavior for actual clients.
- Check public geo/CIDR/RPM behavior without applying spent generation quota to
  status/cancel/download. Do not promise public readiness from a local test.
- Exercise backup restoration into an isolated environment with asset/DB mismatch,
  expired content and inflight job reconciliation.
- Update architecture trees, security control inventory, audit catalogue, roadmap,
  public API reference, environment example and operations runbooks together.

**Gate:** enable the public capability only after P0-P5 and the public-entrance
checks pass. A docs PR does not prove these gates or authorize public deployment.

### P7-P9. Optional extensions

- **P7 external provider:** exact-content approval, restricted provider worker,
  cost ceiling, policy revocation, endpoint/download allowlists and provider
  contract review. No automatic fallback. Start with one provider.
- **P8 vision/editing/Responses:** multimodal messages and guarded uploads first;
  then image editing and a bounded Responses image tool with correct output,
  history, authorization and accounting. No silent stateful-parameter ignoring.
- **P9 multi-node:** per-node endpoint authentication, health/residency, per-node
  admission, resource profiles and asset transfer. A second node does not justify
  dropping the first node's serialization or mandating a shared filesystem.

## 3. Acceptance matrix

Each row is required before enabling the related slice; tests are not claimed
to exist merely because this plan names them.

| Scenario | Required result | Verification environment |
|---|---|---|
| Chat + Responses + two admin callers racing a mode change | A single admission boundary; admitted work drains, new work cannot reach runtime | PostgreSQL + multiple real app instances + HTTP runtime recorder |
| RAG, Tier 2 and ingestion active during drain | No hidden GPU dispatch, nested-permit deadlock or silent ungrounded response | Unit plus cross-process integration |
| Manual Load, stale LOADED observation, runtime eviction | No bypass or false release; actionable reconcile state | Integration then actual host |
| Worker/controller crash after each transition checkpoint | Durable mode and restore manifest; no overlapping old/new dispatch | Fault injection + restart rehearsal |
| Database unavailable during admission/checkpoint | No new dispatch or mode ownership; management reports recovery status | Persistence failure injection |
| Lease expires while old runtime continues | New owner reconciles and does not assume resource free | Fake long-running upstream and host test |
| Drain exceeds allowed window | Text admission restored, image queue explained, no forced text kill | Integration/UI |
| Same idempotency key replayed / changed payload | Same authorized result / 409; one reservation | Concurrent PostgreSQL test |
| Two jobs race the last available credits | Only affordable work accepted | Concurrent PostgreSQL test |
| Provider/local submit acknowledged but persistence interrupted | No blind resubmission; uncertain attempt visible | Adapter failure injection |
| Cancel races success, callback repeats | One terminal outcome and settlement; no early resource release | Integration |
| Result stored but DB commit fails, or disk fills | No falsely successful job; bounded cleanup/reconciliation | Storage fault injection |
| Cross-tenant job, thumbnail, event, download or delete | Non-disclosing refusal; no content or progress leak | Integration and browser |
| Gateway database role queries private payloads | Denied by effective grants/policies, not just a repository convention | Real database role test |
| Key revoked/session expired while queued or observing | No new execution/access; running cost reconciled | Auth + worker integration |
| Oversized/corrupt/mislabelled/decompression-bomb image | Bounded rejection in isolated decoder | Parser/asset integration |
| Delete races late completion / restore from old backup | No visible resurrection; ledger retained without prompt content | Storage and restore rehearsal |
| External approval invalidated or provider changes | No dispatch; no automatic local-to-external fallback | Policy + adapter recorder |
| Leave page, refresh, switch account | Job continues; correct history; no prior account cache leak | Playwright |
| Text -> image -> text cold cycle | Approved memory envelope and latency; exact restore profile ready | Mac Studio only |

Use existing backend unit/integration suites and frontend full-stack harnesses;
extend their fakes to record actual outbound runtime calls. Include negative
controls that deliberately bypass admission or duplicate settlement and prove the
tests fail. Do not rely only on assertions that a collaborator was constructed.

## 4. Rollout and incident handling

1. Apply additive schema/role changes with image flags off. Verify text regression
   and grants. Keep asset directories inaccessible publicly.
2. Route text through the dispatcher in text-only mode and prove its stream and
   failure behavior. Retain a tested rollback artifact.
3. In a scheduled internal window, run drain/unload/fake-image/restore before real
   generation. Confirm memory and runtime state rather than command exit status.
4. Enable one profile for selected users. Observe full cycles, queue fairness,
   restoration failures, outstanding reservations and asset cleanup.
5. Enable broader UI/public access only after the corresponding acceptance gates.

For emergency disablement, close image admission first. Reconcile or stop the
owned image execution, validate memory release, restore the agreed text profile,
then reopen text. If that fails, remain visibly DEGRADED; do not flip a feature
flag that lets legacy text calls reload into an occupied GPU. Keep status and
repair access alive. Record operator interventions and reconcile orphaned usage.

Do not disable the entire health monitor for a scheduled image window. Teach it
expected capability pauses and alert on overdue transitions. Do not rely on a
host-only watcher to detect total host loss; the existing external-monitor gap
remains separate and must be visible in operating expectations.

## 5. Open decisions and risks

| ID | Decision/evidence | Blocks | Risk if guessed |
|---|---|---|---|
| D1 | Exact pause matrix and active-request interruption policy | P0/P2 enablement | Unexpected research-session interruption |
| D2 | Quality corpus, selected model/runtime and license | P4 | Unusable output or an unsupported runtime |
| D3 | Peak memory, drain/window/restore budgets | P2/P4 | Swap pressure or prolonged text outage |
| D4 | Dedicated service packaging, endpoint auth and private-table grants | P1/P3 | New privilege bridge or cross-tenant content exposure |
| D5 | Image/storage quota units, limits and failure/refund policy | P3 | Overspend or misleading usage |
| D6 | Prompt/asset retention, backup and deletion SLA | P3/P5 | Unintended research-content archive |
| D7 | Role grants, operator window control, future sharing | P2/P5 | Ordinary users gaining fleet control or content access |
| D8 | Provider approver, exact-payload approval and data contract | P7 | Unauthorized external disclosure |
| D9 | Supported SDKs and public proxy behavior | P6 | A nominally compatible API that real clients cannot use |

Defaults in the architecture are proposals. Capture final choices in reviewed
decision records before the dependent rollout. No open provider/hardware question
blocks merging this documentation, and merging it does not settle those questions.
