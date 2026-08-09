'use client';

/**
 * Nav plus the session gate. What a 401 means depends on the entrance
 * (frontend.md section 3):
 *
 *   tailnet -> "Tailscale connection lost", offer retry. There is no session to
 *              renew and no login screen to send anyone to.
 *   local   -> redirect to the login screen.
 *   dev     -> treated as local, since local development mode issues sessions.
 *
 * Role gating below hides links the user cannot use. That is a usability
 * affordance; every admin action is authorised server-side in the use case
 * layer regardless of what this renders.
 */

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  ActivityIcon,
  BookOpenIcon,
  ChevronRightIcon,
  BoxIcon,
  GaugeIcon,
  KeyIcon,
  FileTextIcon,
  LibraryIcon,
  LogOutIcon,
  MenuIcon,
  MessageSquareIcon,
  MessagesSquareIcon,
  Building2Icon,
  RouteIcon,
  ScrollTextIcon,
  Trash2Icon,
  ServerIcon,
  SparklesIcon,
  TerminalIcon,
  UserCogIcon,
  UsersIcon,
  XIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ErrorState } from '@/components/composed/error-state';
import { Logo } from '@/components/composed/logo';
import { Spinner } from '@/components/composed/spinner';
import { ThemeToggle } from '@/components/composed/theme-toggle';
import { useSession, useSessionExpiry, type ScopeName } from '@/lib/session';
import { TAILSCALE_CONNECTION_LOST } from '@/features/auth/messages';
import {
  AssistantContextProvider,
  useAssistantContext,
} from '@/features/assistant/context';
import { AssistantDrawer } from '@/features/assistant/components/assistant-drawer';
import {
  readWidePreference,
  RESERVED_CLASS,
  WIDTH_EVENT,
} from '@/features/assistant/width';

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  /**
   * The scope the screen's own first request needs. Absent means everyone.
   */
  requires?: ScopeName;
};

// Each entry names the scope its screen actually needs, rather than the
// `adminOnly: true` this was until 2026-08-04. That flag was accurate while
// there were two roles and wrong the moment there were six: it would have
// hidden Models and Nodes from an `operator` whose whole job is those screens,
// and shown Users to an `auditor` who can read it but not act on it. The
// scopes below are the ones the corresponding endpoints require, so a hidden
// screen and a 403 mean the same thing.

type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
};

