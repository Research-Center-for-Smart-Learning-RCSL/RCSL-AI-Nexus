# Frontend Architecture: Layered Components on shadcn/ui

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md). The management UI is mostly tables, forms, and a few charts across **twenty-one feature folders and twenty screens** as of 2026-08-18 — it said "eleven modules" from the design phase onward, and "eighteen and fourteen" from 2026-08-05 until the evaluation, refusals and account screens arrived — so this document fixes how components are layered and how data flows, letting all modules share one skeleton instead of each inventing its own.

## 1. Where the Frontend Runs

The Next.js application is its **own container**, not static files served by FastAPI. It sits behind each admin entrance and proxies API calls to the corresponding backend from **middleware**, not from `next.config.js`:

```js
// src/middleware.ts
export function middleware(request: NextRequest) {
  const base = process.env.ADMIN_API_URL          // read per request, not at module scope
  if (!base) return new NextResponse('admin API not configured', { status: 500 })
  return NextResponse.rewrite(new URL(request.nextUrl.pathname + request.nextUrl.search, base))
}
export const config = { matcher: '/admin/:path*' }
```

A `rewrites()` entry in `next.config.js` was the original shape and does not work for the deployed image: `output: 'standalone'` resolves the config at **build** time and serialises it, where `ADMIN_API_URL` is unset, so both frontends shipped pointing at `http://localhost:8001` — the container itself. Every admin call failed with `ECONNREFUSED` while `docker inspect` showed the correct value in the environment. Middleware runs per request, which is what lets one image serve two entrances with different destinations.

**The proxy has a timeout, and it is not optional to think about.** Next applies a socket timeout to a proxied request — `proxyTimeout || 30000` in `server/lib/router-utils/proxy-request.js`. Thirty seconds is reasonable for an API call and wrong for an SSE generation, which is idle by design between tokens and can be idle for its whole length while a thinking model deliberates. At the default it cut a 93-second generation at exactly 30 s, and the browser saw a 500 with nothing in the backend log, because the reset happened between the two containers.

So `experimental.proxyTimeout` is set explicitly, and **above the backend's `GENERATION_DEADLINE_SECONDS`**: whichever limit fires first decides the failure, and only the backend's can end the stream with a reason (`finish_reason=length`). Raising one without the other moves the silent cut rather than removing it. A test reads both files and fails if the ordering inverts. Unlike `ADMIN_API_URL` this is a static value, so baking it in at build time is safe — that distinction is exactly why the proxy itself lives in middleware.

**The proxy also has a body limit, and it was worse than the timeout because it did not even reset the socket.** Middleware matches `/admin/:path*`, so every admin request has its body run through `getCloneableBody` (`server/body-streams.js`), whose default ceiling is 10 MB. Past it that function does not reject: it pushes EOF into the stream forwarded upstream as well as the clone the middleware reads, and the caller's original `Content-Length` is forwarded untouched. The backend then waits for bytes nobody will send, until `proxyTimeout` — thirty-six minutes, since that value moved to 2,160,000 ms with the read timeout on 2026-08-14. Found 2026-08-07, present since this file described the proxy, and the cost was that **every document upload between 10 MB and the 32 MiB the UI itself offers hung with no error anywhere**.

So `experimental.middlewareClientMaxBodySize` is set explicitly too, and **at or above the backend's `ADMIN_MAX_BODY_BYTES`**. The reasoning is the mirror image of the timeout's: there the outer limit must be *larger* so the inner one can report a reason, and here the same ordering holds for a different reason — the failure lives in the gap, because only below the backend's ceiling can Next truncate a body the backend would have accepted. Equal is the smallest value that closes it, and smallest is what is wanted: Next buffers up to this much in the Node process for a caller who has not authenticated yet. The same test reads both files.

Both limits together are the standing lesson of this section. **A limit inside the proxying layer binds before anything this project chose, and reports nothing when it does** — one as a socket reset, one as a hang. Neither appeared in a backend log. Anything added to the request path here should be checked for a third.

