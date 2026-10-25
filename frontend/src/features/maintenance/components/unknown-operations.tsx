'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { DisabledReason } from '@/components/composed/disabled-reason';
import { ErrorState, describeError } from '@/components/composed/error-state';
import { Spinner } from '@/components/composed/spinner';

import type { RuntimeReset, UnknownOperation } from '../api';
import { useResetRuntime, useUnknownOperations } from '../hooks/use-maintenance-admin';

const EVIDENCE_MAX = 500;
const ONLY_TAILNET = 'Runtime control is only available from the tailnet admin entrance.';

/**
 * Operations a node sent and cannot account for, and the reset that clears
 * them (#49 §5, #61). Each one blocks its node: nothing more is sent there
 * until a supervised restart, with the host witness's evidence on both sides,
 * proves the runtime that may have received it gone. Nothing here marks an
 * operation done without that evidence; a refusal is shown as the agent gave it.
 */
export function UnknownOperations() {
  const query = useUnknownOperations();
  const reset = useResetRuntime();
  const [target, setTarget] = useState<UnknownOperation | null>(null);
  const [evidence, setEvidence] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [outcome, setOutcome] = useState<RuntimeReset | null>(null);

  if (query.isPending) return <Spinner label="Loading blocked operations" />;
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title="Could not read the blocked operations"
        error={query.error}
        onRetry={() => void query.refetch()}
      />
    );
  }
  const { operations, reset_available: available } = query.data;

  async function confirm() {
    if (!target) return;
    setError(null);
    try {
      const result = await reset.mutateAsync({
        node_id: target.node_id,
        op_id: target.op_id,
        evidence: evidence.trim(),
      });
      setOutcome(result);
      setTarget(null);
      setEvidence('');
    } catch (caught) {
      setError(caught);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Operations with an unknown outcome</CardTitle>
        <CardDescription>
          Each was sent to a runtime that never said how it ended, and its node accepts nothing
          more until a reset proves that runtime gone. A reset restarts the node&apos;s runtime,
          which unloads every model there; the resident models are loaded back on their own.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {outcome ? (
          <p
            role="status"
            className={outcome.cleared ? 'text-sm' : 'text-sm text-destructive'}
          >
            {outcome.cleared
              ? `${outcome.op_id}: ${outcome.detail}.`
              : `${outcome.op_id} was not cleared: ${outcome.detail}`}
          </p>
        ) : null}
        {operations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No node is blocked.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Node</TableHead>
                <TableHead>Operation</TableHead>
                <TableHead>Why unknown</TableHead>
                <TableHead>Since</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {operations.map((operation) => (
                <TableRow key={`${operation.node_id}/${operation.op_id}`}>
                  <TableCell className="font-mono text-xs">{operation.node_id}</TableCell>
                  <TableCell className="text-xs">
                    <span className="font-mono">{operation.op_id}</span> ({operation.kind})
                  </TableCell>
                  <TableCell className="text-xs">{operation.reason ?? '—'}</TableCell>
                  <TableCell className="text-xs">
                    {operation.submitted_at
                      ? new Date(operation.submitted_at).toLocaleString()
                      : '—'}
                  </TableCell>
                  <TableCell>
                    <DisabledReason reason={available ? undefined : ONLY_TAILNET}>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!available}
                        onClick={() => {
                          setOutcome(null);
                          setError(null);
                          setTarget(operation);
                        }}
                      >
                        Reset runtime
                      </Button>
                    </DisabledReason>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTarget(null);
            setError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset the runtime on {target?.node_id}?</DialogTitle>
            <DialogDescription>
              The node stops admitting work, the host witness records the running runtime, the
              supervisor restarts it, and the witness must then see a new one. Only then is{' '}
              {target?.op_id} recorded as failed, with your evidence. Every model on the node is
              unloaded and then loaded back. This can take a minute or two.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1">
            <Label htmlFor="reset-evidence">What you relied on</Label>
            <Input
              id="reset-evidence"
              value={evidence}
              maxLength={EVIDENCE_MAX}
              placeholder="e.g. the client gave up; no one is waiting on this output"
              onChange={(event) => setEvidence(event.target.value)}
            />
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {describeError(error)}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" disabled={reset.isPending} />}>
              Cancel
            </DialogClose>
            <Button
              variant="destructive"
              disabled={reset.isPending || !evidence.trim()}
              onClick={() => void confirm()}
            >
              {reset.isPending ? 'Resetting…' : 'Reset runtime'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