// Grouped by what the reader came to do, not by which part of the backend
// serves it. Thirteen flat entries is a list nobody scans; five named groups is
// a list somebody skips four fifths of.
//
// The grouping falls along role lines, which is the sign it is the right cut
// rather than a tidy one: a `user` sees Integration, Content and one entry of
// Insight; a `curator` sees those plus authorship of both Content screens; an
// `operator` sees Fleet and Insight and none of Administration. Nobody is
// shown a group they have no business in, because a group with no visible
// items is not rendered at all.
//
// **Content is separate from Fleet, and was not until 2026-08-09.** Prompt
// templates and knowledge documents had been filed under Fleet, where the
// authorization model says plainly they do not belong: `_CURATOR_SCOPES` is
// "what the models are told, and nothing else", and its docstring gives the
// reason as "content authorship, which is why neither is with the role that
// runs the nodes". The navigation had them with exactly that role. The visible
// symptom was that a `user` — who holds `prompt:read` and none of
// `model:read`, `routing:read`, `node:read` — saw a group called Fleet
// containing one entry, Prompts, on a deployment where they have no fleet.
const NAV_GROUPS: NavGroup[] = [
  {
    id: 'integration',
    label: 'Integration',
    // Renamed from 'Work' when Chat was pinned above: what is left is the pair
    // about calling the gateway from your own code, and a label describing what
    // the group used to hold is worse than no label.
    //
    // No `requires` on either: every role holds `api_key:read_own`, and the
    // people who need to know how to call the gateway are the ones holding a
    // key.
    items: [
      {
        href: '/api-keys',
        label: 'API keys',
        icon: <KeyIcon className="size-4" />,
      },
      {
        // 'API' was too bare to be useful once 'Connect an agent' sat beside
        // it: both are about the API and the label said nothing about which
        // answers which question. This one is the wire contract — endpoints,
        // fields, error codes — and it is also the whole of what the gateway
        // offers in exchange for `/openapi.json` being disabled in production
        // (security.md §4.4), which is a reason for it to say what it is.
        href: '/api-docs',
        label: 'API reference',
        icon: <BookOpenIcon className="size-4" />,
      },
      {
        // Beside the reference rather than inside it: one is the contract and
        // the other is the walkthrough, and somebody arriving to connect an
        // agent should not have to read the first to find the second.
        href: '/agent-setup',
        label: 'Connect an agent',
        icon: <TerminalIcon className="size-4" />,
      },
    ],
  },
  {
    id: 'fleet',
    label: 'Fleet',
    items: [
      {
        href: '/models',
        label: 'Models',
        icon: <BoxIcon className="size-4" />,
        requires: 'model:read',
      },
      {
        href: '/routing-policies',
        // Matches the page's own heading. 'Routing' meant the reader landed on
        // a title they had not clicked, which costs nothing to avoid and is
        // the difference when following written instructions.
        label: 'Routing policies',
        icon: <RouteIcon className="size-4" />,
        requires: 'routing:read',
      },
      {
        href: '/nodes',
        label: 'Nodes',
        icon: <ServerIcon className="size-4" />,
        requires: 'node:read',
      },
    ],
  },
  {
    id: 'content',
    label: 'Content',
    // What the models are told, as opposed to what runs them. The split
    // from Fleet mirrors the one the authorization model already makes:
    // `curator` holds both writes here and none of the fleet's reads.
    items: [
      {
        href: '/prompt-templates',
        label: 'Prompt templates',
        icon: <FileTextIcon className="size-4" />,
        // `prompt:read` is a base scope, unlike `knowledge:read`, so this is
        // the one Knowledge-group entry a `user` sees: choosing a template is
        // part of asking a question, and the chat picker reads the same list.
        requires: 'prompt:read',
      },
      {
        href: '/knowledge',
        label: 'Knowledge',
        icon: <LibraryIcon className="size-4" />,
        // knowledge:read is an admin scope. Retrieval for the chat happens
        // server-side under the caller's tenant, so a `user` never needs the
        // screen to have their questions answered from these documents.
        requires: 'knowledge:read',
      },
    ],
  },
  {
    id: 'insight',
    label: 'Insight',
    items: [
      {
        href: '/',
        label: 'Dashboard',
        icon: <GaugeIcon className="size-4" />,
        requires: 'usage:read_all',
      },
      {
        href: '/usage',
        label: 'Usage',
        icon: <ActivityIcon className="size-4" />,
        // `read_own`, not `read_all`: since 2026-08-04 the screen serves both,
        // and the narrower scope is held by every human role, so this link is
        // visible to everyone and shows each reader what they are entitled to.
        // The Dashboard above keeps `usage:read_all`, because platform totals
        // have no own-usage equivalent to fall back to.
        requires: 'usage:read_own',
      },
      {
        href: '/logs',
        label: 'Logs',
        icon: <ScrollTextIcon className="size-4" />,
        requires: 'logs:read',
      },
      {
        href: '/prompt-logs',
        label: 'Transcripts',
        icon: <MessagesSquareIcon className="size-4" />,
        // Its own entry rather than a tab on Logs, because the scope is not the
        // same one. `logs:read` reaches `tenant_admin`, `operator` and
        // `auditor`; `prompt_log:read` is admin-only (ADMIN_ONLY_SCOPES), since
        // that view shows what happened and this one shows what was typed. A
        // tab inside a page gated on a different scope is the drift this table
        // exists to prevent — the link would appear for three roles the server
        // refuses.
        requires: 'prompt_log:read',
      },
    ],
  },
  {
    id: 'administration',
    label: 'Administration',
    items: [
      {
        href: '/users',
        label: 'Users',
        icon: <UsersIcon className="size-4" />,
        requires: 'user:read',
      },
      {
        href: '/tenants',
        label: 'Tenants',
        icon: <Building2Icon className="size-4" />,
        requires: 'tenant:read',
      },
      {
        href: '/retention',
        label: 'Retention',
        icon: <Trash2Icon className="size-4" />,
        // Admin-only: `retention:write` is in ADMIN_ONLY_SCOPES because a
        // tenant administrator who could purge could erase the record of what
        // they did inside the tenant they administer.
        requires: 'retention:write',
      },
    ],
  },
];