This makes every API call **same-origin**, which removes three problems at once: no CORS configuration, no third-party cookie restrictions on the session cookie, and no separate API hostname to configure per entrance.

Because the two admin entrances have different trust models and must stay isolated by socket binding ([security.md](./security.md) §5.1), each runs its own frontend container from the same image with a different `ADMIN_API_URL`:

| Container | Published on | `ADMIN_API_URL` |
|---|---|---|
| `frontend-tailnet` | `127.0.0.1:3000`, fronted by `tailscale serve` | `http://admin-tailnet:8001` |
| `frontend-public` | tailnet IP `:3001`, fronted by openresty | `http://admin-public:8002` |

Rendering uses React Server Components for shell and layout, with all data fetching in client components through TanStack Query. Server components do not call the admin API directly, because doing so would put the Next.js server on the authentication path and require it to forward session cookies and Tailscale headers, duplicating the trust logic the backend already owns.

## 2. Component Layers

```
frontend/
  src/
    components/
      ui/                     # shadcn/ui primitives, source lives in the repo
      composed/               # cross-feature building blocks
        data-table.tsx          # wraps TanStack Table: sort, filter, paginate, column toggle
        stat-card.tsx
        metric-chart.tsx
        confirm-dialog.tsx
        form-field.tsx
        status-badge.tsx        # online/offline/degraded, loaded/unloading
        stream-message.tsx      # incremental assistant output, see §6
        empty-state.tsx
        error-state.tsx
        one-time-secret.tsx     # a value the server will never return again
        secret-dialog.tsx       # cannot be dismissed by accident while one is shown
        code-block.tsx          # a snippet meant to be copied rather than read

    features/
      models/
        components/           # ModelTable, ModelFormDialog, DownloadProgress
        hooks/                # useModels, useLoadModel, useDownloadJob
        api.ts
        schema.ts             # zod, used for both validation and inferred types
      routing-policies/
      api-keys/               # issue, edit, revoke; actions gated on the scopes
                              #   the backend grants, so a member manages
                              #   their own (security.md §5.2)
      gateway/                # what an integrator needs: the base URL, the
                              #   servable capabilities, the paste-ready
                              #   snippets shown at issue, and the API reference
      assistant/              # the advisory drawer, mounted once by AppShell so
                              #   one conversation follows the operator across
                              #   screens. context.tsx is a typed registry: a
                              #   page publishes a surface and, on the key
                              #   forms, a draft — and there is no field an
                              #   issued key's plaintext could travel in
                              #   (security.md §7.5). Registrations are a
                              #   *stack*: screens nest, so a dialog closing has
                              #   to restore the page underneath rather than
                              #   clear the registry, which a single slot did
      users/
      chat/
      dashboard/
      nodes/                  # Phase 2
      logs/                   # Phase 2
      usage/                  # Phase 2. Named `usage-analytics/` in this tree
                              #   until 2026-08-05; the directory never was
      knowledge/              # Phase 2, likewise not `knowledge-base/`
      tenants/                # Phase 2
      retention/              # Phase 2
      host/                   # Phase 2
      account/
      auth/
      prompt-templates/       # Phase 2, built 2026-08-05. A named system
                              #   prompt selected by name; no variable
                              #   substitution, deliberately (security.md §7.4)
      prompt-logs/            # Phase 2, built 2026-08-08. Screen label is
                              #   "Transcripts", not "Prompt logs": it shows
                              #   what was typed while a debug window was open
                              #   (security.md §9.2), behind `prompt_log:read`
      evaluations/            # Phase 2, built 2026-08-17. A run's verdicts,
                              #   with what the run does not establish above
                              #   the numbers rather than beneath them
      refusals/               # Phase 2, built 2026-08-18. Every DomainError
                              #   the caller received, second copy of the
                              #   response they already had; `refusal:read_own`
                              #   is a base scope, so a member reads their own.
                              #   Filtered by code, request id, account and
                              #   time; rows are ticked to copy a selection
                              #   rather than the page (`time-range.ts`,
                              #   `account.ts` hold the two decisions)

    app/
      (dashboard)/
        models/page.tsx       # thin, assembles feature components
        api-docs/page.tsx     # the public API documentation security.md §4.4
                              #   promises in exchange for disabling
                              #   /openapi.json on the gateway
        ...
      layout.tsx              # nav, theme provider, SessionProvider (see §3)

    lib/
      api-client.ts
      session.tsx             # auth mode context
      generated/              # openapi-typescript output, committed, never
                              #   hand-edited (§4)
      api-contract.ts         # hand-written, and deliberately not inside
                              #   generated/: it checks each zod schema against
                              #   the generated types so drift is a tsc error
    styles/
      globals.css
```

