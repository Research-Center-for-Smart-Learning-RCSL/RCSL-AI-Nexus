import type { MaintenanceAdmin, MaintenanceNodeStep, MaintenanceOperation } from './api';

/**
 * Reading an entry's and a restore's progress (#61 P4, P5) for the console.
 *
 * The console keeps three things apart that an administrator must not
 * confuse: access closed (immediate), the runtimes released (an entry, node
 * by node), and the models restored (a restore, ending in the reopen). The
 * reasons a button is unavailable are derived here from that state, because
 * the API's refusal says only that the state conflicts, not why.
 */

export const ENTRY_PHASES = [
  ['pending', 'Waiting'],
  ['interrupted', 'Work interrupted'],
  ['snapshotted', 'Snapshot saved'],
  ['reset', 'Runtime restarted'],
  ['verified', 'Verified empty'],
] as const;

export const RESTORE_PHASES = [
  ['pending', 'Loading models'],
  ['loaded', 'All loaded'],
  ['probed', 'Each model answered'],
  ['verified', 'Verified'],
] as const;

export function phasesFor(kind: string): readonly (readonly [string, string])[] {
  return kind === 'restore' ? RESTORE_PHASES : ENTRY_PHASES;
}

export function phaseLabel(kind: string, phase: string): string {
  return phasesFor(kind).find(([value]) => value === phase)?.[1] ?? phase;
}

/** The operation for the hold now closed, or null: an older epoch's is history. */
export function currentOperation(state: MaintenanceAdmin): MaintenanceOperation | null {
  const operation = state.operation ?? null;
  if (!operation || !state.closed || operation.epoch !== state.epoch) return null;
  return operation;
}

export type Milestone = 'not_started' | 'running' | 'done' | 'failed';

export function milestones(state: MaintenanceAdmin): {
  released: Milestone;
  restored: Milestone;
} {
  const operation = currentOperation(state);
  if (!operation) return { released: 'not_started', restored: 'not_started' };
  const outcome: Milestone =
    operation.status === 'succeeded'
      ? 'done'
      : operation.status === 'running'
        ? 'running'
        : 'failed';
  if (operation.kind === 'restore') return { released: 'done', restored: outcome };
  return { released: outcome, restored: 'not_started' };
}

function nodes(steps: MaintenanceNodeStep[], test: (step: MaintenanceNodeStep) => boolean) {
  return steps.filter(test).map((step) => step.node_id).join(', ');
}

/** Why "Restore and reopen" cannot be pressed now, or undefined if it can. */
export function restoreBlocker(state: MaintenanceAdmin): string | undefined {
  const operation = currentOperation(state);
  if (!operation) return 'No entry has been recorded for this hold.';
  if (operation.kind === 'restore') {
    return operation.status === 'running'
      ? 'A restore is running.'
      : 'The restore failed. Retry it, or reopen without restoring.';
  }
  if (operation.status === 'running') return 'The runtimes are still being released.';
  if (operation.status !== 'succeeded') {
    return 'The entry did not release every runtime. Retry it first.';
  }
  const missing = nodes(operation.nodes, (step) => step.snapshot === null);
  if (missing) {
    return `No snapshot for ${missing}: its runtime could not be observed before the reset. Reopen without restoring and load its models by hand.`;
  }
  const unresolved = nodes(operation.nodes, (step) => step.accounting !== 'resolved');
  if (unresolved) {
    return `${unresolved} still has interrupted operations whose outcome is unknown. Resolve them with the reset CLI first.`;
  }
  return undefined;
}

/** Whether "Retry" applies: the current hold's entry or restore failed. */
export function canRetry(state: MaintenanceAdmin): boolean {
  return currentOperation(state)?.status === 'failed';
}

export function describeSnapshot(step: MaintenanceNodeStep): string {
  if (step.snapshot === null) return step.snapshot_error ?? 'Not taken yet';
  if (step.snapshot.length === 0) return 'Nothing was resident';
  return step.snapshot
    .map((model) =>
      model.context_length ? `${model.name} (${model.context_length} ctx)` : `${model.name}`,
    )
    .join(', ');
}