// Pinned above every group, and outside all of them.
//
// Chat is the screen with the widest audience and the shortest reason to be
// open — every role holds `chat:use`, and it is where an out-of-scope URL is
// redirected to, so it is the one destination that must never be a click behind
// a fold. Inside a collapsible group it could be hidden by a preference set
// weeks earlier, on the one screen for which "I could not find it" is the whole
// failure.
const PINNED: NavItem[] = [
  {
    href: '/chat',
    label: 'Chat',
    icon: <MessageSquareIcon className="size-4" />,
  },
];

/** Flattened, for the route guard below. One source, so a screen cannot be
 *  reachable by URL and absent from the nav, or the reverse. */
const NAV: NavItem[] = [...PINNED, ...NAV_GROUPS.flatMap((group) => group.items)];

function isActive(pathname: string | null, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname?.startsWith(href) ?? false;
}

/**
 * The link list, shared by the sidebar and the narrow-screen panel.
 *
 * One definition rather than two: a nav that existed twice is a nav where one
 * copy quietly falls behind, and the role filtering below is the part that must
 * not diverge.
 */
const COLLAPSED_KEY = 'nexus.nav.collapsed';

/**
 * Which groups the reader has folded away, remembered across navigations.
 *
 * Read after mount rather than during render: this component is server-rendered
 * and `localStorage` does not exist there, so reading it inline would either
 * throw or produce markup that disagrees with the client's first paint. The
 * first render is therefore "everything open", which is also the right default
 * — a nav that starts collapsed hides the thing the reader came for, and the
 * clutter this fixes is worth one click to fold, not a hunt to unfold.
 *
 * A bad value in storage is discarded rather than repaired. It is a UI
 * preference; the cost of getting it wrong is one lost fold, and code that
 * carefully rehabilitates malformed JSON is code nobody can justify.
 */
function useCollapsedGroups(): [Set<string>, (id: string) => void] {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const stored: unknown = JSON.parse(
        window.localStorage.getItem(COLLAPSED_KEY) ?? '[]',
      );
      if (Array.isArray(stored)) {
        setCollapsed(new Set(stored.filter((id): id is string => typeof id === 'string')));
      }
    } catch {
      // Unparseable or unavailable storage: keep the default.
    }
  }, []);

  const toggle = useCallback((id: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      try {
        window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      } catch {
        // Private browsing, or a full quota. The fold still works for this
        // session; only its memory is lost, which is not worth an error.
      }
      return next;
    });
  }, []);

  return [collapsed, toggle];
}

function NavLinks({
  items,
  pathname,
  onNavigate,
}: {
  items: NavItem[];
  pathname: string | null;
  onNavigate?: () => void;
}) {
  return (
    <nav className="space-y-0.5">
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm',
              active
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:bg-muted/50',
            )}
          >
            {item.icon}
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * The grouped nav, shared by the sidebar and the narrow-screen panel.
 *
 * One definition rather than two: a nav that existed twice is a nav where one
 * copy quietly falls behind, and the scope filtering is the part that must not
 * diverge.
 *
 * **A group holding the current page cannot be folded away.** Otherwise the
 * reader collapses Fleet while standing on Models, the highlighted item
 * vanishes, and the sidebar stops saying where they are — the one thing it is
 * for. The fold is remembered, so it takes effect the moment they navigate
 * elsewhere.
 */