## 3. Authentication: One Build, Two Modes

The frontend cannot assume how the user was authenticated. On the tailnet, identity arrives as a header injected by `tailscale serve` that the browser never sees; on the public entrance it is a server-side session cookie established by password plus TOTP. **In neither case does the frontend hold a token or set an `Authorization` header.**

The entrance is discovered at runtime from a single endpoint:

```ts
// GET /admin/me
type Me = {
  id: string                          // absent once, and the self-deletion guard
                                      //   compared a uuid to a login and never matched
  auth_mode: 'tailnet' | 'local' | 'dev'
  login: string
  display_name: string
  role: 'admin' | 'tenant_admin' | 'operator' | 'curator' | 'auditor' | 'user'
  scopes?: string[]                   // resolved server-side from the role.
                                      //   Optional, and absent is not empty: empty
                                      //   means this account holds nothing, missing
                                      //   means an older backend did not say, and
                                      //   `can()` falls back to role === 'admin'
  session_expires_at: string | null   // null on tailnet, which has no session
}
```

The root layout fetches this once and exposes it through context. What depends on it:

| Concern | `tailnet` | `local` |
|---|---|---|
| Sign-out button | Hidden, there is no session to end | Shown, calls `/admin/auth/logout` |
| Response to 401 | Show "Tailscale connection lost", offer retry | Redirect to the login screen |
| Session expiry warning | Not applicable | Warn before `session_expires_at` |
| CSRF token | Not needed | Required on mutations, see below |
| Change password, re-enrol TOTP | Not applicable | Available in account settings |

All requests use `credentials: 'include'`. On the public entrance, mutations additionally carry a CSRF token read from a non-`HttpOnly` companion cookie, matching the double-submit scheme in [security.md](./security.md) §5.3. `api-client.ts` attaches it automatically for non-GET requests so individual features cannot forget.

### Screens that exist only on the public entrance

These live outside the authenticated layout and must render before any `/admin/me` call succeeds:

- **Login**, in two steps. Password first, then TOTP on a separate screen. The error copy for a wrong password and an unknown account must be **identical**, since the backend deliberately does not distinguish them ([backend.md](./backend.md) §7); a helpful "no such user" message in the UI would undo that.
- **Invitation acceptance**, reached from a single-use link. Sets a password and enrols TOTP in one flow, showing the QR code and then the recovery codes. Recovery codes are displayed exactly once, so the screen requires an explicit "I have saved these" confirmation before continuing.
- **Password reset**, reached from an administrator-issued link. Same shape as invitation acceptance minus TOTP enrolment.

Password strength feedback uses the same zxcvbn threshold the backend enforces, so the UI never accepts something the API will reject.

Role gating in the UI is a usability affordance, not a security control. Every admin action is authorized server-side in the use case layer ([backend.md](./backend.md) §7); hiding a button never stands in for that.

