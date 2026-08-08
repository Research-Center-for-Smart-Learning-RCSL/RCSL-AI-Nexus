'use client';

import { useState } from 'react';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

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
import { usePromptLogs } from '@/features/prompt-logs/hooks/use-prompt-logs';
import { TranscriptDialog } from '@/features/prompt-logs/components/transcript-dialog';
import type { PromptLogSummary } from '@/features/prompt-logs/schema';

const PAGE_SIZE = 50;
const COLUMNS = ['When', 'Capability', 'Model', 'Request', 'Size', 'Result', ''];

/** Characters, not tokens, and said so — the row stores what it can measure. */
function chars(n: number): string {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
}

export function PromptLogsTable() {
  const [requestId, setRequestId] = useState('');
  const [capability, setCapability] = useState('');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<string | null>(null);

  const filters = {
    capability: capability || undefined,
    request_id: requestId.trim() || undefined,
    limit: PAGE_SIZE,
    offset,
  };
  const { data, isLoading, isFetching, error, refetch } = usePromptLogs(filters);

  if (error) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  const entries: PromptLogSummary[] = data?.entries ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const filtered = Boolean(capability || requestId.trim());

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-xs flex-1">
          <Input
            value={requestId}
            onChange={(e) => {
              setRequestId(e.target.value);
              setOffset(0);
            }}
            placeholder="Request id, e.g. req_9f2a…"
            aria-label="Find the conversation behind a request id"
          />
        </div>
        <div className="max-w-[10rem] flex-1">
          <Input
            value={capability}
            onChange={(e) => {
              setCapability(e.target.value);
              setOffset(0);
            }}
            placeholder="Capability"
            aria-label="Filter by capability"
          />
        </div>
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {total === 0 ? 'No transcripts' : `${from}–${to} of ${total}`}
        </span>
      </div>

      <div className="rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c, i) => (
                <TableHead key={c || `actions-${i}`}>{c}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {COLUMNS.map((c, j) => (
                    <TableCell key={c || `cell-${j}`}>
                      <div className="h-4 w-full animate-pulse rounded bg-muted" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="p-0">
                  {/* An empty table here is the *correct* state on an ordinary
                      deployment, not a failure, so the copy says so plainly.
                      An empty state that reads as "something went wrong" would
                      send an operator looking for a bug in a control that is
                      working exactly as designed. */}
                  <EmptyState
                    title={filtered ? 'Nothing matched' : 'No transcripts captured'}
                    description={
                      filtered
                        ? 'No captured conversation matches this. The request id has to be the whole value from the caller’s error, not part of one.'
                        : 'This is the normal state. The platform records metadata only, and full prompt and completion text appears here only while a debug window is open on an API key or a user account — opened from the API keys or Users screen, and closing by itself within a day.'
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
                  <TableCell>{entry.capability}</TableCell>
                  <TableCell className="font-mono text-xs">{entry.model_alias}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    <div className="max-w-[12rem] truncate">
                      {entry.request_id ?? '—'}
                    </div>
                  </TableCell>
                  {/* Sizes rather than a preview. A preview would put message
                      content on a screen nobody has asked to read yet, and
                      would make the audit row — written only when a transcript
                      is opened — describe less than what was actually shown. */}
                  <TableCell className="whitespace-nowrap tabular-nums text-xs text-muted-foreground">
                    {chars(entry.message_chars)} in / {chars(entry.completion_chars)} out
                    {entry.reasoning_chars > 0 ? ` / ${chars(entry.reasoning_chars)} think` : ''}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {entry.completed ? (
                      <span className="text-xs text-muted-foreground">
                        {entry.finish_reason ?? 'stop'}
                      </span>
                    ) : (
                      <Badge variant="destructive">
                        {entry.finish_reason ?? 'cut off'}
                      </Badge>
                    )}
                    {entry.tool_calls > 0 ? (
                      <span className="ml-1 text-xs text-muted-foreground tabular-nums">
                        {entry.tool_calls} call{entry.tool_calls === 1 ? '' : 's'}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" variant="outline" onClick={() => setOpen(entry.id)}>
                      Read
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || isFetching}
          aria-label="Previous page"
        >
          <ChevronLeftIcon className="size-4" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOffset(offset + PAGE_SIZE)}
          disabled={to >= total || isFetching}
          aria-label="Next page"
        >
          <ChevronRightIcon className="size-4" />
        </Button>
      </div>

      <TranscriptDialog id={open} onOpenChange={(next) => !next && setOpen(null)} />
    </div>
  );
}
