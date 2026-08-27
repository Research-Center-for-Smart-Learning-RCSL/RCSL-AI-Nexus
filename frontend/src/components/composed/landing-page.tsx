'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { ArrowRightIcon, LockKeyholeIcon, NetworkIcon, ServerIcon } from 'lucide-react';

import { ErrorState } from '@/components/composed/error-state';
import { Logo } from '@/components/composed/logo';
import { ThemeToggle } from '@/components/composed/theme-toggle';
import { Button, buttonVariants } from '@/components/ui/button';
import { TAILSCALE_CONNECTION_LOST } from '@/features/auth/messages';
import { useSession } from '@/lib/session';
import { LandingThreeBackdrop } from '@/components/composed/entry-transition';

function CtaLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={buttonVariants({ size: 'lg', className: 'group min-w-44' })}>
      {children}
      <ArrowRightIcon className="transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

function PrimaryAction() {
  const { me, status, authMode, error, refresh } = useSession();

  if (status === 'loading') {
    return (
      <div className="space-y-2" aria-live="polite">
        <p className="text-sm text-muted-foreground">Checking your access…</p>
        <Button size="lg" disabled className="min-w-44">
          Loading
        </Button>
        {/* This branch is what the prerendered HTML contains: the session is
            always unresolved at build time, so the static ‘/’ carries a
            disabled control and no way in. With scripting the state resolves
            in a few hundred milliseconds and this markup is never seen; with
            scripting blocked or failed it is the whole page, and the one
            public door to the platform would otherwise be a button that never
            enables. Sign in is the right guess for a reader we know nothing
            about — an existing session lands them past the form anyway. */}
        <noscript>
          <Link
            href="/login"
            className={buttonVariants({ size: 'lg', className: 'min-w-44' })}
          >
            Sign in
          </Link>
        </noscript>
      </div>
    );
  }

  if (status === 'authenticated' && me) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Signed in as <span className="font-medium text-foreground">{me.display_name}</span>
        </p>
        <CtaLink href="/dashboard">Go to the console</CtaLink>
      </div>
    );
  }

  // The failure states keep the diagnosis the shell would have shown at the
  // old '/' instead of falling through to Sign in: /login dead-ends both — a
  // tailnet identity never reaches that route, and an unreachable API rejects
  // the very login it asks for.
  if (status === 'error' || authMode === 'tailnet') {
    return (
      <ErrorState
        title={
          status === 'error' ? 'Could not reach the admin API' : 'Tailscale connection lost'
        }
        error={status === 'error' ? error : TAILSCALE_CONNECTION_LOST}
        onRetry={() => void refresh()}
        className="max-w-md px-5 py-6"
      />
    );
  }

  return <CtaLink href="/login">Sign in</CtaLink>;
}

export function LandingPage() {
  return (
    <main className="relative isolate flex min-h-[100dvh] overflow-hidden bg-background">
      <div className="nexus-dot-grid absolute inset-0 opacity-50" aria-hidden="true" />
      <div
        className="absolute inset-0 bg-[radial-gradient(circle_at_72%_28%,color-mix(in_oklab,var(--primary)_18%,transparent),transparent_34%),radial-gradient(circle_at_18%_78%,color-mix(in_oklab,var(--chart-3)_13%,transparent),transparent_38%)]"
        aria-hidden="true"
      />
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle />
      </div>

      <div className="relative mx-auto flex w-full max-w-7xl flex-col justify-between px-6 py-8 sm:px-10 lg:px-16 lg:py-12">
        <header className="flex items-center gap-4">
          <Logo height={48} />
          <div>
            <p className="font-heading text-sm font-semibold tracking-tight">RCSL AI Nexus</p>
            <p className="text-xs text-muted-foreground">Research Center for Smart Learning</p>
          </div>
        </header>

        <section className="grid items-center gap-12 py-8 sm:py-10 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.72fr)]">
          <div className="max-w-3xl">
            <p className="mb-5 font-mono text-xs font-medium tracking-[0.24em] text-primary uppercase">
              Your models. One intelligent gateway.
            </p>
            {/* The scale stops at 7xl: the hero column is ~642px wide once the
                container hits its max, and this line at 8xl needs 643px — the
                one-pixel miss that put "AI" alone on the first line. 8xl also
                made the hero taller than a 1080p viewport, and this is a
                one-screen page. */}
            <h1 className="font-heading text-5xl leading-[0.98] font-semibold tracking-[-0.055em] text-balance sm:text-6xl xl:text-7xl">
              AI infrastructure,
              <span className="block text-primary">under your control.</span>
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-7 text-muted-foreground xl:text-xl xl:leading-8">
              A self-hosted LLM gateway and management platform for secure access,
              observable operations, and models that can grow with your work.
            </p>
            <div className="mt-6">
              <PrimaryAction />
            </div>
          </div>

          <div className="relative hidden min-h-96 lg:block" aria-hidden="true">
            <div className="absolute inset-0 rounded-[2.5rem] border border-primary/15 bg-card/55 shadow-2xl shadow-primary/10 backdrop-blur-sm" />
            <div className="absolute inset-8 rounded-[2rem] border border-primary/20" />
            <div className="absolute inset-16 rounded-[1.5rem] border border-primary/30" />
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="grid size-48 grid-cols-2 gap-3 rotate-6 rounded-3xl border border-primary/30 bg-background/80 p-5 shadow-xl backdrop-blur">
                {[ServerIcon, NetworkIcon, LockKeyholeIcon, ArrowRightIcon].map((Icon, index) => (
                  <div key={index} className="flex items-center justify-center rounded-2xl border bg-card text-primary shadow-sm">
                    <Icon className="size-8" strokeWidth={1.5} />
                  </div>
                ))}
              </div>
            </div>
            {/* Above the icon card, not behind it: the scene carries a depth
                mask matching the card, so each orbit passes in front of the
                icons on one side and disappears behind them on the other,
                instead of being flattened under the card everywhere. */}
            <LandingThreeBackdrop />
          </div>
        </section>

        <footer className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
          <p>Built for infrastructure you can inspect, operate, and own.</p>
          <p className="font-mono">RCSL · NTNU</p>
        </footer>
      </div>
    </main>
  );
}
