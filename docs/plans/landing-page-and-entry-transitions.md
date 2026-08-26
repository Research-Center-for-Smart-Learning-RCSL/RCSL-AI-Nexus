# Plan: A Public Landing Page, and Two 3D Entry Transitions

**Status: planned, not built. Nothing in this document describes code that
exists.** Written 2026-08-26. Every file and line reference below was read at
that date against `main` at `e8373ca`; line numbers will drift and the
surrounding reasoning is what should be trusted if they disagree.

This is a design record rather than a task list. The decisions were taken in
conversation and are written down here with the reasons, because three of them
are cheap to make and expensive to reverse — the route move touches
authorization behaviour, and the WebGL dependency touches the test suite and
the bundle.

## 1. What was asked for

Three things, in the requester's order:

1. A **spectacular full-screen transition before the login screen**.
2. A **second transition after sign-in, before the application appears**. These
   are two separate animations, not one.
3. **The logo in the top-left must return to the home page, including after
   sign-in.**

Item 3 is what forced the largest change, because this repository has no home
page. `/` is the Dashboard (`frontend/src/app/(dashboard)/page.tsx`), behind
the authenticated shell. "Return to the home page after signing in" therefore
means a page that does not exist yet.

### Decisions taken

| Question | Decision |
|---|---|
| What is the home page | Build a **new public landing page** at `/`; move the Dashboard to `/dashboard` |
| What an authenticated visitor sees at `/` | The landing page, with the current account shown at the top and a "go to the console" action — **not** an automatic redirect |
| Where the post-sign-in curtain lives | The session gate, so it also covers reloads, with a minimum-duration state machine (see §6) |
| How often each curtain plays | Curtain A: **once per browser tab session**. Curtain B: **every entry**, always skippable |
| 3D technique | **Real WebGL**: `three` + `@react-three/fiber` + `@react-three/drei` |
| Curtain A scene | Depth tunnel — the camera flies through a corridor of emissive rings |
| Curtain B scene | Layer dive — the camera descends through stacked translucent shells |
| Glow | **Additive-blending fake bloom**, not `EffectComposer` / `UnrealBloomPass` |
| Palette | **Follows the theme**: two palettes, light and dark |
| Pointer parallax | **None**, on either the landing page or the curtains |
| WebGL unavailable or too slow | Degrade to a short CSS `perspective` fade, roughly 400ms |

Two of these are worth restating because they were chosen against the
recommendation offered at the time, and the document should not pretend
otherwise: `drei` was chosen over a bare `three` build, and Curtain B plays in
full on **every** entry to the application rather than only after a sign-in.
Both are workable. §7.5 and §6.3 record what they cost.

## 2. The route reshuffle

### 2.1 Why the Dashboard has to move

`/` is claimed by `(dashboard)/page.tsx`, which sits inside the `(dashboard)`
route group and therefore inside `AppShell`. Anything rendered there is behind
the session gate: an anonymous visitor to `/` is redirected to
`/login?next=%2F` by `app-shell-runtime.tsx:72`. A landing page for people who
have not signed in cannot live inside that group, and two files cannot both own
`/`. So the Dashboard moves to `/dashboard` and `/` becomes a new public route
outside the group.

### 2.2 The coupling that must not be missed

This is the one part of the move that is not mechanical.

`app-shell-runtime.tsx:86-95` redirects a signed-in caller away from any route
their scopes do not cover, and it decides that by matching `pathname` against
the **navigation catalog's own `href` values**:

```ts
const onForbiddenRoute =
  status === 'authenticated' &&
  NAV.some((item) => item.requires && !can(item.requires) && isActive(pathname, item.href));
```

The Dashboard's catalog entry requires `usage:read_all`
(`app-shell-navigation-catalog.tsx:179-182`), which the `user` role does not
hold. So today a `user` who opens `/` is matched by this guard, is sent to
`/chat`, and — critically — `main` renders `null` for the frame in between
(`app-shell-runtime.tsx:200`), so the Dashboard's queries never mount and never
fire.

The long comment at `app-shell-runtime.tsx:180-194` records why that matters:
letting the forbidden page mount fires `/admin/dashboard` and `/admin/usage`,
each refusal writes an `authz.denied` audit row, and on 2026-08-14 exactly those
rows were **misread as a real access problem** during an audit review. The
guard is what stopped that recurring.

**If the route moves to `/dashboard` and the catalog entry is left pointing at
`/`, the guard silently stops matching**, the Dashboard mounts for every `user`
who signs in, and the audit noise returns — with no test failure, because
nothing asserts the guard against a literal path. The catalog `href` and the
directory name must change in the same commit, and §10 adds a test that pins
them together.

