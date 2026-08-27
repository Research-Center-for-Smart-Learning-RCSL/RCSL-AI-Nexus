'use client';

import Link from 'next/link';
import { ArrowRightIcon, LockKeyholeIcon, NetworkIcon, ServerIcon } from 'lucide-react';

import { Logo } from '@/components/composed/logo';
import { ThemeToggle } from '@/components/composed/theme-toggle';
import { Button, buttonVariants } from '@/components/ui/button';
import { useSession } from '@/lib/session';

function PrimaryAction() {
  const { me, status } = useSession();

  if (status === 'loading') {
    return (
      <div className="space-y-2" aria-live="polite">
        <p className="text-sm text-muted-foreground">Checking your access…</p>
        <Button size="lg" disabled className="min-w-44">
          Loading
        </Button>
      </div>
    );
  }

  if (status === 'authenticated' && me) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          Signed in as <span className="font-medium text-foreground">{me.display_name}</span>
        </p>
        <Link
          href="/dashboard"
          className={buttonVariants({ size: 'lg', className: 'group min-w-44' })}
        >
          Go to the console
          <ArrowRightIcon className="transition-transform group-hover:translate-x-0.5" />
        </Link>
      </div>
    );
  }

  return (
    <Link
      href="/login"
      className={buttonVariants({ size: 'lg', className: 'group min-w-44' })}
    >
      Sign in
      <ArrowRightIcon className="transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
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

        <section className="grid items-center gap-12 py-16 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.72fr)]">
          <div className="max-w-3xl">
            <p className="mb-5 font-mono text-xs font-medium tracking-[0.24em] text-primary uppercase">
              Your models. One intelligent gateway.
            </p>
            <h1 className="font-heading text-5xl leading-[0.98] font-semibold tracking-[-0.055em] text-balance sm:text-6xl lg:text-8xl">
              AI infrastructure,
              <span className="block text-primary">under your control.</span>
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-muted-foreground sm:text-xl">
              A self-hosted LLM gateway and management platform for secure access,
              observable operations, and models that can grow with your work.
            </p>
            <div className="mt-9">
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
