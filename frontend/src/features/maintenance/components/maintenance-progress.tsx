'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import type { MaintenanceNodeStep, MaintenanceOperation } from '../api';
import { describeSnapshot, phaseLabel, phasesFor } from '../progress';

const STATUS: Record<string, { label: string; variant: 'secondary' | 'outline' | 'destructive' }> =
  {
    running: { label: 'In progress', variant: 'secondary' },
    done: { label: 'Done', variant: 'outline' },
    failed: { label: 'Failed', variant: 'destructive' },
    succeeded: { label: 'Succeeded', variant: 'outline' },
    abandoned: { label: 'Abandoned', variant: 'outline' },
  };

function StatusBadge({ status }: { status: string }) {
  const descriptor = STATUS[status] ?? { label: status, variant: 'outline' as const };
  return <Badge variant={descriptor.variant}>{descriptor.label}</Badge>;
}

function PhaseTrail({ kind, step }: { kind: string; step: MaintenanceNodeStep }) {
  const phases = phasesFor(kind);
  const reached = phases.findIndex(([value]) => value === step.phase);
  return (
    <ol className="flex flex-wrap gap-x-2 gap-y-1 text-xs" aria-label="Phases">
      {phases.map(([value, label], index) => {
        const done = index < reached || (index === reached && step.status === 'done');
        const current = index === reached && step.status !== 'done';
        return (
          <li
            key={value}
            aria-current={current ? 'step' : undefined}
            className={
              done
                ? 'text-foreground'
                : current
                  ? step.status === 'failed'
                    ? 'font-medium text-destructive'
                    : 'font-medium text-foreground'
                  : 'text-muted-foreground'
            }
          >
            {done ? '✓ ' : current ? '› ' : ''}
            {label}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Each node's progress through the hold's entry or restore (#61 P4, P5):
 * which phase it reached, what it saved, and why it stopped if it did.
 * Administrators only; the public status says none of this.
 */
export function MaintenanceProgress({ operation }: { operation: MaintenanceOperation }) {
  const restoring = operation.kind === 'restore';
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {restoring ? 'Restoring the models' : 'Releasing the runtimes'}
          <StatusBadge status={operation.status} />
        </CardTitle>
        <CardDescription>
          {restoring
            ? 'Each node loads back what it held before the entry, largest first, checks each model answers, and the platform reopens only once every node verifies.'
            : 'Each node interrupts its running work, saves what its runtime held, restarts it with nothing loaded, and verifies it empty. Access was closed when the entry was made; this is the memory being released.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {operation.error ? (
          <p role="alert" className="text-sm text-destructive">
            {operation.error}
          </p>
        ) : null}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Node</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>{restoring ? 'Restoring' : 'Snapshot'}</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {operation.nodes.map((step) => (
              <TableRow key={step.node_id}>
                <TableCell className="font-mono text-xs">{step.node_id}</TableCell>
                <TableCell>
                  <PhaseTrail kind={operation.kind} step={step} />
                  <p className="sr-only">{phaseLabel(operation.kind, step.phase)}</p>
                </TableCell>
                <TableCell className="text-xs">
                  <p>{describeSnapshot(step)}</p>
                  {!restoring && step.interrupted.length > 0 ? (
                    <p className="text-muted-foreground">
                      Interrupted {step.interrupted.length} running request
                      {step.interrupted.length === 1 ? '' : 's'}
                    </p>
                  ) : null}
                  {!restoring && step.accounting === 'unresolved' ? (
                    <p className="text-destructive">Interrupted requests not yet resolved</p>
                  ) : null}
                </TableCell>
                <TableCell className="space-y-1 text-xs">
                  <StatusBadge status={step.status} />
                  {step.attempts > 0 && step.status === 'running' ? (
                    <p className="text-muted-foreground">Attempt {step.attempts + 1}</p>
                  ) : null}
                  {step.error ? <p className="text-destructive">{step.error}</p> : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {operation.nodes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No node has a runtime to release.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