**The nav gates on scopes, not on roles**, and each entry names the scope its screen's own first request requires — so a hidden link and a 403 are the same statement, one made before the click and one after. This replaced an `adminOnly` flag on 2026-08-04, which was accurate with two roles and wrong with six: it would have hidden Models from the `operator` whose job they are. Three entries declare no scope at all (API keys, API, Chat) because every role holds what they need. One definition feeds both the sidebar and the narrow-screen panel, and a route the caller's scopes do not cover redirects to `/chat` rather than rendering a screen whose data will 403 — that guard is for the address bar and the shared bookmark, which the nav cannot hide. All of it is covered by `app-shell.test.tsx`, which drives on scope sets rather than role names: the role table belongs to the backend, and a frontend copy of it could only assert that the copy matches itself.

## 4. Type Safety: Types Generated From the Backend

**Wired 2026-08-05.** This section read "**Not wired** … `src/lib/generated/`
holds only a `.gitkeep`, there is no `sync-types` script" and described a
`pnpm sync-types` that never existed — a name that also appeared in
`.gitignore`, justifying an ignore rule for output nothing produced. Both are
now real and neither is called that.

```bash
scripts/generate-api-types.sh      # or, from frontend/, pnpm gen:api
```

The script builds the admin ASGI app **in-process** and dumps its OpenAPI
document, rather than scraping a running container: FastAPI can produce the
document offline, so this needs no deployment, no database and no credentials
— which is what lets CI regenerate and fail on a difference. The gateway
deliberately serves no schema ([security.md](./security.md) §4.4) and the chat
UI talks to `/admin/chat` anyway, so one generated file covers everything.

**The output is committed**, and that is forced rather than tidy: the frontend
image builds from `./frontend` alone, with no Python and no backend source, so
a type derived from the backend cannot be build output there and a fresh clone
would fail `pnpm build`. Committing also makes the diff the place a contract
change is reviewed.

**The same script emits two catalogues beside the types, and they are not types at all.** `lib/generated/role-scopes.ts` carries what each role holds, read out of `adapters/authz/role_authorization.py` through its public `scopes_for`; `lib/generated/audit-actions.ts` carries every action name the platform writes, read out of `domain/entities/audit.py`. Both replaced hand-kept copies that had drifted — the role map twice in one day, with the tests passing while asserting a navigation no real role is shown, and the action list by eight names, each of which was a filter option `/admin/logs` could not offer. They are values rather than types because they are needed at runtime: a filter has to enumerate, and a test has to *follow* what a role holds rather than restate it. Consuming them does not weaken a test — what a role can see is still asserted explicitly, so a scope change that alters the navigation fails loudly. CI regenerates all three files and fails if the committed result differs.

**The generated types do not replace the zod schemas.** Types are erased; every
response is still `parse`d at runtime, which is what catches a deployment
serving something its own schema does not describe and turns a wrong shape into
one legible error rather than `undefined` spreading through a component tree.
What the types add is `lib/api-contract.ts` — a file that ships nothing and
exports nothing, where every hand-written schema is checked against the API
type it claims to describe, so a renamed or retyped field fails `tsc`.

Two refinements are deliberate and tolerated: narrowing `string` to a closed
union (`role`, `state`, `runtime`), and reading a subset of a response's
fields. **Dropping `null` is not**, and it is checked before assignability
because assignability permits exactly that mistake — `z.string()` *is*
assignable to `string | null`, and then throws on the first null the backend
sends. That distinction is what found all three of the mismatches present when
the file was first written.

What it cannot cover, stated so the list is not mistaken for coverage: the
document comes from the tailnet entrance, so screens served only by the public
entrance — the login challenge, the invitation-acceptance result — have no
types to check against and are guarded by their zod schema alone. Request
bodies are unchecked too; a wrong request shape is answered with a 422 the
operator sees, which is worse to use but not silent, and it is responses that
fail invisibly.

## 5. Data Flow

**Server state** (models, nodes, policies, users) always goes through **TanStack Query**:

