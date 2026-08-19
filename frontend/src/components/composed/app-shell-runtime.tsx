'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { LogOutIcon, MenuIcon, SparklesIcon, UserCogIcon, XIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Logo } from '@/components/composed/logo';
import { ThemeToggle } from '@/components/composed/theme-toggle';
import { useSession } from '@/lib/session';
import { useAssistantContext } from '@/features/assistant/context';
import { AssistantDrawer } from '@/features/assistant/components/assistant-drawer';
import { readWidePreference, RESERVED_CLASS, WIDTH_EVENT } from '@/features/assistant/width';

import { NAV, NAV_GROUPS, PINNED, isActive } from './app-shell-navigation-catalog';
import { NavGroups } from './app-shell-navigation';
import { SessionExpiryWarning } from './session-expiry-warning';
import { renderSessionGate } from './app-shell-session-gate';
import { useCollapsedGroups } from './use-collapsed-nav-groups';

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
        <aside className="sticky top-0 hidden h-[100dvh] w-56 shrink-0 overflow-y-auto overscroll-contain border-r p-3 sm:block">
          <div className="mb-4 px-2">
            {/* Stacked rather than set beside the title. The sidebar is 224px
                wide, which leaves room for the mark at a size it survives;
                inline next to the text it would have to shrink to about 24px,
                where the monogram becomes an unreadable blob. */}
            <Logo height={48} className="mb-2" />
            <p className="font-heading text-sm font-semibold">RCSL AI Nexus</p>
            <Badge variant="outline" className="mt-1">
              {authMode ?? 'unknown'}
            </Badge>
          </div>
          <NavGroups
            pinned={visiblePinned}
            groups={visibleGroups}
            pathname={pathname}
            collapsed={collapsed}
            onToggle={toggleGroup}
          />
        </aside>

        {/* The same links for anything narrower than the sidebar's breakpoint.
            Below 640px the aside is display:none, and without this there was no
            way at all to reach another screen short of typing the URL. */}
        {navOpen ? (
          <div className="fixed inset-0 z-50 sm:hidden">
            <button
              type="button"
              aria-label="Close the menu"
              className="absolute inset-0 bg-black/40"
              onClick={() => setNavOpen(false)}
            />
            <div
              ref={navPanelRef}
              role="dialog"
              aria-modal="true"
              aria-label="Navigation"
              // Focusable only as a target for the effect above, so focus lands
              // inside the panel and Tab continues through the links rather
              // than leaving for the header.
              tabIndex={-1}
              className="absolute inset-y-0 left-0 flex w-64 max-w-[85%] flex-col overflow-y-auto overscroll-contain border-r bg-background p-3 outline-none"
            >
              <div className="mb-4 flex items-start justify-between gap-2 px-2">
                <div>
                  <p className="font-heading text-sm font-semibold">
                    RCSL AI Nexus
                  </p>
                  <Badge variant="outline" className="mt-1">
                    {authMode ?? 'unknown'}
                  </Badge>
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close the menu"
                  onClick={() => {
                    setNavOpen(false);
                    navButtonRef.current?.focus();
                  }}
                >
                  <XIcon />
                </Button>
              </div>
              <NavGroups
                pinned={visiblePinned}
                groups={visibleGroups}
                pathname={pathname}
                collapsed={collapsed}
                onToggle={toggleGroup}
                onNavigate={() => setNavOpen(false)}
              />
            </div>
          </div>
        ) : null}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <Button
                ref={navButtonRef}
                variant="ghost"
                size="icon-sm"
                className="sm:hidden"
                aria-label="Open the menu"
                aria-expanded={navOpen}
                onClick={() => setNavOpen(true)}
              >
                <MenuIcon />
              </Button>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{me.display_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {me.login} - {me.role}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {/* Labelled, not just an icon. The sparkle alone said nothing
                  about what it opens — an operator has to already know the
                  feature exists to try it, which is the opposite of what an
                  assistant is for. The text is what the `aria-label` has always
                  said, so a screen reader user was the only one being told.
                  Hidden below `sm` where the header is tight; the label is what
                  drops, never the control. */}
              <Button
                variant="ghost"
                size="sm"
                aria-label={
                  assistant.isOpen
                    ? 'Close the assistant'
                    : 'Open the assistant'
                }
                aria-expanded={assistant.isOpen}
                onClick={() => assistant.setOpen(!assistant.isOpen)}
                className={cn(
                  'gap-1.5',
                  assistant.isOpen && 'bg-muted text-foreground',
                )}
              >
                <SparklesIcon className="size-4" />
                <span className="hidden sm:inline">Assistant</span>
              </Button>
              <ThemeToggle />
              {/* Account settings only apply where local credentials exist. */}
              {authMode !== 'tailnet' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label="Account"
                  // This renders an anchor, not a button. Without saying so,
                  // Base UI keeps native button semantics for an element that
                  // has none, and warns. A link that navigates is the correct
                  // element here — it is Ctrl-clickable and has an href — so
                  // the prop follows the markup rather than the other way.
                  nativeButton={false}
                  render={<Link href="/account" />}
                >
                  <UserCogIcon />
                  {/* The label is the first thing to go when the header has to
                      share a narrow row with the menu button and the identity
                      block; the icon still carries the meaning, and the
                      aria-label above keeps the name for anyone not seeing it. */}
                  <span className="hidden md:inline">Account</span>
                </Button>
              ) : null}
              {/* No session on the tailnet, so nothing to sign out of. */}
              {authMode !== 'tailnet' ? (
                <Button
                  variant="outline"
                  size="sm"
                  aria-label="Sign out"
                  onClick={() => void signOut()}
                >
                  <LogOutIcon />
                  <span className="hidden md:inline">Sign out</span>
                </Button>
              ) : null}
            </div>
          </header>

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
