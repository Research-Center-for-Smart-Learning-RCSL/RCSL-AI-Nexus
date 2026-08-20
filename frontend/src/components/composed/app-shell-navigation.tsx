'use client';

import Link from 'next/link';
import { ChevronRightIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

import { isActive, type NavGroup, type NavItem } from './app-shell-navigation-catalog';

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
export function NavGroups({
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
