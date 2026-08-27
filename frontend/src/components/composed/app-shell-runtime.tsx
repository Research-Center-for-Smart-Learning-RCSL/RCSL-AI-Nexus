'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';

import { cn } from '@/lib/utils';
import { useSession } from '@/lib/session';
import { useAssistantContext } from '@/features/assistant/context';
import { AssistantDrawer } from '@/features/assistant/components/assistant-drawer';
import { readWidePreference, RESERVED_CLASS, WIDTH_EVENT } from '@/features/assistant/width';

import { NAV, NAV_GROUPS, PINNED, isActive } from './app-shell-navigation-catalog';
import { SessionExpiryWarning } from './session-expiry-warning';
import { renderSessionGate } from './app-shell-session-gate';
import { useCollapsedGroups } from './use-collapsed-nav-groups';
import { DesktopNavigation } from './app-shell-desktop-navigation';
import { MobileNavigation } from './app-shell-mobile-navigation';
import { AppShellHeader } from './app-shell-header';
import { AppEntryTransition } from './entry-transition';

export function AppShell({ children }: { children: ReactNode }) {
  const { me, status, authMode, can, error, refresh, signOut } =
    useSession();
  const router = useRouter();
  const pathname = usePathname();
  const assistant = useAssistantContext();
  const [navOpen, setNavOpen] = useState(false);
  const [collapsed, toggleGroup] = useCollapsedGroups();
  // Declared before the early returns below. This component returns early
  // while loading, on error and when redirecting, so a hook after them runs a
  // different number of times per render.
  const [assistantWide, setAssistantWide] = useState(false);

  useEffect(() => {
    setAssistantWide(readWidePreference());
    const onWidth = (event: Event) =>
      setAssistantWide((event as CustomEvent<boolean>).detail);
    window.addEventListener(WIDTH_EVENT, onWidth);
    return () => window.removeEventListener(WIDTH_EVENT, onWidth);
  }, []);

  const navPanelRef = useRef<HTMLDivElement | null>(null);
  const navButtonRef = useRef<HTMLButtonElement | null>(null);

  // Closed on every navigation. The panel overlays the content it just sent the
  // reader to, so leaving it open would hide the result of their own tap.
  useEffect(() => setNavOpen(false), [pathname]);

  // The panel is `fixed`, but it sits before the header in the DOM, so opening
  // it and pressing Tab walked *forward* into the header buttons and never into
  // the links. Focus moves in on open and back to the button on close, and
  // Escape dismisses it — the same contract the column menu in DataTable got,
  // for the same reason.
  useEffect(() => {
    if (!navOpen) return;

    navPanelRef.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setNavOpen(false);
        navButtonRef.current?.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [navOpen]);

  // Only the public entrance has a login screen to redirect to.
  const shouldRedirectToLogin =
    status === 'unauthenticated' && authMode !== 'tailnet';

  useEffect(() => {
    if (!shouldRedirectToLogin) return;
    const next = encodeURIComponent(pathname ?? '/');
    router.replace(`/login?next=${next}`);
  }, [shouldRedirectToLogin, pathname, router]);

  // Someone who navigates to a route their scopes do not cover (including the
  // dashboard at its explicit `/dashboard` route) is sent to the one
  // screen everybody can use, rather than left on a page whose data 403s. The
  // nav already hides these links; this covers the URL bar and bookmarks.
  //
  // The redirect is an effect, so it cannot stop the forbidden page mounting
  // first — and mounting is what fires its queries. See `<main>` below, which
  // is the half that keeps them from being sent.
  const onForbiddenRoute =
    status === 'authenticated' &&
    NAV.some(
      (item) =>
        item.requires && !can(item.requires) && isActive(pathname, item.href),
    );

  useEffect(() => {
    if (onForbiddenRoute) router.replace('/chat');
  }, [onForbiddenRoute, router]);

  const gate = renderSessionGate({ status, authMode, error, refresh });
  if (gate !== undefined) {
    // The gate's contract is "undefined means proceed" — honouring it, rather
    // than re-enumerating its states here, is what makes a state added there
    // block here without this file knowing about it. Only the loading state
    // carries the entry curtain; error and lost-tailnet keep their precedence
    // over decoration.
    //
    // **The curtain is the second child, and so is the one below.** React
    // reconciles a fragment's children by position, so keeping the two
    // branches the same shape is the whole reason one curtain instance spans
    // both: it is mounted here while the identity is still loading and
    // *inherited* by the authenticated branch, rather than being remounted
    // there with its timeline back at zero. Inserting anything ahead of it in
    // either fragment silently restarts the hold at the moment it should be
    // ending. `app-shell.entry-transition.test.tsx` asserts node identity
    // across the transition and fails on exactly that edit.
    return status === 'loading' ? (
      <>
        {gate}
        <AppEntryTransition sessionSettled={false} />
      </>
    ) : (
      gate
    );
  }

  if (!me) return null; // Redirecting.

  // Filtered per group, and a group left with nothing is dropped entirely: an
  // empty heading is worse than the flat list this replaced, because it names a
  // capability the reader does not have and then offers nothing behind it.
  // Filtered by the same rule as the groups. Pinned is not exempt from scopes,
  // only from folding — the two are separate properties and conflating them
  // would put an unreachable screen at the top of everyone's sidebar the first
  // time something pinned needs one.
  const visiblePinned = PINNED.filter((item) => !item.requires || can(item.requires));
  const visibleGroups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.requires || can(item.requires)),
  })).filter((group) => group.items.length > 0);

  return (
    <>
      <div
        className={cn(
          // A fixed viewport height with one scrolling region inside it, rather
          // than a document that scrolls behind a nav that does not. The header
          // used to scroll away on exactly the screens long enough to need it —
          // Logs, Models, Users — while the sidebar beside it stayed put, and a
          // page wanting the remaining height had to compete with a document
          // scrollbar it could not see. `100dvh` rather than `100vh` so the
          // mobile browser's collapsing toolbar is not counted twice.
          'flex h-[100dvh] flex-col overflow-hidden',
          // Reserving the panel's width from `lg` up is what turns it from
          // something that covers the rightmost table columns into something that
          // sits beside them. Below `lg` there is no width to spare, so it
          // overlays and the header button stays available to dismiss it.
          //
          // The two values track the panel's own two widths through
          // `features/assistant/width`. They have to agree: reserving too little
          // puts the panel back over the content it was widened to be read
          // beside, which is the whole point of widening it.
          assistant.isOpen &&
            (assistantWide ? RESERVED_CLASS.wide : RESERVED_CLASS.narrow),
        )}
      >
        {/* First in the tab order, visible only while focused. Every screen puts
            the whole sidebar between the address bar and the page, so without
            this a keyboard reader tabs through fifteen links to reach the table
            they navigated to, on every navigation. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-60 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:ring-2 focus:ring-ring"
        >
          Skip to content
        </a>
        <SessionExpiryWarning />
        <div className="flex min-h-0 flex-1">
          {/* Full height with its own scroll, inside a shell that no longer
              scrolls as a whole. On the screens that are actually long — Users,
              Logs, Models — reaching the bottom of a table used to mean losing
              every link and scrolling back up to go anywhere. `overscroll-contain`
              for the same reason as everywhere else: a nav that has reached its
              end must not start moving the region behind it. */}
          <DesktopNavigation authMode={authMode} pinned={visiblePinned} groups={visibleGroups} pathname={pathname} collapsed={collapsed} onToggle={toggleGroup} />

          {/* The same links for anything narrower than the sidebar's breakpoint.
              Below 1024px the aside is display:none, and without this there is no
              way at all to reach another screen short of typing the URL. The
              breakpoint is `lg` rather than `sm` because between the two a 224px
              sidebar and a dense table share a viewport neither of them fits in;
              the tables are what the reader came for. */}
          <MobileNavigation navOpen={navOpen} setNavOpen={setNavOpen} navPanelRef={navPanelRef} navButtonRef={navButtonRef} authMode={authMode} pinned={visiblePinned} groups={visibleGroups} pathname={pathname} collapsed={collapsed} onToggle={toggleGroup} />


          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <AppShellHeader navButtonRef={navButtonRef} navOpen={navOpen} setNavOpen={setNavOpen} me={me} authMode={authMode} assistant={assistant} signOut={signOut} />

            {/* The application's only scrolling region, and a flex column, so a
                page that wants the remaining height asks for it with `flex-1`
                instead of guessing at the chrome above it in viewport units. A
                page that overflows scrolls here, beneath a header and beside a
                nav that both stay where they were.

                `tabIndex={-1}` is what makes the skip link above land somewhere:
                without it the anchor moves the scroll position and leaves focus
                at the top of the document, so the next Tab returns to the nav. */}
            {/* The chrome stays; only the page is withheld. A screen's data
                hooks fire on mount, and a refusal on this API is an
                `authz.denied` audit row — so letting a forbidden page render for
                the one frame before the effect above redirects was not a
                cosmetic flash. Opening the app as a `user` lands on the
                dashboard, which asks for `/admin/dashboard` and `/admin/usage`,
                and every such sign-in wrote two denials naming scopes the reader
                was never shown a link to and had not reached for. That is noise
                in the one record §9.2 keeps for reading deliberate attempts, and
                on 2026-08-14 it was read as exactly that: those rows are what
                suggested the operator of key 68953ceb could not see their own
                usage, which they can — `/usage` serves `usage:read_own` from
                `/usage/me`. Rendering nothing here is not a second access
                control; the server refuses these calls whatever the client
                does. */}
            <main
              id="main-content"
              tabIndex={-1}
              className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto overscroll-contain p-4 outline-none"
            >
              {onForbiddenRoute ? null : children}
            </main>
          </div>
        </div>

        {/* Inside the authenticated branch, and after `children` so the fixed
            panel stacks above the content. Every early return above — loading,
            Tailscale lost, unreachable API — renders no drawer: each is a state
            where the assistant could not answer anyway, since its endpoint needs
            the same identity the failed call did. */}
        <AssistantDrawer />
      </div>
      {/* Second child, matching the loading branch above — see the note there.
          This is not a new curtain; it is the one that mounted while the
          identity was loading, now told the identity has settled. */}
      <AppEntryTransition sessionSettled />
    </>
  );
}

/**
 * The shell, with the assistant's page-context registry around it.
 *
 * The provider wraps rather than nests so that it is mounted for every branch
 * of `AppShell`, including the ones that render no drawer. `useAssistantSurface`
 * throws without a provider, and a page that registers itself on mount would
 * otherwise crash during the moment the session is still loading.
 */