- Polling cases such as model download progress and node health use `refetchInterval`.
- Mutations use `useMutation` plus `invalidateQueries`, so the UI resynchronises from the server rather than maintaining a second copy of the truth.

**Client-only state** (sidebar collapse, active tab) uses `useState` and `useContext`. No Zustand or Redux: nearly all meaningful state here is server state, and a global store would add indirection without removing any.

**Forms** use react-hook-form with zod. `features/*/schema.ts` defines the schema once and serves both `zodResolver` validation and `z.infer` types.

**Loading, empty, and error states** are handled by the shared `composed/` components rather than ad hoc per feature, so behaviour stays consistent across modules.

## 6. Streaming Chat

The chat UI consumes SSE from `/admin/chat` ([backend.md](./backend.md) §6). Three behaviours are easy to omit and produce bad UX:

- **Abort on unmount or user cancel.** The `AbortController` signal must reach `fetch`, otherwise the backend keeps generating and holds a concurrency slot. This is the client half of the disconnect guardrail.
- **Terminal error frames.** Because the HTTP status is already sent, a mid-stream failure arrives as an error frame, not an HTTP error. The stream reader must recognise it and surface the message rather than silently truncating.
- **The terminal frame's `finish_reason`.** `length` is the platform's ceiling reporting itself, and a thinking model reaches it having produced no answer at all — measured at 16,384 tokens and eleven minutes. Reading it and discarding it, which the reader did, makes that outcome render identically to an ordinary empty completion. It travels to the turn along with the elapsed time, because the live message that was showing the clock is gone by the time the finished turn renders.
- **Render incrementally without re-rendering the whole thread.** `stream-message.tsx` owns the accumulating buffer so that only the active message re-renders.

**Reasoning is a second channel, not more text.** A thinking model sends its deliberation as `reasoning_content` inside the delta, separate from `content` ([backend.md](./backend.md) §6). The store accumulates the two separately and they stay separate to the render.

`ReasoningBlock` is a **one-line ticker that expands**, not a growing wall of text: the summary carries elapsed time and the tail of the current reasoning, and the full text is behind the disclosure. Three reasons, none cosmetic. A block that grows for four minutes pushes the page down the whole time. The reader's actual decision during a long deliberation is whether to stop and re-ask with thinking off — this model has been measured producing 23,632 tokens of reasoning and no answer — and a clock answers that better than paragraphs do. And it is deliberately **not** rendered as markdown, unlike the answer: scratch work should not carry the same typographic authority as a conclusion.

It stays collapsed unless the reader opens it. An earlier version passed `open` as a controlled prop derived from whether an answer had started, so the block snapped shut in the reader's face on the first answer token; `defaultOpen` seeds the initial state and nothing overrides it after.

**The bubble must say something before the first byte.** `StreamStore.begin()` marks the request in flight and stamps `startedAt`, so the placeholder and the clock appear immediately. Without it the status stayed `idle` until the first delta arrived, which meant the placeholder — whose condition requires `streaming` — was unreachable during the only interval it existed for, and the wait rendered as a completely empty box. A few seconds of that reads as a hung application; a cold model load reads as a dead one.

Two consequences are invisible in the UI and only appear in what the server receives, so both live in exported pure functions with tests rather than inside the component:

- **Reasoning is never replayed as history.** It is the model's scratch work; sending it back multiplies the prompt on every later turn and is counted by the ceiling that truncates a generation.
- **A turn with no content at all is kept on screen and dropped from the request.** A generation that spent its whole budget deliberating produced no answer; leaving the turn out would show the user nothing, and sending it would put `{"role":"assistant","content":""}` into the prompt template for that turn and every later one.

