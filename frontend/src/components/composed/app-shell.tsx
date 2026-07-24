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
  BoxIcon,
  GaugeIcon,
  KeyIcon,
  LogOutIcon,
  MessageSquareIcon,
  UserCogIcon,
  UsersIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ErrorState } from '@/components/composed/error-state';
import { useSession, useSessionExpiry } from '@/lib/session';
import { TAILSCALE_CONNECTION_LOST } from '@/features/auth/messages';

type NavItem = {
  href: string;
  label: string;
  icon: ReactNode;
  adminOnly?: boolean;
};

const NAV: NavItem[] = [
  { href: '/', label: 'Dashboard', icon: <GaugeIcon className="size-4" /> },
  { href: '/models', label: 'Models', icon: <BoxIcon className="size-4" /> },
  {
    href: '/api-keys',
    label: 'API keys',
    icon: <KeyIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/users',
    label: 'Users',
    icon: <UsersIcon className="size-4" />,
    adminOnly: true,
  },
  {
    href: '/chat',
    label: 'Chat',
    icon: <MessageSquareIcon className="size-4" />,
  },
];

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

  if (status === 'loading') {
    return (
      <div className="flex flex-1 items-center justify-center">
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
            <p className="font-heading text-sm font-semibold">RCSL AI Nexus</p>
            <Badge variant="outline" className="mt-1">
              {authMode ?? 'unknown'}
            </Badge>
          </div>
          <nav className="space-y-0.5">
            {visible.map((item) => {
              const active =
                item.href === '/'
                  ? pathname === '/'
                  : pathname?.startsWith(item.href);
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
    </div>
  );
}
