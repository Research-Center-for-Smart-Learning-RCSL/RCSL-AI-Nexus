'use client';

/**
 * Where a screen's settings meet another screen's, filtered by what the reader
 * can actually open.
 *
 * Several settings in this application only mean something in combination: a
 * model's memory figure is budgeted against its node's, a capability does not
 * exist for a key to be scoped to until a routing policy creates it, a
 * transcript is captured only while a debug window opened elsewhere is running.
 * Describing a screen without those connections leaves a reader configuring
 * one half of something.
 *
 * **The filtering is the part that needs care.** The navigation already hides
 * groups a role has no business in, so a cross-reference written as flat prose
 * can send a reader to a screen that does not exist for them — worse than
 * saying nothing, because it reads as a missing permission or a broken link.
 * Each entry therefore carries the scope its target requires, and an entry the
 * reader cannot open is dropped rather than rendered inert. A page whose every
 * entry is dropped renders nothing at all.
 *
 * Entries with no `requires` are visible to every signed-in reader; the two
 * that matter — Chat and API reference — are reachable by all human roles.
 */

import Link from 'next/link';

import type { KnownScope } from '@/lib/generated/role-scopes';
import { useSession } from '@/lib/session';

export type RelatedScreen = {
  href: string;
  label: string;
  /** What the entry adds, not what the target screen is. */
  note: string;
  /** Omitted when every signed-in reader holds what the target needs.
   *
   * `KnownScope` rather than `ScopeName`: a typo in an authored scope name
   * would drop the entry for everybody, silently, which is exactly the failure
   * this component exists to avoid in the other direction. */
  requires?: KnownScope;
};

export function RelatedScreens({
  items,
  title = 'Used together with',
}: {
  items: RelatedScreen[];
  title?: string;
}) {
  const { can } = useSession();
  const visible = items.filter((item) => !item.requires || can(item.requires));

  if (visible.length === 0) return null;

  return (
    <section className="max-w-prose space-y-2 rounded-lg border p-4">
      <h2 className="font-heading text-sm font-semibold">{title}</h2>
      <ul className="space-y-1.5 text-sm text-muted-foreground">
        {visible.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className="underline underline-offset-2 hover:text-foreground"
            >
              {item.label}
            </Link>{' '}
            — {item.note}
          </li>
        ))}
      </ul>
    </section>
  );
}
