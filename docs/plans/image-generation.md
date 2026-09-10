# Image Generation: Construction Plan

**Status: proposed implementation plan; no image-generation feature implemented.**
Prepared 2026-09-10 against remote `main` at
`c890aa4546ec5e578d64b8144f8b166f06f9b0d0`. The planning PR changes documentation
only. It is not authorization to deploy, interrupt live requests, purchase
hardware, or send research content to a provider.

## 1. Product direction and decision boundary

The product owner established these requirements during the architecture review:

1. The first release serves teaching materials, presentation illustrations, and
   general illustrations.
2. Content stays internal by default. Only approved content may use external
   generation services.
3. Temporarily suspending some text services during generation is acceptable.
4. This deliverable is an English construction plan and a remote pull request,
   not feature implementation.

Requirement 3 changes the earlier recommendation to defer all self-hosted
generation until a second node. The initial deployment target is now a
**time-shared Mac Studio**, subject to measured capacity and recovery gates.
An additional node remains an expansion option, not a prerequisite.

Accepting temporary suspension does not decide which services may stop, for how
long, or whether an active response may be interrupted. This plan proposes
draining active work, blocking new affected inference, and restoring the
recorded text-service profile. It does not assume permission to kill active
research sessions.

## 2. Read this package in order

| Document | Purpose |
|---|---|
| [Verified baseline](./image-generation/verified-baseline.md) | Evidence from the current source, documentation corrections, and unverified deployment assumptions |
| [Architecture and contracts](./image-generation/architecture.md) | Shared-host scheduling, jobs, runtime boundaries, storage, API, security, and frontend contracts |
| [Delivery and acceptance](./image-generation/delivery.md) | Dependency-ordered construction slices, file ownership, tests, rollout, rollback, and decisions |

The [2026-09-07 survey](./image-capabilities.md) remains historical evidence.
This package supersedes its recommendations where explicitly identified in the
baseline. Historical progress entries are not rewritten to describe new plans
as past deployments.

Labels throughout this package have specific meanings:

- **Verified:** read in source at the baseline commit; not a claim of live testing.
- **Recorded:** a dated deployment observation from the progress log.
- **Accepted requirement:** a product-owner instruction listed above.
- **Proposed:** an implementation choice for review, not already shipped.
- **Open / gate:** evidence or a decision required before the dependent slice.

## 3. Recommended first release

Deliver one internally hosted text-to-image runtime, one approved model/workflow
profile, one image per job, a small set of supported aspect ratios, a private
image library, and durable job tracking. Begin with operator-scheduled generation
windows so the cost of switching services is visible and bounded. Automatic
batching can follow measured operation.

Build resource admission and recovery before enabling generation. Pausing only
`/v1/chat/completions` is insufficient: Responses, admin chat, the management
assistant, Tier 2 summarization, embedding, ingestion, and model lifecycle calls
can also consume or reload the same hardware.

Use a separate image execution port while retaining the registry's model
identity. Use PostgreSQL as job authority, a private binary asset store, and
independent metadata accounting. Redis may accelerate notifications but must not
be the only record of accepted work. Keep the existing text streaming contract.

Evaluate a pinned ComfyUI workflow first, with Diffusers as the alternative if
the fixed workflow is better maintained as a small worker. This is a benchmark
choice, not a runtime procurement decision or a claim of M4 compatibility.

Do not include arbitrary workflow editing, custom-node installation by users,
image editing, public sharing, general Responses tool execution, automatic
research-document grounding, or automatic external fallback in the first release.
The design reserves boundaries for those features without pretending they exist.

## 4. Construction order

`baseline and product gates -> shared admission -> safe mode switching -> durable
jobs and assets -> one runtime -> private UI -> public compatibility -> optional
external providers / vision / editing / multi-node`

Jobs/assets work can be developed independently of host control after contracts
are agreed, but cannot be enabled against a real runtime before the admission
and restoration gates pass. Each delivery slice identifies its own tests and
rollback. Do not merge one large feature patch that makes all gates inseparable.

## 5. Decisions required before live enablement

| Decision | Proposed default | What remains open |
|---|---|---|
| Paused services | All local GPU inference during the first image window | Whether embedding or a small assistant may remain, after measured coexistence |
| Switching authority | Operator opens a bounded window; users submit jobs within policy | Which roles may schedule windows |
| Active text work | Drain to completion; fail the switch on drain timeout | Maximum wait and any later explicit interruption policy |
| Runtime/model | Benchmark fixed ComfyUI and a limited alternative | Exact versions, model license, acceptable quality and measured memory |
| User experience | One image, fixed ratio presets, private library | Daily volume and acceptable queue/completion time |
| Content retention | Finite configurable retention with an explicit UI notice | Days, storage budget, backup treatment, deletion SLA |
| External approval | Exact request content approved before dispatch; no automatic fallback | Approver role, approval validity, provider/region and spend ceiling |
| Charging | Reserve before dispatch; settle actual usage independently of delivery | Units, per-tenant limits, and failed/cancelled job policy |

Unknown values are deployment gates, not blanks to be silently filled by code
defaults. Mode transitions, content custody, and release tests are specified in
the linked documents so these remaining choices do not prevent a reviewable plan.