### 2.3 Complete list of changes

| File | Change |
|---|---|
| `app/(dashboard)/page.tsx` | Move to `app/(dashboard)/dashboard/page.tsx`, unchanged content |
| `app/page.tsx` | **New.** The landing page. Outside `(dashboard)`, so no session gate |
| `app-shell-navigation-catalog.tsx:179` | `href: '/'` → `href: '/dashboard'` |
| `app-shell-navigation-catalog.tsx:277` | Delete the `if (href === '/') return pathname === '/'` special case; no href is `/` any more, and `startsWith` is then correct for every entry |
| `lib/safe-redirect.ts:18` | `DEFAULT_REDIRECT` `'/'` → `'/dashboard'`. Without this, sign-in with no `next` lands on the marketing page |
| `features/auth/hooks/use-login.ts:29` | Default parameter `'/'` → `'/dashboard'` |
| `features/auth/components/login-form.tsx:34` | Same default |
| `features/auth/components/accept-invitation-form.tsx:88` | `router.replace('/')` → `'/dashboard'` |
| `components/composed/app-shell-test-support.tsx:33,94` | Default `pathname` used by the shell tests |
| `components/composed/app-shell.access.test.tsx:30,37,48` | `signedInWith(..., '/')` → `'/dashboard'` |
| `components/composed/app-shell-desktop-navigation.tsx:18` | Wrap `<Logo>` in `<Link href="/">` |
| `components/composed/app-shell-header.tsx` | Add a clickable home mark at the left of the header (see §2.5) |

Checked and **not** affected: `src/middleware.ts` matches only `/admin/:path*`;
`lib/safe-redirect.test.ts` asserts against the `DEFAULT_REDIRECT` constant
rather than a literal, so it keeps passing; `e2e/auth.spec.ts:104` expects
`/chat` because it passes `next=%2Fchat` explicitly. No Playwright spec
navigates to `/`.

### 2.4 Sign-out, and the tailnet entrance

Two consequences that follow from the move and are decided here rather than
left to discover:

**Sign-out keeps going to `/login`.** `lib/session/provider.tsx:53` does
`window.location.assign('/login')`. Sending it to the landing page instead
would be defensible, but somebody who just signed out of an admin console is
usually signing back in, and the landing page would add a click to that. Keep
it.

**The tailnet entrance now opens on a marketing page.** On the tailnet there is
no login screen at all (`frontend.md` §3); identity arrives as a header. An
operator whose bookmark is `/` will land on the landing page and need one click
to reach the console. That is the direct cost of item 3 in §1 — the logo has to
lead *somewhere*, and the requester chose a landing page over a redirect. It is
acceptable because the landing page shows the signed-in account and a
prominent console action (§3), and because the fix for a daily user is to
bookmark `/dashboard`. **Do not "solve" this with an auth-mode redirect at
`/`**: that would make the logo unclickable-in-effect for exactly the people who
asked for it to be clickable.

### 2.5 The logo as a home link

The mark today appears in exactly one place and is not a link: the desktop
sidebar, `app-shell-desktop-navigation.tsx:18`, at 48px. The header
(`app-shell-header.tsx`) has no mark at all, and below the `lg` breakpoint the
sidebar is `display:none`, so on a phone there is currently nothing in the
top-left to click.

`logo.tsx:18` states the binding constraint: the mark is an interlocking
monogram that stops resolving below about 48px, and "do not reach for a smaller
size than the ones offered here". The header row is roughly 48px tall including
padding, so the image cannot go there at a size where it reads.

So: wrap the sidebar mark in `<Link href="/">`, and give the header a **textual**
home link rather than a shrunken monogram. Both need an accessible name that
says where they go ("RCSL AI Nexus, home") rather than just "RCSL".

## 3. The landing page

Scope: **one screen**, brand-forward, not a full marketing site.

- A full-viewport hero carrying the 3D treatment, the product name, and one
  line of positioning.
- A single primary action, which switches on session state read from the
  existing `useSession()`:
  - unauthenticated → "Sign in", to `/login`
  - authenticated → the account's display name plus "Go to the console", to
    `/dashboard`
- Nothing below the fold. If it grows into feature sections later, the material
  is in `docs/ARCHITECTURE.md` and `README.md`.

`SessionProvider` already sits in the root layout (`app/layout.tsx:42`), so `/`
gets session state with no new provider and, more importantly, **no new
request**: `/admin/me` is already fetched on every route including `/login`. An
anonymous visitor's 401 there is existing behaviour, not something this page
introduces.