**Thinking is a per-request choice.** The composer carries a `Thinking` toggle, because a model that will not stop deliberating cannot be fixed by any budget — measured, the same question produced nothing in 23,632 tokens with thinking on and a complete answer in 49 seconds with it off. **Both positions are sent**, so the box describes what the request asked for rather than what a server-side default happens to be. An earlier version omitted the field when checked, reasoning that `true` should not override the deployment default — which had it backwards: under `OLLAMA_THINKING=false` the box read "on", the request said nothing, the server applied `false`, and the control displayed the opposite of what happened with no way to correct it. Sending `true` is safe because the asymmetry lives a layer lower: the adapter maps it to sending no `think` field to the runtime ([backend.md](./backend.md) §6), so the value the browser sends and the value that reaches Ollama are deliberately not the same thing.

## 7. Charts

Charts appear on the Dashboard and Usage Analytics. **Decided: no chart library.** Tremor had shifted to copy-in source (the supply-chain caveat below), and Recharts, the documented fallback, is a real dependency plus a React 19 version constraint. The data these screens show is simple magnitude-over-time, so the charts are drawn as inline SVG instead: `components/composed/metric-chart.tsx` renders lines and an area, with axes and a hover tooltip, and the pure geometry (scales, path building, nice-max) lives in `chart-geometry.ts` where it is unit-tested without a DOM. Series colours read the theme's computed ramp (`--chart-1..5`) through `currentColor`, so they follow light and dark rather than carrying a second palette. One series renders as a filled area; several render as plain lines with a legend.

The trade is that axes, ticks and the tooltip are ours to maintain rather than a library's. That is acceptable while the charts stay simple time series; a genuinely richer visualisation (stacked areas, brushing, dual axes) would be the point to revisit the dependency.

This avoids the supply-chain caveat in [security.md](./security.md) §10 entirely: copy-in component libraries do not receive upstream fixes automatically, and here there is nothing copied in.

## 8. Rendering Untrusted Content

Model output and, in Phase 2, knowledge base excerpts are untrusted input. Markdown rendering must sanitise (for example `rehype-sanitize`), and raw HTML passthrough stays disabled. Streaming makes this easy to get wrong, because sanitising partial markdown as it arrives can produce different output than sanitising the completed document. Sanitise the accumulated buffer on each render rather than sanitising individual deltas.

## 9. Testing

**Vitest and the first Playwright paths are in place; Storybook is not.** For a while there was
no runner at all and the frontend was checked by the TypeScript compiler and
ESLint only, which is how an open redirect, an unreachable frame schema, and a
comparison between a UUID and an email address all shipped at once. Coverage is
now deliberately uneven rather than absent: the logic where a defect *is* a
security defect is covered, the two authentication state machines and the API
key management lifecycle are driven in Chromium, and presentation is not
exhaustively covered.

Currently 374 Vitest tests across 40 files (2026-08-18) — the SSE reader and frame schema, the API
client's CSRF and 401 handling, `safe-redirect`, the password schema, the key
form's own rules, and the assistant's proposal parsing, transcript handling and
page-context registry — plus five Playwright paths, and one more under §9.1 that
runs against a real backend. The five intercept
the admin API at the network boundary: they cover the real Next.js pages,
accessible controls, form state, requests and navigation without needing a
shared account or mutable Postgres fixture. The API key path keeps a stateful
in-memory API boundary across issue, edit and revoke, including the one-time
secret acknowledgement and revoked-key filter; routing policy editing asserts
the complete PUT and a GET made after it. Stream cancellation is the exception
to finite interception: a loopback HTTP fixture holds a real SSE response open
so Stop and client-side navigation must propagate disconnect to the upstream
socket. These complement rather than replace the backend's real-database
integration tests for authentication, API key persistence and routing policy
persistence.

`pnpm test:e2e` owns the loopback admin fixture, a Next.js **production build**
and the Chromium run. The build is the point: `next dev` serves an application
that nobody deploys, and running against it made the tests assert around a
development overlay and a cold-compile deadline while leaving everything
decided at build time — `NEXT_PUBLIC_*` inlining, the absence of StrictMode's
double-invoked effects — unexercised. `pnpm test:e2e --dev` keeps the
hot-reloading loop for local iteration, and is what `test:e2e:ui` uses. Because
that build inlines a test CSRF cookie name, it writes to `.next-e2e` rather
than to the `.next` that `pnpm build` produces.

