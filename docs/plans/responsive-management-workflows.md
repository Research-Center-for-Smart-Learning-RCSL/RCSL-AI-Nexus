# Plan: Responsive Management Workflows

**Status: proposed 2026-08-30.** Written against `main` at `53c7f0f` after a
browser review at 1280 × 720 and 390 × 844. This plan is the first of two
companion UI work packages. The second is
[information-discovery-and-interface-polish.md](./information-discovery-and-interface-polish.md).

This package groups the changes that share the management shell, narrow-screen
breakpoints, bottom composers, focus ownership, and panel geometry. Implementing
them together avoids solving the same 390px width constraint independently in
the header, Chat, the assistant, and the two side panels.

## 1. Priority and scope

The global backlog was ranked by affected users, severity, frequency, and
implementation cost. This package owns five items:

| Global priority | Item | Value |
|---:|---|---|
| 1 | Recompose the mobile management header | Very high: every authenticated screen |
| 2 | Split the mobile Chat composer into usable rows | Very high: the primary input is currently squeezed nearly closed |
| 3 | Recompose the mobile assistant composer | High: the same narrow-row failure appears in the assistant |
| 8 | Add spatial motion to mobile navigation | Medium: improves orientation without delaying work |
| 9 | Add spatial motion to the assistant drawer | Medium: explains the desktop width change and mobile takeover |

Priorities 4–7 and 10–12 belong to the companion plan.

### Explicitly frozen

The entry experience is not part of this project. Do not change:

- `LoginEntryTransition` or `AppEntryTransition`;
- `EntryCurtain`, its durations, watchdogs, skip behaviour, or frequency;
- `entry-transition-scenes.tsx`, any Three.js scene, or the landing-page orbit;
- the existing entry-transition tests or bundle boundary, except where an
  unrelated test fixture must keep compiling.

The panel motion in this plan begins only after an authenticated interface is
already usable. It is ordinary state-change feedback, not an entry animation.

## 2. Observed constraints

### 2.1 Mobile header

At 390px the header presents the menu, home link, two-line identity, assistant,
theme, account, and sign-out controls in one row. The identity truncates and the
five adjacent icon targets become a sequence a reader has to remember. The
controls are individually valid; the composition is not.

The relevant implementation is split between
`components/composed/app-shell-header.tsx` and
`components/composed/app-shell-runtime.tsx`. Any consolidation must preserve:

- the mobile-navigation focus return;
- the assistant's open/closed state and accessible name;
- the absence of Account and Sign out on the tailnet entrance;
- the full identity and role somewhere visible without relying on a tooltip;
- the textual home link below the desktop-sidebar breakpoint.

### 2.2 Chat composer

`features/chat/components/chat-composer.tsx` puts a fixed-width capability
selector, Thinking, the message input, Send, and Clear in one flex row. At
390px the layout technically remains inside the viewport by shrinking the
message input until it is no longer a useful writing surface. Avoiding overflow
is not sufficient if the primary control absorbs all of the compression.

### 2.3 Assistant composer

The full-screen mobile assistant is legible, but its footer repeats the same
shape: input, Ask, and Clear compete in one row. Clear is a transcript-level
operation, not part of composing the next question, so it should not consume
permanent width beside every question.

### 2.4 Panels

Both `app-shell-mobile-navigation.tsx` and `assistant-drawer.tsx` conditionally
mount their panels. The state is correct, including Escape and focus return for
navigation, but the visual change is instantaneous. On desktop the assistant
also changes the shell's reserved width immediately, so content jumps from one
geometry to another with no spatial explanation.

## 3. Decisions

### 3.1 Mobile header: two stable destinations, one account menu

Below `sm`, the header contains four conceptual controls:

1. the navigation-menu button;
2. the compact textual home link;
3. the assistant button;
4. one account-and-appearance menu.

The account menu trigger may show the display name when space permits, but it
must not require the login and role to remain inline. Its menu contains the
complete display name, login, human-readable role, theme control, Account link
where local credentials exist, and Sign out where a local session exists.

At `sm` and above, the existing identity block and labelled Assistant control
may remain. At `md` and above, Account and Sign out may remain directly visible
if the row has room. There must be one source of truth for the actions so that
the direct controls and compact menu cannot drift in availability or labels.

Use a real menu primitive with keyboard navigation, Escape dismissal, outside
click dismissal, and focus return. Do not implement the menu as an unlabelled
popover containing arbitrary buttons.

### 3.2 Chat: settings row plus writing row

Below `sm`, preserve the existing knowledge-base control and description, then
render the composer as two rows:

- a settings row for Capability and Thinking;
- a writing row in which the message field owns the available width and Send
  remains reachable.

