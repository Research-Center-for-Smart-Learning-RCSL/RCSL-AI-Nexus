# Frontend Architecture: Layered Components on shadcn/ui

Extends [../ARCHITECTURE.md](../ARCHITECTURE.md). The management UI is mostly tables, forms, and a few charts across eleven modules, so this document fixes how components are layered and how data flows, letting all modules share one skeleton instead of each inventing its own.

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

    features/
      models/
        components/           # ModelTable, ModelFormDialog, DownloadProgress
        hooks/                # useModels, useLoadModel, useDownloadJob
        api.ts
        schema.ts             # zod, used for both validation and inferred types
      routing-policies/
      api-keys/
      users/
      chat/
      dashboard/
      nodes/                  # Phase 2
      logs/                   # Phase 2
      usage-analytics/        # Phase 2
      knowledge-base/         # Phase 2
      prompt-templates/       # Phase 2

    app/
      (dashboard)/
        models/page.tsx       # thin, assembles feature components
        ...
      layout.tsx              # nav, theme provider, SessionProvider (see §3)

    lib/
      api-client.ts
      session.tsx             # auth mode context
      generated/              # openapi-typescript output, never hand-edited
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

## 4. Type Safety: Types Generated From the Backend

**Not wired.** `src/lib/generated/` holds only a `.gitkeep`, there is no
`sync-types` script in `package.json`, and nothing imports from it. Runtime
zod parsing is the only type safety today, and it cannot catch drift the way
generated types would. The section below is the intent; it also cannot be
completed until the admin API exists to generate from.

Eleven modules mean eleven sets of request and response shapes. Hand-maintained types drift, so they are generated:

```bash
# Admin API. Note the admin port: the gateway deliberately serves no schema.
npx openapi-typescript http://localhost:8001/openapi.json -o src/lib/generated/admin-api.ts
```

The gateway disables `/openapi.json` and `/docs` in production ([security.md](./security.md) §4.4), and the chat UI talks to `/admin/chat` rather than the public gateway anyway, so one generated file is enough. Package this as `pnpm sync-types` and run it whenever backend schemas change; a mismatch then surfaces at compile time instead of at runtime.

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

**There is no frontend test runner yet.** No Vitest, no Storybook, no
Playwright. The frontend is currently checked by the TypeScript compiler and
ESLint only, which is how an open redirect, an unreachable frame schema, and a
comparison between a UUID and an email address all shipped at once. Closing
this is the highest-value frontend work outstanding; the plan below is
unchanged.

- **Storybook plus Vitest** for `components/ui` and `components/composed`. The composed layer is reused across eleven modules, so a break there is expensive; stories cover loading, empty, error, and large-dataset states.
- **Vitest with Testing Library** for `features/*/hooks`, mocking the API client.
- **Playwright** for a small set of critical paths (create an API key, edit a routing policy and confirm gateway behaviour changes, stream a chat response and cancel mid-stream). Not every module needs an end-to-end test.
