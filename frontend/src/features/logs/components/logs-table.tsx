'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ErrorState } from '@/components/composed/error-state';
import { useLogs } from '@/features/logs/hooks/use-logs';
import {
  AUDIT_ACTIONS,
  type AuditEntry,
  type KnownAuditAction,
} from '@/features/logs/schema';

import { LogFilters } from './log-filters';
import { LogsGrid } from './logs-grid';

const PAGE_SIZE = 50;

export function LogsTable() {
  const [actionText, setActionText] = useState('');
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const [offset, setOffset] = useState(0);
  const appliedAction = useRef('');

  useEffect(() => {
    const timer = setTimeout(() => {
      const next = actionText.trim();
      if (appliedAction.current === next) return;
      appliedAction.current = next;
      setAction(next);
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [actionText]);

  const filters = {
    action: action || undefined,
    outcome: outcome || undefined,
    limit: PAGE_SIZE,
    offset,
  };
  const { data, isLoading, isFetching, error, refetch } = useLogs(filters);
  const filtered = Boolean(action || outcome);
  const unknownAction = Boolean(
    action && !AUDIT_ACTIONS.includes(action as KnownAuditAction),
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
      <LogFilters
        actionText={actionText}
        setActionText={setActionText}
        action={action}
        outcome={outcome}
        changeOutcome={(next) => {
          setOutcome(next);
          setOffset(0);
        }}
        unknownAction={unknownAction}
        total={total}
        from={from}
        to={to}
      />
      <LogsGrid
        entries={entries}
        isLoading={isLoading}
        filtered={filtered}
        unknownAction={unknownAction}
        action={action}
      />
      <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
        <span>{isFetching ? 'Loading...' : `${from}–${to} of ${total}`}</span>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Previous page"
          disabled={offset === 0}
          onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
        >
          <ChevronLeftIcon />
        </Button>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Next page"
          disabled={to >= total}
          onClick={() => setOffset((current) => current + PAGE_SIZE)}
        >
          <ChevronRightIcon />
        </Button>
      </div>
    </div>
  );
}