The landing page must render correctly in all three session states —
`loading`, `unauthenticated`, `authenticated` — without flashing the wrong
call to action. Render the neutral state while `loading`.

## 4. Curtain A — depth tunnel

**Scene.** The camera travels along `-Z` through a corridor of emissive
rectangular rings. Rings scale up and fade as they pass the near plane. At the
end of the run a light source rushes the camera, the frame washes to the
theme's foreground colour, and the wash retreats to reveal the login card
settling from a slight scale and blur.

**Duration** about 2.0s. **Mount point:** `app/(auth)/login/page.tsx`, *not*
`app/(auth)/layout.tsx`.

That distinction matters. The `(auth)` layout also wraps `accept-invite` and
`reset-password`, both of which are reached from single-use emailed links
(`frontend.md` §3). Putting a two-second curtain in front of somebody
completing an invitation — a flow that ends in recovery codes shown exactly
once — is the wrong place for a flourish. The curtain is a fixed-position
overlay, so mounting it from the page rather than the layout costs nothing.

**When it plays.** First visit to `/login` in a browser tab, recorded in
`sessionStorage`. It must **not** play when:

- `prefers-reduced-motion: reduce` is set;
- the URL carries a `next` parameter. That parameter means the visitor was
  *bounced* here — either by `app-shell-runtime.tsx:72-76` on an expired
  session, or by the unauthorized bridge — and someone whose session just
  expired mid-task should not be made to watch a two-second flight before they
  can type their password. This rule is more important than the sessionStorage
  one and is independent of it.

## 5. Curtain B — layer dive

**Scene.** Five or six translucent shells stacked along `Z`, each carrying a
faint structural grid. The camera descends through them; each shell, as it is
passed, rotates and slides out of frame. The run ends on the plane where the
real interface sits, and the canvas fades as the application settles from
`scale(0.98)`.

**Duration** about 1.6s, **always skippable** — any key, any click, `Escape`.
Skipping **aborts immediately**; it does not fast-forward to the end of the
timeline. That is the whole value of the escape hatch for someone who reloads
often.

## 6. Why Curtain B needs its own state machine

### 6.1 The problem with binding it to `status === 'loading'`

The obvious implementation is to replace the spinner branch of
`renderSessionGate` (`app-shell-session-gate.tsx:22-32`) with the curtain. That
does not work for the case the curtain exists for.

`use-login.ts:77-82` finishes a sign-in like this:

```ts
await queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
router.replace(redirectTo);
```

Identity is refetched **before** the navigation. By the time `AppShell` mounts,
the session query is usually already resolved, so `status` is `authenticated`
and the `loading` branch either never renders or renders for a single frame.
The curtain would be invisible on precisely the entry that most deserves it.

### 6.2 The shape instead

A small state machine owned by the shell, independent of the query's status:

- `playing` on mount, with a **minimum duration**. The timeline runs to
  completion even when the data arrived first.
- The curtain covers the gate's `loading` state when there is one, and covers
  nothing but itself when there is not.
- It resolves on `max(minimum duration, session settled)`, or immediately on
  skip.
- It **must not** cover the gate's other branches. `status === 'error'` and the
  tailnet `unauthenticated` branch are states where the reader needs to see a
  message and a retry button, not a flight through shells. Those two early
  returns in `renderSessionGate` keep precedence over the curtain.
- It must not persist across the `!me` early return at
  `app-shell-runtime.tsx:100`, which is the redirect-to-login path. Curtain up
  over a redirect would read as a hang.

### 6.3 The cost of "every entry"

Curtain B plays in full on every entry to the application, including every
reload. Consequences, accepted knowingly:

- Every entry constructs a WebGL context and compiles shaders — see §7.4.
- The 3D chunk is on the critical path of the authenticated shell, not just of
  two public pages (§7.5).
- Tailnet users see Curtain B and never Curtain A, since they have no login
  screen.

The mitigation is the skip, which is why §5 requires abort-not-fast-forward and
a very wide trigger surface.

## 7. The 3D stack

### 7.1 Dependencies

`three`, `@react-three/fiber`, `@react-three/drei` — all MIT. The project is
React 19.2.4 / Next 15.5.21, which needs the R3F v9 line; `drei` must be pinned
to the release that declares R3F v9 as its peer. **Verify the peer ranges at
install time rather than trusting this paragraph**, which was written without
network access.

`motion` / `framer-motion` was considered earlier in the discussion and is
**not** being added. The 3D work is a command-driven `requestAnimationFrame`
timeline, and the DOM-side settling is two or three transitions that plain CSS
already covers. One new rendering dependency is enough.

