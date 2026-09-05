# Plan: Information Discovery and Interface Polish

**Status: proposed 2026-08-30.** Written against `main` at `53c7f0f` after a
browser review at 1280 × 720 and 390 × 844. This plan is the second of two
companion UI work packages. The first is
[responsive-management-workflows.md](./responsive-management-workflows.md).

This package groups work whose common purpose is reducing the time between a
reader's intent and the relevant information: finding a reference section,
finding an error code, understanding a degraded landing page, recovering from
the login screen, and recognising disclosure state. These changes share content
structure, state language, anchors, and a restrained micro-interaction
vocabulary rather than the authenticated shell's responsive geometry.

## 1. Priority and scope

This package owns the remaining seven items in the global value ranking:

| Global priority | Item | Value |
|---:|---|---|
| 4 | Add API Reference section navigation | High: the mobile document is about 18,748px tall |
| 5 | Add error-code search and filtering | High: integrators usually arrive with a specific status or code |
| 6 | Replace the mobile error-table presentation | Medium-high: the current table requires horizontal scrolling |
| 7 | Make the landing degraded state compact and actionable | Medium-high: an API outage currently takes over the primary action area |
| 10 | Shorten the forgotten-password guidance | Medium-low: improves a frequent authentication screen without changing policy |
| 11 | Link the login brand to the public home page | Low: inexpensive and provides a clear escape route |
| 12 | Standardise disclosure and menu micro-interactions | Low: consistency and state legibility rather than new capability |

Priorities 1–3, 8, and 9 belong to the responsive-workflows plan.

### Explicitly frozen

Entry animation is outside this project. The existing decisions in
[landing-page-and-entry-transitions.md](./landing-page-and-entry-transitions.md)
remain authoritative. Do not modify the login curtain, application curtain,
Three.js scenes, landing orbit, durations, watchdogs, skip behaviour, or entry
frequency.

The micro-interactions below apply only to controls the reader has already
reached: disclosures, menus, filtered results, and inline status. They must
never cover the viewport or delay first interaction.

## 2. API Reference as a lookup surface

### 2.1 Observed problem

`features/gateway/components/api-reference.tsx` renders every reference section
in one `space-y-8` flow. That is accurate and exportable, but it is shaped like a
document to read from the beginning rather than a reference to query. At 390 ×
844 the rendered page was approximately 18,748px high. The Errors section alone
contains a long three-column table whose minimum useful width is greater than
the mobile content column.

The page already has two valuable properties that must survive:

- Copy as Markdown and Download `.md` export the complete contract.
- A failed live gateway-information request leaves the static contract visible
  and labels only the origin and capability list as unavailable.

### 2.2 One section catalogue

Introduce one ordered section catalogue containing a stable id, visible title,
and rendering key for every top-level API Reference section. Use it to drive:

- `id` and `aria-labelledby` on each section;
- the desktop table of contents;
- the mobile jump control;
- scrollspy state;
- tests that every catalogue entry resolves to exactly one heading.

Do not maintain a second hand-written list beside the component order. A stale
table of contents is worse than no table of contents because it asserts that a
section does not exist.

Desktop uses a sticky in-page navigation column where the content width permits
it. Mobile uses a compact "Jump to section" control near the export actions.
Changing the selected section scrolls the existing main region; it does not
change the Next.js route or create browser-history entries for passive
scrollspy updates. Direct `#section-id` links remain shareable.

The table of contents and jump control carry `data-md-skip`, so an exported
reference does not begin with interface chrome.

### 2.3 Scrollspy

Use `IntersectionObserver` against section headings inside the shell's scrolling
`main`, not against the document viewport. Select the first heading at or below
the reading offset, with the preceding section as the fallback while a long
section fills the viewport.

The active indicator may move or fade over 120–180ms. It must not smooth-scroll
the page in response to ordinary user scrolling. Explicit section jumps may use
native smooth scrolling only when reduced motion is not requested.

