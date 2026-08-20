import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/composed/empty-state';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { AuditEntry } from '@/features/logs/schema';
import { cn } from '@/lib/utils';
import { wrapTooltip } from '@/lib/wrap-tooltip';

const COLUMNS = ['When', 'Actor', 'Action', 'Target', 'Outcome', 'Detail'];

function OutcomeBadge({ outcome }: { outcome: string }) {
  const ok = outcome === 'success';
  return (
    <Badge variant={ok ? 'secondary' : 'destructive'} className="gap-1.5">
      <span
        className={cn(
          'size-1.5 rounded-full',
          ok ? 'bg-emerald-500' : 'bg-destructive',
        )}
      />
      {outcome}
    </Badge>
  );
}

function detailText(detail: Record<string, string>): string {
  return Object.entries(detail)
    .map(([key, value]) => `${key}: ${value}`)
    .join(', ');
}

export function LogsGrid({
  entries,
  isLoading,
  filtered,
  unknownAction,
  action,
}: {
  entries: AuditEntry[];
  isLoading: boolean;
  filtered: boolean;
  unknownAction: boolean;
  action: string;
}) {
  return (
    <div className="rounded-lg ring-1 ring-foreground/10">
      <Table>
        <TableHeader>
          <TableRow>
            {COLUMNS.map((column) => (
              <TableHead key={column}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            Array.from({ length: 5 }).map((_, index) => (
              <TableRow key={`skeleton-${index}`}>
                {COLUMNS.map((column) => (
                  <TableCell key={column}>
                    <div className="h-4 w-full animate-pulse rounded bg-muted" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : entries.length === 0 ? (
            <TableRow>
              <TableCell colSpan={COLUMNS.length} className="p-0">
                <EmptyState
                  title={filtered ? 'No matching entries' : 'Nothing recorded yet'}
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
                  <div className="text-xs text-muted-foreground">
                    {entry.actor_source}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs">{entry.action}</TableCell>
                <TableCell title={wrapTooltip(entry.target)}>
                  <div className="max-w-[16rem] truncate">{entry.target ?? '-'}</div>
                </TableCell>
                <TableCell>
                  <OutcomeBadge outcome={entry.outcome} />
                </TableCell>
                <TableCell
                  className="text-xs text-muted-foreground"
                  title={wrapTooltip(detailText(entry.detail))}
                >
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
  );
}