Import `drei` helpers by name, never namespace-wide, or the tree-shaking that
justifies taking it at all does not happen.

### 7.2 Fake bloom

Glow is drawn as additive-blended sprites layered under the emissive geometry,
not as a post-processing pass. `EffectComposer` with `UnrealBloomPass` looks
better in isolation but adds several full-screen passes per frame, which is
paid on every reload (§6.3) and lands hardest on the machines least able to
afford it. On a dark field with emissive line work the difference is small.

### 7.3 Theme-aware palettes

Both curtains read the resolved theme from `next-themes` and pick one of two
palettes:

- **dark** — near-black field, cyan-to-white emissive line work
- **light** — bright low-contrast field, deep-blue line work, and a
  correspondingly gentler wash

Two honest warnings. First, the light palette is inherently less dramatic;
"spectacular" on a bright field means restraint, and trying to match the dark
version's impact will produce something that flashes. Second, `ThemeProvider`
runs with `defaultTheme="system"` and `enableSystem`
(`lib/theme-provider.tsx:16-19`), so the resolved theme is **not known during
server rendering**. The curtain must not render 3D content before the theme
resolves, or the first frame will be the wrong palette. Hold the neutral cover
layer (§7.4) until then.

### 7.4 Degradation ladder, and the cover layer

In order:

1. `prefers-reduced-motion: reduce` → no curtain at all. Not a shortened
   curtain — nothing is mounted, nothing is covered.
2. No WebGL context available → the CSS fallback.
3. WebGL available but the first ~300ms measures a poor frame rate → abandon
   the timeline and fall back.
4. Any exception during scene construction → fall back.

The **fallback** is a single CSS `perspective` scale-and-fade of about 400ms.
It is a degradation, not a second animation to maintain, and it must stay small
enough that nobody is tempted to grow it.

Independently of the ladder, every curtain paints an opaque **cover layer** in
the theme background colour *before* any WebGL work begins, and removes it only
once the first frame has been drawn. Context creation plus shader compilation
is on the order of 50–150ms cold; without the cover that interval is a visible
flash of the page underneath.

**The curtain must never be able to leave the viewer on a blank screen.** Every
path — success, fallback, exception, skip — ends with the curtain removed. A
hard watchdog timeout should tear it down regardless of state.

### 7.5 Bundle

Load the 3D module through `next/dynamic` with `ssr: false`, so it is a
separate chunk and never enters the server render. Three consumers: the landing
page, the login page, and the app shell.

Rough expectation, to be measured rather than believed: `three` alone is around
150KB gzipped; `drei` adds whatever its used helpers pull in. This will be by a
wide margin the largest dependency in the frontend. Record the real
`next build` numbers, before and after, in `docs/PROGRESS.md` when the work
lands.

## 8. Accessibility

- `prefers-reduced-motion: reduce` removes both curtains entirely (§7.4).
- Curtains are `aria-hidden` decoration. They must not trap focus, and focus
  must land where it would have landed without them — the login form's first
  field, or `#main-content`.
- The skip affordance is visibly labelled, not folklore. A curtain that can
  only be dismissed by people who guess to press a key is not skippable.
- The skip-to-content link at `app-shell-runtime.tsx:143-148` must still be the
  first thing in the tab order once the curtain resolves.
- No parallax was requested and none is planned, which also removes a class of
  motion-sensitivity problem.

## 9. Security

Nothing here touches an authorization boundary, with one exception already
covered: §2.2, where the route move can silently disable a guard whose failure
mode is audit-log noise rather than access. The landing page reads session
state that the root layout already fetches and displays a display name that the
authenticated user owns; it exposes nothing new, and it must not render
anything scope-dependent.

## 10. Test impact

Verified against this repository on 2026-08-26 (jsdom 29.1.1, as pinned):

| Fact | Consequence |
|---|---|
| `window.matchMedia` is **undefined** in jsdom | An unguarded `matchMedia('(prefers-reduced-motion: reduce)')` **throws** in Vitest. Nothing in `src/` calls it today, so there is no polyfill in `vitest.setup.ts`. Guard the call *and* add the polyfill |
| `window.WebGLRenderingContext` is **undefined** in jsdom | WebGL detection returns false in tests, so the fallback path is what unit tests exercise. This is convenient and deterministic — but it means the WebGL path itself is never covered by Vitest |
| `sessionStorage` **works** in Vitest | `environmentOptions.jsdom.url` is set (`vitest.config.ts:20`), so the opaque-origin restriction does not apply. Several assistant tests already use it. Curtain A's once-per-tab gate needs no new setup. (`localStorage` is the one that needed the polyfill at `vitest.setup.ts:14-32`.) |