## 3. Error lookup and responsive presentation

### 3.1 Structured error catalogue

Move the authored error rows in `api-reference-errors.tsx` into one typed data
catalogue. Each record contains:

- HTTP status or stream marker;
- stable error code;
- the existing rich remediation content;
- optional search aliases only where readers use a term not present in the
  visible content.

The catalogue feeds search, the desktop table, the mobile presentation, and the
Markdown export. The prose remains authored once. Do not scrape rendered text
or duplicate descriptions across two responsive components.

### 3.2 Search behaviour

Place a labelled search field at the start of Errors. Match case-insensitively
against status, code, and visible remediation text. Queries such as `429`,
`quota_exceeded`, `timeout`, and `request id` must produce useful results.

Filtering is local and immediate; this catalogue is small enough that debounce
would add latency without saving meaningful work. Announce the result count in
a polite live region. A no-results state offers Clear search and does not hide
the Errors heading or the field that can recover it.

The current query does not enter the URL in the first implementation. A shared
filtered URL is useful only if the rest of the reference also adopts durable
query state; adding it here alone would make back/forward behaviour inconsistent.

### 3.3 Desktop table, mobile cards

Keep the table at `md` and above, where comparing status, code, and remedy
across rows is valuable. Below `md`, render one card per filtered record:

- status and code form the card heading;
- remediation is the body;
- the code remains selectable and visually distinct;
- no card requires horizontal scrolling.

Both presentations render from the same catalogue. The mobile cards carry
`data-md-skip`; the desktop table remains the single Markdown-export source, so
the export cannot contain every error twice even though CSS keeps both
responsive renderers in the DOM.

Do not collapse remediation behind an accordion by default. A reference search
result should show why it matched, browser find-in-page should reach the text,
and a reader comparing two similar 429 or 503 conditions should not have to open
each one first.

## 4. Landing degraded state

### 4.1 Preserve the truthful diagnosis

The landing page currently replaces its normal primary action with
`ErrorState` when `/admin/me` cannot reach the admin API. That is correct in one
important respect: Sign in would fail against the same API, and the tailnet
entrance has no sign-in route. Do not restore a live-looking CTA that leads to a
dead end.

### 4.2 Reduce visual takeover

Replace the large generic error card in the hero action slot with a compact,
landing-specific status block:

- title: management service unavailable;
- one sentence stating that sign-in or console access cannot be checked;
- Retry as the primary available action;
- technical error detail behind an inline disclosure, not as the hero's second
  headline;
- an `aria-live` status for retry progress and recovery.

Keep the product statement, header, and footer visually present on mobile. The
degraded state should explain why the door is unavailable without turning the
public front page into a generic error screen.

Do not add a Troubleshooting link unless the application has a real,
deployment-appropriate destination. A label that promises help and points to a
repository path unavailable to the deployed reader is not an action.

## 5. Login recovery copy and home route

### 5.1 Short guidance

Replace the current multi-line paragraph with:

> Forgot your password? Ask an administrator for a single-use reset link.

If more explanation is required, place it in a native disclosure below that
sentence. Keep the two security constraints explicit:

- there is no self-service reset endpoint;
- the UI must not reveal whether an account exists.

Do not add a "Forgot password" form, email field, or account-specific error.
The generic password failure and the administrator-issued reset flow remain
unchanged.

### 5.2 Brand as a home link

In `app/(auth)/layout.tsx`, wrap the login brand block in a link to `/` with an
accessible name such as "RCSL AI Nexus, home". Preserve the current large logo
size and centred composition; this is a navigation affordance, not a redesign of
the authentication card.

The first Tab should still reach the login field unless a keyboard reader moves
backward or intentionally navigates the brand. `autoFocus` on Login remains the
initial focus contract.

## 6. Micro-interaction vocabulary

