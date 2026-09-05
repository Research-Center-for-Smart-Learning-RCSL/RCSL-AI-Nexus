import type { ReactNode } from 'react';
import { ChevronRightIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

export type PageHeaderProps = {
  title: string;
  /**
   * One sentence stating what the screen is. Everything a reader needs before
   * they can use the screen belongs here; everything they need only once
   * belongs in `children`.
   */
  lead: ReactNode;
  /** Expanded on request, under `detailsLabel`. */
  children?: ReactNode;
  detailsLabel?: string;
  className?: string;
};

/**
 * The heading block every screen opens with.
 *
 * The reference material each screen carries is read once and then never
 * again, while the table or form beneath it is read daily. Rendering all of it
 * ahead of the controls pushed the working part of several screens below the
 * fold, so the standing text is one sentence and the rest is behind a
 * disclosure that remembers nothing — a reader who wants it opens it, and a
 * reader who has read it is not shown it a second time.
 *
 * A native `<details>` rather than a scripted panel: it is keyboard-operable,
 * announced as a disclosure, expandable before hydration, and searchable by the
 * browser's own find-in-page in Chromium.
 */
export function PageHeader({
  title,
  lead,
  children,
  detailsLabel = 'About this screen',
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('space-y-3', className)}>
      <div className="space-y-1.5">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">
          {title}
        </h1>
        <p className="max-w-prose text-sm text-muted-foreground">{lead}</p>
      </div>
      {children ? (
        <details className="group max-w-prose rounded-lg border">
          <summary
            className={cn(
              'flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium',
              'hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
              // Safari draws its own triangle through `list-item`, which the
              // rule above does not reach.
              '[&::-webkit-details-marker]:hidden',
            )}
          >
            <ChevronRightIcon className="nexus-disclosure-chevron size-3.5 shrink-0 group-open:rotate-90" />
            {detailsLabel}
          </summary>
          <div className="space-y-3 border-t px-3 py-3 text-sm text-muted-foreground">
            {children}
          </div>
        </details>
      ) : null}
    </div>
  );
}
