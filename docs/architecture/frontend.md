# Frontend Architecture: Layered Components on shadcn/ui

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md). The management UI is mostly tables, forms, and a few charts across **eighteen feature folders and fourteen screens** as of 2026-08-05 — it said "eleven modules" from the design phase onward — so this document fixes how components are layered and how data flows, letting all modules share one skeleton instead of each inventing its own.

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
  auth_mode: 'tailnet' | 'local' | 'dev'
  login: string
  display_name: string
  role: 'admin' | 'user'
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

Currently 229 Vitest tests across 26 files — the SSE reader and frame schema, the API
client's CSRF and 401 handling, `safe-redirect`, the password schema, the key
form's own rules, and the assistant's proposal parsing, transcript handling and
page-context registry — plus three Playwright paths. The browser tests intercept
the admin API at the network boundary: they cover the real Next.js pages,
accessible controls, form state, requests and navigation without needing a
shared account or mutable Postgres fixture. The API key path keeps a stateful
in-memory API boundary across issue, edit and revoke, including the one-time
secret acknowledgement and revoked-key filter. These complement rather than
replace the backend's real-database integration tests for authentication and
API key persistence.

`pnpm test:e2e` owns the Next.js development server and Chromium run. A small
Node coordinator terminates the whole server process tree because Playwright's
ordinary `webServer` teardown leaves Next's worker alive on Windows after the
tests have finished; CI and local runs therefore use the same command and both
return cleanly. Failed CI runs retain trace, screenshot and the HTML report as a
GitHub Actions artifact.

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

- **Storybook** for `components/ui` and `components/composed`. The composed layer is reused across eighteen feature folders, so a break there is expensive; stories cover loading, empty, error, and large-dataset states. Not started, and one of the two items left in Phase 2.
- **Vitest with Testing Library** across the remaining `features/*/hooks`. Started: `useChatStream` and `useAssistant` are driven through `renderHook` with the API module mocked, which is the pattern the rest should follow.
- **Playwright**, beyond the authentication and browser-boundary API key increments, for a small set of full-stack critical paths: edit a routing policy and confirm gateway behaviour changes, stream a chat response and cancel mid-stream, and eventually run the management browser against isolated Postgres state. Not every module needs an end-to-end test.