Standardise only the small state changes already present across disclosures,
menus, copy feedback, and filtered-result changes:

| Interaction | Motion | Ceiling |
|---|---|---:|
| Disclosure chevron | quarter turn | 160ms |
| Menu/popover appearance | opacity plus 2–4px translation | 160ms |
| Copy-success icon swap | opacity | 120ms |
| Filtered-result insertion/removal | opacity only, where it does not reorder focus | 180ms |
| Active in-page indicator | colour/opacity or short translation | 180ms |

Use one easing family and shared duration tokens rather than accumulating
`duration-100`, `duration-150`, and component-specific arbitrary values. The
tokens may be CSS custom properties in `globals.css` or documented Tailwind
utilities, but they must be consumable by the existing copied-in UI primitives.

With `prefers-reduced-motion: reduce`, durations become effectively immediate.
Focus, visibility, and accessible state change at the start of the interaction;
no control waits for `transitionend` to become operable.

Do not add route fades, table-row choreography, skeleton shimmer beyond what
already exists, scroll-linked parallax, or a motion library. This project needs
a small vocabulary, not a second animation system.

## 7. Shared implementation sequence

1. Define the API Reference section catalogue and add stable anchors.
2. Add desktop and mobile section navigation, then scrollspy and direct-anchor
   coverage.
3. Convert Errors to a typed catalogue without changing its rendered content.
4. Add local search and the mobile card renderer; verify Markdown contains one
   complete error list.
5. Build the landing-specific degraded state with retry and recovery behaviour.
6. Shorten login recovery copy and link the brand home.
7. Extract the restrained duration/easing vocabulary and apply it only to the
   controls named in this plan.

## 8. Verification

### Automated

- Assert that every section-catalogue id resolves to one heading and every
  rendered top-level section appears in the catalogue.
- Test direct anchor loading, explicit mobile jumps, and scrollspy inside the
  shell's scrolling `main`.
- Test error search by status, exact code, partial code, remediation text, no
  results, and Clear search.
- Assert that desktop and mobile error renderers derive from the same record
  count and that Markdown export contains each error code once.
- Extend landing-page tests for loading, unavailable, retrying, recovered,
  unauthenticated, authenticated, and tailnet-lost states.
- Extend authentication layout tests for the home link without changing the
  Login field's initial focus.
- Run disclosure and menu tests with reduced motion and prove state changes do
  not depend on an animation finishing.

### Manual

- At 390 × 844, reach Endpoint, Errors, and Limits from the top without manual
  page-length scrolling.
- Search for two conditions sharing a status, such as the 429 and 503 pairs,
  and compare their remedies without horizontal scrolling.
- Load a direct `#errors` URL and confirm the heading is not hidden under shell
  chrome.
- Export Markdown on desktop and mobile and compare the section and error-code
  counts.
- Simulate an unreachable admin API on the landing page and confirm the product
  identity remains visible while the unavailable action remains truthful.
- At 200% text zoom, login recovery guidance and the home link remain legible
  without pushing the card outside the viewport.

## 9. Acceptance criteria

- Every API Reference top-level section has a stable direct link and appears in
  one responsive navigation surface.
- The active section is conveyed without changing history during passive
  scrolling.
- Errors are searchable by status, code, and remedy, with an announced result
  count and recoverable no-results state.
- The mobile error reference requires no horizontal scrolling; the desktop
  comparison table remains available.
- Markdown export contains the complete reference and exactly one copy of each
  error record, without navigation chrome.
- An unavailable admin API produces a compact, truthful landing status with a
  working Retry action and no dead Sign in action.
- Login recovery copy is concise, retains the no-self-service policy, and does
  not create an account-enumeration signal.
- The authentication brand links to `/` while Login remains initially focused.
- Named micro-interactions use the shared duration/easing vocabulary and become
  immediate under reduced motion.
- No entry-transition file, scene, duration, trigger, frequency, or test is
  changed by this project.