Work required:

- **`app-shell.*.test.tsx` will render Curtain B.** Three suites —
  `app-shell.access.test.tsx`, `app-shell.roles.test.tsx`,
  `app-shell.groups.test.tsx` — render `AppShell` in an authenticated state and
  assert on navigation and page content. With detection falling back (no
  WebGL), they should pass, but they will now render an overlay that did not
  exist when their queries were written. Add a mock for the curtain module in
  `app-shell-test-support.tsx` so these suites test the shell rather than the
  animation, and cover the curtain's state machine in its own suite.
- **`playwright.config.ts` gets `use: { reducedMotion: 'reduce' }`.** Without
  it, `e2e/auth.spec.ts:86` navigates to `/login` and Curtain A's overlay
  intercepts the pointer events the spec then dispatches at the form. With
  reduced motion honoured per §7.4, no curtain is mounted and every existing
  spec behaves as it does today. This is also an admission: **CI will not
  exercise the curtains at all.** They are decoration with a hard requirement
  never to block, and that requirement is what the unit tests should assert.
- **A test pinning §2.2**: assert that the navigation catalog's Dashboard entry
  href matches the route the Dashboard actually occupies, so that moving one
  without the other fails a test instead of quietly restoring the 2026-08-14
  audit noise.
- Landing page tests: the three session states, and that the primary action
  points at `/login` or `/dashboard` correspondingly.

Frontend test counts are stated in `docs/ROADMAP.md` and `docs/PROGRESS.md`.
Both need updating when this lands; the roadmap's own history shows that number
going stale repeatedly.

## 11. Licensing

`three`, `@react-three/fiber` and `@react-three/drei` are MIT, which
`ATTRIBUTIONS.md` already establishes is compatible with this project's
AGPL-3.0 licence. That file covers work incorporated *beyond* declared
dependencies, and these are declared dependencies in `frontend/package.json` —
so strictly they belong with everything else in that manifest and need no
entry. Add one anyway if the curtains end up adapting a published shader or
scene from elsewhere, which is the case the file exists for.

## 12. Build order

Deliberately three commits, not one.

1. **Route reshuffle only.** The move, all ten call sites from §2.3, the
   clickable logo, the new pin test from §10. No landing page, no animation.
   The entire existing suite — Vitest and Playwright — must be green at this
   point. This is the step that can break authorization behaviour, and it
   should be verifiable without a single line of 3D in the diff.
2. **Landing page**, static, no 3D. Session-aware call to action, tests for the
   three states.
3. **Curtains**, A then B, with the dependency, the fallback ladder, the mocks
   and the Playwright config change.

If the animation later needs rework, the foundation underneath it has already
been proven separately.

## 13. Acceptance criteria

- Signing in with no `next` lands on `/dashboard`; with `next=/chat`, on
  `/chat`.
- A `user` (no `usage:read_all`) who signs in is redirected to `/chat` **and
  the Dashboard's queries never fire** — no `authz.denied` rows for
  `/admin/dashboard` or `/admin/usage`.
- The top-left logo reaches `/` from every authenticated screen, on desktop and
  below the `lg` breakpoint.
- `/` renders for an anonymous visitor without redirecting to `/login`.
- With `prefers-reduced-motion: reduce`, no curtain is mounted anywhere.
- With WebGL disabled, both entries still complete, via the CSS fallback.
- Curtain B is dismissable by key, click and `Escape`, and dismissal is
  immediate.
- Arriving at `/login?next=...` never plays Curtain A.
- No path leaves a curtain on screen: verify by killing the WebGL context
  mid-animation.
- Ten consecutive reloads of `/dashboard` do not produce WebGL context-loss
  warnings — the check for the disposal requirement in §7.4.

## 14. Open questions

1. **Landing page copy.** The positioning line is unwritten. `README.md` and
   `docs/ARCHITECTURE.md` are the source material.
2. **Does the tailnet entrance want its own landing behaviour?** §2.4 argues
   against, and this plan assumes not. Revisit only if daily operators complain
   about the extra click.
3. **Measured bundle cost.** §7.5 is an estimate. If the real figure is
   materially worse than ~150KB gzipped, the honest response is to reconsider
   `drei`, then R3F, then WebGL — in that order, since each step back is
   smaller than the one after it.
4. **Does Curtain B survive contact with daily use?** It plays on every reload
   by decision. If the skip is being used reflexively after a week, the setting
   to change is the frequency, not the animation.
