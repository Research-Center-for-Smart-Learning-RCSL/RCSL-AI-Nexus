import Link from 'next/link';

import { Logo } from '@/components/composed/logo';
import { ThemeToggle } from '@/components/composed/theme-toggle';

/**
 * Layout for screens that must render before anyone is authenticated.
 *
 * Deliberately outside `(dashboard)`: that layout fetches `/admin/me` and
 * assumes a session exists, which is exactly what is missing here. Nesting
 * these routes under it would produce a redirect loop on the login screen.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="nexus-dot-grid relative flex min-h-screen items-center justify-center bg-muted/40 p-6">
      {/* Reachable before anyone is signed in: the theme is a client-side
          preference with no session behind it, and this is the first screen
          most people see. */}
      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <Link
          href="/"
          aria-label="RCSL AI Nexus, home"
          className="mb-8 flex flex-col items-center rounded-lg text-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-4"
        >
          {/* The sign-in screens are the one place with room to show the mark
              at a size where its interlocking actually reads. The whole brand
              is the route out, rather than making only the mark clickable. */}
          <Logo height={72} />
          <h1 className="mt-4 text-xl font-semibold tracking-tight">RCSL AI Nexus</h1>
          <p className="text-sm text-muted-foreground">Management</p>
        </Link>
        {children}
      </div>
    </div>
  );
}
