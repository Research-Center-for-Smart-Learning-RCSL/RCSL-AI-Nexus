'use client';

import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ErrorState } from '@/components/composed/error-state';
import { useUsageRecords } from '@/features/usage/hooks/use-usage';
import type { UsageRecord } from '@/features/usage/schema';

const PAGE_SIZE = 50;
const COLUMNS = ['When', 'Capability', 'Model', 'Tokens', 'Latency', 'Result'];

const TIER_TITLE: Record<number, string> = {
  0: 'Tool definitions were deduplicated and trimmed',
  1: 'Old tool results were replaced with markers',
  2: 'The oldest turns were replaced with a summary',
};

function tokens(n: number): string {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
}

/**
 * What a request had removed from it, spelled out rather than left as a tier.
 *
 * The counts come from the row rather than being recomputed: they are the
 * figures the guardrail actually judged, on the same basis it judged them, and
 * a number derived here would be a second opinion about a decision already
 * taken.
 */
function CompactionCell({ record }: { record: UsageRecord }) {
  if (record.compaction_tier === null) return null;
  const before = record.tokens_before_compaction;
  const after = record.tokens_after_compaction;
  const saved = before !== null && after !== null ? before - after : null;
  return (
    <Badge
      variant="outline"
      className="ml-2"
      title={TIER_TITLE[record.compaction_tier] ?? 'The prompt was reduced before it was sent'}
    >
      compacted T{record.compaction_tier}
      {saved !== null ? ` −${tokens(saved)}` : ''}
    </Badge>
  );
}

/**
 * The individual requests behind the charts above.
 *
 * Filtering to compacted requests is the first thing this table was wanted for:
 * `usage_records` gained three columns describing what a prompt was reduced to
 * on the argument that a response header the client may not read needs durable
 * evidence behind it, and until this screen existed that evidence was as
 * unreadable as the header.
 */
export function UsageRecordsTable() {
  const [offset, setOffset] = useState(0);
  const [compactedOnly, setCompactedOnly] = useState(false);
  const filters = {
    compacted: compactedOnly ? true : undefined,
    limit: PAGE_SIZE,
    offset,
  };
  const { data, isLoading, error, refetch } = useUsageRecords(filters);

  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;

  return (
    <section className="space-y-3" aria-labelledby="usage-records-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="usage-records-heading" className="text-sm font-medium">
            Individual requests
          </h3>
          <p className="text-sm text-muted-foreground">
            {data?.scoped_to_self
              ? 'Your own requests. Reading another account’s requires usage:read_all.'
              : 'Every served request in this tenant, newest first.'}
          </p>
        </div>
        <Button
          size="sm"
          variant={compactedOnly ? 'default' : 'outline'}
          aria-pressed={compactedOnly}
          onClick={() => {
            setCompactedOnly((v) => !v);
            // Page one, because the filter changes what the pages contain.
            // Keeping the offset would show an empty table on a filter that
            // matched fewer rows than the page already scrolled past.
            setOffset(0);
          }}
        >
          Compacted only
        </Button>
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableHead key={c}>{c}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            ) : entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="text-muted-foreground">
                  {compactedOnly
                    ? 'No request in this range had its prompt reduced.'
                    : 'No requests recorded in this range.'}
                </TableCell>
              </TableRow>
            ) : (
              entries.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">
                    {new Date(r.at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    {r.capability}
                    {/* The caller asked for something else and the key's
                        default substituted this one. Null when the two agree,
                        which is every ordinary request. */}
                    {r.requested_capability ? (
                      <span className="ml-1 text-xs text-muted-foreground">
                        asked {r.requested_capability}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{r.model_alias}</TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums text-xs text-muted-foreground">
                    {tokens(r.prompt_tokens)} in / {tokens(r.tokens)} out
                    <CompactionCell record={r} />
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums text-xs text-muted-foreground">
                    {(r.latency_ms / 1000).toFixed(1)}s
                  </TableCell>
                  <TableCell>
                    {r.completed ? (
                      <span className="text-xs text-muted-foreground">done</span>
                    ) : (
                      <Badge variant="destructive">cut off</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end gap-2">
        <span className="text-xs text-muted-foreground tabular-nums">
          {total === 0 ? '0' : `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
        </span>
        <Button
          size="sm"
          variant="outline"
          disabled={offset === 0}
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
        >
          Previous
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
        >
          Next
        </Button>
      </div>
    </section>
  );
}
