'use client';

import { useState } from 'react';
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
import type { AuditEntry } from '@/features/logs/schema';

const PAGE_SIZE = 50;
const OUTCOMES = [
  { value: '', label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'failure', label: 'Failure' },
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
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const [offset, setOffset] = useState(0);

  const filters = { action: action || undefined, outcome: outcome || undefined, limit: PAGE_SIZE, offset };
  const { data, isLoading, isFetching, error, refetch } = useLogs(filters);

  // A filter change must return to the first page, or the offset could point
  // past the end of a smaller filtered set.
  function changeAction(next: string) {
    setAction(next);
    setOffset(0);
  }
  function changeOutcome(next: string) {
    setOutcome(next);
    setOffset(0);
  }

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
        <Input
          value={action}
          onChange={(e) => changeAction(e.target.value)}
          placeholder="Filter by action, e.g. user.invited"
          className="max-w-xs"
          aria-label="Filter by action"
        />
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
                    title="No matching entries"
                    description="Every administrative action is recorded here. Adjust the filters to widen the search."
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
                  <TableCell className="max-w-[16rem] truncate" title={entry.target ?? undefined}>
                    {entry.target ?? '-'}
                  </TableCell>
                  <TableCell>
                    <OutcomeBadge outcome={entry.outcome} />
                  </TableCell>
                  <TableCell
                    className="max-w-[20rem] truncate text-xs text-muted-foreground"
                    title={detailText(entry.detail)}
                  >
                    {detailText(entry.detail) || '-'}
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
