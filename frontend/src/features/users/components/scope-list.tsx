'use client';

import { CheckIcon } from 'lucide-react';

import { SCOPE_LABELS } from '@/features/users/schema';

/**
 * A set of permissions, in words.
 *
 * Shared by the role picker (which shows what a role *would* grant, from the
 * catalogue) and the account screen (which shows what the signed-in account
 * *does* hold, from `GET /admin/me`). One component because the rendering rule
 * that matters is the same in both places and is easy to get wrong once:
 *
 * a scope with no plain-language name is shown by its identifier rather than
 * skipped. Omitting it would understate what is granted, and understating is
 * the one direction a permissions display must never be wrong in — a reader
 * who sees `logs:read` learns something, a reader shown nothing concludes
 * there is nothing there.
 */
export function ScopeList({ scopes }: { scopes: string[] }) {
  return (
    <ul className="grid gap-1 sm:grid-cols-2">
      {scopes.map((scope) => (
        <li
          key={scope}
          className="flex items-start gap-1.5 text-xs text-muted-foreground"
        >
          <CheckIcon className="mt-0.5 size-3 shrink-0 text-primary" aria-hidden />
          <span>{SCOPE_LABELS[scope] ?? scope}</span>
        </li>
      ))}
    </ul>
  );
}
