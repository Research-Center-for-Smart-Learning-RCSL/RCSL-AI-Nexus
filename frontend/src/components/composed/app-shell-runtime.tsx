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

  // Someone who navigates to a route their scopes do not cover (the dashboard
  // is the index, so this includes just opening the app) is sent to the one
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
  if (gate !== undefined) return gate;

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
    <div
      className={cn(
        'flex flex-1 flex-col',
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
      <SessionExpiryWarning />
      <div className="flex flex-1">
        {/* Sticky, with its own scroll. Without this the nav scrolled away with
            the content, so on the screens that are actually long — Users, Logs,
            Models — reaching the bottom of a table meant losing every link and
            scrolling back up to go anywhere. `h-[calc(100dvh)]` rather than
            `h-screen`: on mobile browsers `100vh` includes the chrome that
            hides as you scroll, so the last group sat under the toolbar.
            `overscroll-contain` for the same reason as everywhere else — a nav
            that has reached its end must not start moving the page behind it. */}
        <DesktopNavigation authMode={authMode} pinned={visiblePinned} groups={visibleGroups} pathname={pathname} collapsed={collapsed} onToggle={toggleGroup} />

        {/* The same links for anything narrower than the sidebar's breakpoint.
            Below 640px the aside is display:none, and without this there was no
            way at all to reach another screen short of typing the URL. */}
        <MobileNavigation navOpen={navOpen} setNavOpen={setNavOpen} navPanelRef={navPanelRef} navButtonRef={navButtonRef} authMode={authMode} pinned={visiblePinned} groups={visibleGroups} pathname={pathname} collapsed={collapsed} onToggle={toggleGroup} />


        <div className="flex min-w-0 flex-1 flex-col">
          <AppShellHeader navButtonRef={navButtonRef} navOpen={navOpen} setNavOpen={setNavOpen} me={me} authMode={authMode} assistant={assistant} signOut={signOut} />

          {/* A flex column, so a page that wants the remaining height can ask
              for it with `flex-1` instead of guessing at the chrome above it in
              viewport units. */}
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
          <main className="flex min-w-0 flex-1 flex-col p-4">
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