function NavGroups({
  pinned,
  groups,
  pathname,
  collapsed,
  onToggle,
  onNavigate,
}: {
  pinned: NavItem[];
  groups: NavGroup[];
  pathname: string | null;
  collapsed: Set<string>;
  onToggle: (id: string) => void;
  onNavigate?: () => void;
}) {
  return (
    <div className="space-y-3">
      {/* Above every heading and inside none of them, so no fold can reach it. */}
      {pinned.length ? (
        <NavLinks items={pinned} pathname={pathname} onNavigate={onNavigate} />
      ) : null}
      {groups.map((group) => {
        const holdsCurrentPage = group.items.some((item) => isActive(pathname, item.href));
        const open = holdsCurrentPage || !collapsed.has(group.id);
        return (
          <div key={group.id}>
            <button
              type="button"
              onClick={() => onToggle(group.id)}
              aria-expanded={open}
              aria-controls={`nav-group-${group.id}`}
              className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-xs font-medium tracking-wide text-muted-foreground uppercase hover:bg-muted/50"
            >
              <ChevronRightIcon
                className={cn('size-3 transition-transform', open && 'rotate-90')}
              />
              {group.label}
            </button>
            <div id={`nav-group-${group.id}`} hidden={!open}>
              <NavLinks items={group.items} pathname={pathname} onNavigate={onNavigate} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * The end-of-session warning.
 *
 * `session_expires_at` is the **absolute** expiry, fixed at login and never
 * moved: the store extends the idle window on every read but deliberately does
 * not touch this deadline. So there is no "stay signed in" to offer — a button
 * promising one would do nothing and then the session would end anyway.
 *
 * What can be offered is the choice of moment. Signing back in now, before the
 * deadline, is the difference between losing a half-written form deliberately
 * and losing it mid-sentence. The notice can be dismissed, because for most of
 * the warning window there is nothing to do about it, and it comes back for the
 * last minute regardless of that dismissal.
 */
function SessionExpiryWarning() {
  const { msRemaining, shouldWarn } = useSessionExpiry();
  const { signOut } = useSession();
  const [dismissed, setDismissed] = useState(false);

  if (!shouldWarn || msRemaining === null) return null;
  const urgent = msRemaining <= 60_000;
  if (dismissed && !urgent) return null;

  const minutes = Math.max(1, Math.round(msRemaining / 60_000));
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-amber-500/10 px-4 py-2 text-sm"
    >
      <span>
        Your session ends in about {minutes} minute{minutes === 1 ? '' : 's'}.
        This deadline is fixed at sign-in and cannot be extended.
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Button size="xs" variant="outline" onClick={() => void signOut()}>
          Sign in again now
        </Button>
        {!urgent ? (
          <Button size="xs" variant="ghost" onClick={() => setDismissed(true)}>
            Dismiss
          </Button>
        ) : null}
      </div>
    </div>
  );
}

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
  const onForbiddenRoute =
    status === 'authenticated' &&
    NAV.some(
      (item) =>
        item.requires && !can(item.requires) && isActive(pathname, item.href),
    );

  useEffect(() => {
    if (onForbiddenRoute) router.replace('/chat');
  }, [onForbiddenRoute, router]);

  if (status === 'loading') {
    return (
      <div className="flex flex-1 flex-col items-center justify-center">
        <Spinner label="Checking your access" />
        <p className="text-sm text-muted-foreground">Checking your access...</p>
      </div>
    );
  }

  if (status === 'unauthenticated' && authMode === 'tailnet') {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState
          title="Tailscale connection lost"
          error={TAILSCALE_CONNECTION_LOST}
          onRetry={() => void refresh()}
          className="max-w-md"
        />
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <ErrorState
          title="Could not reach the admin API"
          error={error}
          onRetry={() => void refresh()}
          className="max-w-md"
        />
      </div>
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
          <main className="flex min-w-0 flex-1 flex-col p-4">{children}</main>
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
export function AppShellWithAssistant({ children }: { children: ReactNode }) {
  return (
    <AssistantContextProvider>
      <AppShell>{children}</AppShell>
    </AssistantContextProvider>
  );
}
