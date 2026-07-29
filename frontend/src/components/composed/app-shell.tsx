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

import { useEffect, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  ActivityIcon,
  BookOpenIcon,
  BoxIcon,
  GaugeIcon,
  KeyIcon,
  LibraryIcon,
  LogOutIcon,
  MessageSquareIcon,
  Building2Icon,
  RouteIcon,
  ScrollTextIcon,
  ServerIcon,
  UserCogIcon,
  UsersIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ErrorState } from '@/components/composed/error-state';
import { Logo } from '@/components/composed/logo';
import { Spinner } from '@/components/composed/spinner';
import { useSession, useSessionExpiry } from '@/lib/session';
import { TAILSCALE_CONNECTION_LOST } from '@/features/auth/messages';
import { AssistantContextProvider } from '@/features/assistant/context';
import { AssistantDrawer } from '@/features/assistant/components/assistant-drawer';

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  adminOnly?: boolean;
};

// adminOnly mirrors the scopes in adapters/authz. The dashboard needs
// usage:read_all and the model registry needs model:read, neither of which a
// `user` holds (security.md section 5.2), so both would 403 for one. A `user`
// sees Chat and their own API keys.
const NAV: NavItem[] = [
  {
    href: '/',
    label: 'Dashboard',
    icon: <GaugeIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/models',
    label: 'Models',
    icon: <BoxIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/routing-policies',
    label: 'Routing',
    icon: <RouteIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/nodes',
    label: 'Nodes',
    icon: <ServerIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/knowledge',
    label: 'Knowledge',
    icon: <LibraryIcon className="size-4" />,
    // knowledge:read is an admin scope. Retrieval for the chat happens
    // server-side under the caller's tenant, so a `user` never needs the
    // screen to have their questions answered from these documents.
    adminOnly: true,
  },
  {
    href: '/usage',
    label: 'Usage',
    icon: <ActivityIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/logs',
    label: 'Logs',
    icon: <ScrollTextIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/api-keys',
    label: 'API keys',
    icon: <KeyIcon className="size-4" />,
  },
  {
    // Not adminOnly, for the same reason API keys is not: the people who need
    // to know how to call the gateway are the ones holding a key.
    href: '/api-docs',
    label: 'API',
    icon: <BookOpenIcon className="size-4" />,
  },
  {
    href: '/users',
    label: 'Users',
    icon: <UsersIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/tenants',
    label: 'Tenants',
    icon: <Building2Icon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/chat',
    label: 'Chat',
    icon: <MessageSquareIcon className="size-4" />,
  },
];

function isActive(pathname: string | null, href: string): boolean {
  if (href === '/') return pathname === '/';
  return pathname?.startsWith(href) ?? false;
}

function SessionExpiryWarning() {
  const { msRemaining, shouldWarn } = useSessionExpiry();
  if (!shouldWarn || msRemaining === null) return null;
  const minutes = Math.max(1, Math.round(msRemaining / 60_000));
  return (
    <div className="border-b bg-amber-500/10 px-4 py-2 text-sm">
      Your session ends in about {minutes} minute{minutes === 1 ? '' : 's'}.
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, status, authMode, isAdmin, error, refresh, signOut } =
    useSession();
  const router = useRouter();
  const pathname = usePathname();

  // Only the public entrance has a login screen to redirect to.
  const shouldRedirectToLogin =
    status === 'unauthenticated' && authMode !== 'tailnet';

  useEffect(() => {
    if (!shouldRedirectToLogin) return;
    const next = encodeURIComponent(pathname ?? '/');
    router.replace(`/login?next=${next}`);
  }, [shouldRedirectToLogin, pathname, router]);

  // A signed-in `user` who navigates to an admin-only route directly (the
  // dashboard is the index, so this includes just opening the app) is sent to
  // the one screen they can use, rather than left on a page whose data 403s.
  // The nav already hides these links; this covers the URL bar and bookmarks.
  const onForbiddenRoute =
    status === 'authenticated' &&
    !isAdmin &&
    NAV.some((item) => item.adminOnly && isActive(pathname, item.href));

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

  const visible = NAV.filter((item) => !item.adminOnly || isAdmin);

  return (
    <div className="flex flex-1 flex-col">
      <SessionExpiryWarning />
      <div className="flex flex-1">
        <aside className="hidden w-56 shrink-0 border-r p-3 sm:block">
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
          <nav className="space-y-0.5">
            {visible.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
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
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center justify-between gap-3 border-b px-4 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{me.display_name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {me.login} - {me.role}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {/* Account settings only apply where local credentials exist. */}
              {authMode !== 'tailnet' ? (
                <Button variant="ghost" size="sm" render={<Link href="/account" />}>
                  <UserCogIcon />
                  Account
                </Button>
              ) : null}
              {/* No session on the tailnet, so nothing to sign out of. */}
              {authMode !== 'tailnet' ? (
                <Button variant="outline" size="sm" onClick={() => void signOut()}>
                  <LogOutIcon />
                  Sign out
                </Button>
              ) : null}
            </div>
          </header>

          <main className="min-w-0 flex-1 p-4">{children}</main>
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