Clear moves to transcript-level chrome, adjacent to the transcript rather than
to Send. It stays disabled when there is nothing to clear and retains its
confirmation contract if one is introduced later.

Use a multiline message field that grows to a bounded height and then scrolls
internally. Enter submits only if that remains the documented keyboard
behaviour; Shift+Enter must always insert a newline. Do not make a send-key
change accidentally as part of replacing `Input`.

Desktop may retain the compact single-row settings and actions, provided the
message field has a documented minimum usable width before the layout wraps.

### 3.3 Assistant: keep the question primary

On mobile, the assistant footer contains the question field and Ask. Clear
moves into the assistant header or a labelled overflow menu. Stop replaces Ask
in place while streaming, as it does today, so the action does not move during
the wait.

The field may grow to a small bounded multiline height. The assistant is an
advisory surface rather than a full chat screen, so it should not consume more
than roughly one quarter of a phone viewport before scrolling internally.

### 3.4 Navigation motion

Opening mobile navigation uses one short spatial transition:

- panel: `translateX(-100%)` to `translateX(0)`;
- backdrop: transparent to its existing black opacity;
- duration: 160–200ms;
- easing: decelerate on open, accelerate on close;
- no spring, overshoot, scale, or content stagger.

The panel must remain mounted long enough to finish its exit, but become inert
and leave the tab order as soon as close begins. Focus returns to the menu
button after the panel is closed. With `prefers-reduced-motion: reduce`, both
states change without an animated interval.

### 3.5 Assistant motion and desktop geometry

The assistant uses the same 160–200ms motion vocabulary:

- mobile: translate from the inline end and cover the viewport;
- desktop: translate from the inline end while the shell moves to its reserved
  width;
- backdrop: none on desktop, because the assistant is deliberately non-modal;
- reduced motion: immediate state change.

The drawer and reserved content width must describe one movement. Do not let
the content snap first and animate an already stationary panel over the space,
or animate the drawer over a table and reserve the width only at the end. A CSS
grid column transition is preferable to independently timed padding and panel
transforms, provided charts and tables receive resize observations throughout
the transition. If that causes unstable table reflow, keep the desktop width
change immediate and animate only the drawer; correctness outranks polish.

Widening and narrowing the assistant use the same duration and preserve the
stored width preference in `features/assistant/width.ts`.

## 4. Shared implementation sequence

1. Extract a shared account-action definition and build the compact header
   menu without removing the existing desktop controls.
2. Add narrow-screen header coverage, including local and tailnet modes.
3. Recompose Chat and assistant footers at the same breakpoint and introduce a
   shared bounded multiline-field treatment if both need one.
4. Move Clear to transcript-level controls and prove its disabled and streaming
   states.
5. Add a shared panel-motion vocabulary and reduced-motion override.
6. Apply it to mobile navigation, then the assistant drawer and width toggle.
7. Run the full frontend unit suite and focused browser checks at 390, 768,
   1024, and 1280 CSS pixels.

## 5. Verification

### Automated

- Extend shell tests for the compact account menu under local and tailnet
  authentication.
- Assert that opening and closing navigation preserves focus, Escape dismissal,
  `aria-expanded`, and removal from the closed tab order.
- Add component tests for the two Chat layouts and the assistant footer,
  including streaming, empty, and populated transcripts.
- Add a browser path at 390 × 844 that proves the Chat and assistant message
  fields have usable width and that the document does not scroll horizontally.
- Run that browser path with reduced motion and prove no panel waits on an
  animation event to become usable or to close.

### Manual

- At 200% text zoom, every header action remains reachable and the complete
  identity remains available from the account menu.
- At 390px, a multi-line Chat message can be written without hiding Capability,
  Thinking, or Send.
- On mobile, the assistant's Ask/Stop action does not move when streaming
  begins.
- On desktop, opening and widening the assistant never puts it over the main
  content and never leaves a blank reserved column after close.
- Pointer, keyboard, and screen-reader navigation all identify the same account
  actions with the same labels.

## 6. Acceptance criteria

- No authenticated screen has horizontal document overflow at 390px.
- The mobile header exposes navigation, home, assistant, theme, account, and
  sign-out where applicable without rendering all of them as peer controls in
  one row.
- The full login and role are available without hover.
- Chat's message field remains a primary writing surface at 390px, and Clear no
  longer competes with Send for composer width.
- The assistant question field and Ask/Stop remain usable at 390px, and Clear is
  still discoverable.
- Mobile navigation and the assistant communicate direction with no more than
  200ms of state-change motion.
- Reduced-motion users receive immediate panel state changes.
- No entry-transition file, scene, duration, trigger, frequency, or test is
  changed by this project.
