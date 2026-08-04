'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState } from '@/components/composed/empty-state';
import { ErrorState } from '@/components/composed/error-state';
import { useLogs } from '@/features/logs/hooks/use-logs';
import { AUDIT_ACTIONS, type AuditEntry } from '@/features/logs/schema';

const PAGE_SIZE = 50;
// The three values the backend writes, and the filter is an exact match on the
// column. Until 2026-08-02 the third option here was `failure`, which nothing
// has ever written: pressing it filtered a real query down to nothing and
// looked like a quiet audit log rather than a broken button. `denied` became
// worth its own option the same day, when authorization refusals started being
// recorded — it is now the busiest failure outcome and a different question
// from `failed`, which means an action was attempted and did not complete.
const OUTCOMES = [
  { value: '', label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'denied', label: 'Denied' },
];

function OutcomeBadge({ outcome }: { outcome: string }) {
  const ok = outcome === 'success';
  return (
    <Badge variant={ok ? 'secondary' : 'destructive'} className="gap-1.5">
      <span className={cn('size-1.5 rounded-full', ok ? 'bg-emerald-500' : 'bg-destructive')} />
      {outcome}
    </Badge>
  );
}

function detailText(detail: Record<string, string>): string {
  const parts = Object.entries(detail).map(([k, v]) => `${k}: ${v}`);
  return parts.join(', ');
}

const COLUMNS = ['When', 'Actor', 'Action', 'Target', 'Outcome', 'Detail'];

export function LogsTable() {
  // What is typed, and what is asked for. They were the same value, so every
  // keystroke queried the server: typing one action name sent a dozen requests,
  // eleven of which described a prefix that matches nothing by definition.
  const [actionText, setActionText] = useState('');
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const [offset, setOffset] = useState(0);

  // What the last debounce actually applied. A ref rather than a comparison
  // inside a state updater, which React may run twice and which would make the
  // `setOffset` below a side effect in a place that must not have one.
  const appliedAction = useRef('');

  useEffect(() => {
    const timer = setTimeout(() => {
      const next = actionText.trim();
      // Guarded, because this fires on mount and after any edit that resolves
      // back to the same filter — typing a character and deleting it, say.
      // Resetting unconditionally meant a Next click within the debounce window
      // silently returned to page 1 while the request for the later offset was
      // already in flight.
      if (appliedAction.current === next) return;
      appliedAction.current = next;
      setAction(next);
      // A filter change must return to the first page, or the offset could
      // point past the end of a smaller filtered set.
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [actionText]);

  const filters = { action: action || undefined, outcome: outcome || undefined, limit: PAGE_SIZE, offset };
  const { data, isLoading, isFetching, error, refetch } = useLogs(filters);

  function changeOutcome(next: string) {
    setOutcome(next);
    setOffset(0);
  }

  // An exact match that found nothing is a different situation from a filter
  // nobody set, and only one of them has advice worth giving.
  const filtered = Boolean(action || outcome);
  const unknownAction = Boolean(
    action && !AUDIT_ACTIONS.includes(action as (typeof AUDIT_ACTIONS)[number]),
  );

  if (error) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  const entries: AuditEntry[] = data?.entries ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-xs flex-1">
          <Input
            value={actionText}
            onChange={(e) => setActionText(e.target.value)}
            placeholder="Exact action, e.g. user.invited"
            list="audit-actions"
            aria-label="Filter by action, matched exactly"
            aria-describedby="audit-action-hint"
          />
          {/* The whole set the backend writes. Without it the box looked like a
              search and behaved like an equality check, so a partial name
              returned an empty table that read as a quiet audit log. */}
          <datalist id="audit-actions">
            {AUDIT_ACTIONS.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </div>
        <div className="flex gap-1">
          {OUTCOMES.map((o) => (
            <Button
              key={o.value || 'all'}
              size="sm"
              variant={o.value === outcome ? 'default' : 'outline'}
              onClick={() => changeOutcome(o.value)}
              aria-pressed={o.value === outcome}
            >
              {o.label}
            </Button>
          ))}
        </div>
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {total === 0 ? 'No entries' : `${from}–${to} of ${total}`}
        </span>
      </div>

      <p id="audit-action-hint" className="text-xs text-muted-foreground">
        The action filter matches the whole name, not part of one. Start typing
        to pick from the {AUDIT_ACTIONS.length} the platform records.
        {unknownAction ? (
          <span className="text-destructive">
            {' '}
            <strong>{action}</strong> is not one of them, so this can only ever
            return nothing.
          </span>
        ) : null}
      </p>

      <div className="rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableHead key={c}>{c}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {COLUMNS.map((c) => (
                    <TableCell key={c}>
                      <div className="h-4 w-full animate-pulse rounded bg-muted" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="p-0">
                  <EmptyState
                    title={
                      filtered ? 'No matching entries' : 'Nothing recorded yet'
                    }
                    description={
                      unknownAction
                        ? `No action is named "${action}". Clear the box and pick from the list to see what is recorded.`
                        : filtered
                          ? 'Nothing matched these filters. The action has to be a whole name; clear it, or try a different outcome.'
                          : 'Every administrative action is recorded here as it happens.'
                    }
                    className="border-0"
                  />
                </TableCell>
              </TableRow>
            ) : (
              entries.map((entry) => (
                <TableRow key={entry.id}>
                  <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">
                    {new Date(entry.at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{entry.actor_display}</div>
                    <div className="text-xs text-muted-foreground">{entry.actor_source}</div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{entry.action}</TableCell>
                  {/* The width has to constrain a block *inside* the cell, not
                      the cell. `max-width` on a `td` is advisory under the
                      automatic table layout every table here uses: the column
                      is sized from its content first, so the cap was ignored,
                      `truncate` had nothing to truncate against, and a long
                      value widened the whole table until it ran past the right
                      edge — visible as overflow rather than as an ellipsis,
                      and only reachable through the wrapper's horizontal
                      scrollbar. An inner div is an ordinary block box and
                      honours the cap. */}
                  <TableCell title={entry.target ?? undefined}>
                    <div className="max-w-[16rem] truncate">
                      {entry.target ?? '-'}
                    </div>
                  </TableCell>
                  <TableCell>
                    <OutcomeBadge outcome={entry.outcome} />
                  </TableCell>
                  <TableCell
                    className="text-xs text-muted-foreground"
                    title={detailText(entry.detail)}
                  >
                    {/* The widest column in practice and the one that showed
                        the defect: `detail` is every key and value of an audit
                        entry joined into one line, so it is routinely longer
                        than the viewport. The `title` carries the full text for
                        a hover; the ellipsis is what tells anyone there is more
                        to hover over. */}
                    <div className="max-w-[20rem] truncate">
                      {detailText(entry.detail) || '-'}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
        <span>{isFetching ? 'Loading...' : `${from}–${to} of ${total}`}</span>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
        >
          <ChevronLeftIcon />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Next page"
          disabled={to >= total}
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
        >
          <ChevronRightIcon />
        </Button>
      </div>
    </div>
  );
}