### 9.1 The full-stack path, and why it is a separate command

Everything above stops at the browser's network boundary. That is the right
bound for a form's contract and it leaves one question unanswered: whether
editing a routing policy changes which model the **gateway** serves. `routing-policies.spec.ts`
proves the form sends the right PUT and the backend integration suite proves the
gateway routes on what is stored, so both stay green if the two are connected to
different things — an alias the form writes and the gateway never reads, a save
that lands in a different tenant.

`pnpm test:e2e:full` runs the paths under `e2e/full-stack` against the real admin
entrance, the real gateway and a Postgres it drops and rebuilds from Alembic
(`E2E_DATABASE_URL`). Nothing inside the applications is stubbed. The admin
entrance runs in `AUTH_MODE=dev`, which substitutes the header `tailscale serve`
injects and leaves the users lookup, the role, the scopes and CSRF exactly as
deployed. The runtime is a fake Ollama the **real** adapter reaches over HTTP, so
the assertion is the model reference the gateway asked for, read off a socket
rather than from an injected double. `CACHE_BACKEND=memory` is the one deployment
difference, and configuration refuses it under `ENV=production`.

**A separate mode rather than an addition to the default run**, because the
default paths must stay runnable with no database. Making all of them depend on
one is how this join went untested for as long as it did — the local Docker
daemon was unavailable on the day the browser paths were written, and a harness
nobody could run would not have been written honestly. In CI it is its own job
with its own Postgres service.

What it does not prove is inference. The runtime answers on the wire but does not
run a model, which is the same boundary everything else in this repository stops
at away from the Mac Studio.

A Node coordinator chooses an unused loopback port and terminates the build,
Next, Playwright and (in full-stack mode) both uvicorn process trees, because
Playwright's ordinary `webServer`
teardown leaves Next's worker alive on Windows after the tests have finished.
Spawn failures, signals and the runner's own deadlines (five minutes for the
build, ten for the tests) all converge on the same cleanup; CI adds an outer
sixteen-minute deadline, one minute above their sum, so the runner is what
reports a hang. `failOnFlakyTests` is on in CI: retries distinguish a flaky
test from a broken one, and a test that only passes on retry fails the run
rather than leaving a green tick and a note in a report nobody opens. Failed
CI runs retain trace, screenshot and the HTML report as a GitHub Actions
artifact.

Two things about the setup are worth knowing before adding to it. Vitest's
`globals` are **not** enabled, so every test imports what it uses — and
Testing Library therefore does not auto-clean, which is why `vitest.setup.ts`
registers `afterEach(cleanup)` explicitly. Without it a second `render` in one
file fails with "found multiple elements", which reads as a broken assertion
rather than as missing setup.

**A test written after a fix passes for the same reason the code does.** Put
the defect back and confirm the test notices. That has already caught a test
which passed either way, because its mock resolved immediately and the branch
being fixed was never executed (see [PROGRESS.md](../PROGRESS.md) 2026-07-29).

What is still outstanding:

- **Storybook** for `components/ui` and `components/composed`. The composed layer is reused across twenty-one feature folders, so a break there is expensive; stories cover loading, empty, error, and large-dataset states. Not started, and one of the two items left in Phase 2.
- **Vitest with Testing Library** across the remaining `features/*/hooks`. Started: `useChatStream` and `useAssistant` are driven through `renderHook` with the API module mocked, which is the pattern the rest should follow.
- **Playwright**, beyond the paths now present. The full-stack join landed 2026-08-10 (§9.1): a policy edited in the browser is observed changing which model the gateway asks its runtime for, against a real Postgres. What remains is breadth rather than a missing kind of coverage — the same harness could carry key issue to first gateway call, and a model unload to the refusal that follows. Not every module needs an end-to-end test.
