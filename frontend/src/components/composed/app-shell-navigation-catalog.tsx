import type { ReactNode } from 'react';
import {
  ActivityIcon, BookOpenIcon, BoxIcon, GaugeIcon, KeyIcon, FileTextIcon,
  FlaskConicalIcon, LibraryIcon, MessageSquareIcon, MessagesSquareIcon,
  Building2Icon, RouteIcon, ScrollTextIcon, ShieldAlertIcon, Trash2Icon,
  ServerIcon, TerminalIcon, UsersIcon,
} from 'lucide-react';

import type { KnownScope } from '@/lib/generated/role-scopes';

export type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  /**
   * The scope the screen's own first request needs. Absent means everyone.
   */
  requires?: KnownScope;
  /** `KnownScope`, not `ScopeName`: this value is *authored*, and `ScopeName`
      is `string` because it types what the server sends. A misspelling here
      would hide the entry from every role rather than fail, which is the
      quietest possible way to remove a screen from the navigation. */
};

// Each entry names the scope its screen actually needs, rather than the
// `adminOnly: true` this was until 2026-08-04. That flag was accurate while
// there were two roles and wrong the moment there were six: it would have
// hidden Models and Nodes from an `operator` whose whole job is those screens,
// and shown Users to an `auditor` who can read it but not act on it. The
// scopes below are the ones the corresponding endpoints require, so a hidden
// screen and a 403 mean the same thing.

export type NavGroup = {
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
export const NAV_GROUPS: NavGroup[] = [
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
    id: 'evidence',
    label: 'Evidence',
    // Its own group rather than a fourth entry under Fleet, because it answers
    // a different question about the same subject. Fleet is what is registered,
    // loaded and routed right now; this is what a task set measured models
    // doing on a day that has already passed, and filing a dated record beside
    // three live screens invites it being read as one of them.
    //
    // Gated on `model:read`, the scope the endpoint requires, so the group
    // appears for exactly the roles that can open what is in it: a `user` and a
    // `curator` see no group at all rather than a heading with nothing behind
    // it.
    items: [
      {
        href: '/evaluations',
        label: 'Model evaluation',
        icon: <FlaskConicalIcon className="size-4" />,
        requires: 'model:read',
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
        // the one Content entry a `user` sees: a template is named by its
        // caller, so whoever sends `prompt_template` needs to read the list.
        // The chat panel has no template picker; only API callers select one.
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
        label: 'Audit log',
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
      {
        href: '/refusals',
        label: 'Refusals',
        icon: <ShieldAlertIcon className="size-4" />,
        // The one entry in this group every human role sees. Reading your own
        // refusals is in the base scopes, because being told why you were
        // refused is not an administrative privilege — that condition is what
        // cost two people an evening each on 2026-08-17. The screen itself says
        // when it is showing you only your own.
        requires: 'refusal:read_own',
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
export const PINNED: NavItem[] = [
  {
    href: '/chat',
    label: 'Chat',
    icon: <MessageSquareIcon className="size-4" />,
  },
];

/** Flattened, for the route guard below. One source, so a screen cannot be
 *  reachable by URL and absent from the nav, or the reverse. */
export const NAV: NavItem[] = [...PINNED, ...NAV_GROUPS.flatMap((group) => group.items)];

export function isActive(pathname: string | null, href: string): boolean {
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
