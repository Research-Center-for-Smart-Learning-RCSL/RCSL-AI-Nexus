import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { MaintenanceNodeStep, MaintenanceOperation } from '../api';
import { MaintenanceConsole } from './maintenance-console';

function node(changes: Partial<MaintenanceNodeStep> = {}): MaintenanceNodeStep {
  return {
    node_id: 'local',
    phase: 'verified',
    status: 'done',
    attempts: 0,
    error: null,
    snapshot: [{ name: 'gemma4:31b-it-q8_0', context_length: 262144 }],
    snapshot_at: '2026-10-25T08:00:00Z',
    snapshot_error: null,
    interrupted: ['op-1'],
    accounting: 'resolved',
    ...changes,
  };
}

function operation(changes: Partial<MaintenanceOperation> = {}): MaintenanceOperation {
  return {
    id: 'op',
    kind: 'enter',
    epoch: 1,
    status: 'succeeded',
    requested_by: 'admin',
    error: null,
    created_at: null,
    finished_at: null,
    nodes: [node()],
    ...changes,
  };
}

const state = vi.hoisted(() => ({
  data: {
    closed: false,
    phase: 'normal',
    epoch: 0,
    revision: 0,
    message: null as string | null,
    expected_return_at: null as string | null,
    changed_by: null as string | null,
    changed_at: null as string | null,
    enabled: true,
    operation: null as MaintenanceOperation | null,
  },
  enter: vi.fn(async () => undefined),
  reopen: vi.fn(async () => undefined),
  restore: vi.fn(async () => undefined),
  retry: vi.fn(async () => undefined),
}));

vi.mock('../hooks/use-maintenance-admin', () => ({
  useMaintenanceAdmin: () => ({ data: state.data, isPending: false, isError: false }),
  useEnterMaintenance: () => ({ mutateAsync: state.enter }),
  useReopenAfterMaintenance: () => ({ mutateAsync: state.reopen }),
  useRestoreAfterMaintenance: () => ({ mutateAsync: state.restore }),
  useRetryMaintenance: () => ({ mutateAsync: state.retry, isPending: false }),
  useSetMaintenanceMessage: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

beforeEach(() => {
  state.data = { ...state.data, closed: false, enabled: true, message: null, epoch: 0 };
  state.data.operation = null;
  state.enter.mockClear();
  state.reopen.mockClear();
  state.restore.mockClear();
  state.retry.mockClear();
});

function closedWith(op: MaintenanceOperation | null) {
  state.data = { ...state.data, closed: true, epoch: 1, operation: op };
}

describe('the maintenance console', () => {
  it('says what closing does before it does it, then sends the message', async () => {
    render(<MaintenanceConsole />);
    await userEvent.type(screen.getByLabelText('Message'), 'Runtime upgrade');
    await userEvent.click(screen.getByRole('button', { name: 'Close for maintenance' }));

    expect(screen.getByText(/signed out and cannot sign back in/)).toBeInTheDocument();
    expect(state.enter).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'Close now' }));
    expect(state.enter).toHaveBeenCalledWith({
      message: 'Runtime upgrade',
      expected_return_at: null,
    });
  });

  it('will not close a deployment that has not enabled it, and says why', () => {
    state.data = { ...state.data, enabled: false };
    render(<MaintenanceConsole />);

    expect(screen.getByRole('button', { name: 'Close for maintenance' })).toBeDisabled();
    expect(screen.getByText(/MAINTENANCE_ENABLED/)).toBeInTheDocument();
  });

  it('offers reopening while closed, whatever the flag says', async () => {
    state.data = { ...state.data, closed: true, enabled: false };
    render(<MaintenanceConsole />);

    await userEvent.click(screen.getByRole('button', { name: 'Reopen without restoring' }));
    expect(screen.getByText(/whatever the runtimes hold/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    expect(state.reopen).toHaveBeenCalled();
  });

  it('shows access, release and restore apart, and each node\'s progress', () => {
    closedWith(
      operation({
        status: 'running',
        nodes: [node({ phase: 'snapshotted', status: 'running', accounting: null })],
      }),
    );
    render(<MaintenanceConsole />);

    expect(screen.getByText('Access closed').nextSibling).toHaveTextContent('Done');
    expect(screen.getByText('Runtimes released').nextSibling).toHaveTextContent('In progress');
    expect(screen.getByText('Models restored').nextSibling).toHaveTextContent('Not started');
    expect(screen.getByText('Releasing the runtimes')).toBeInTheDocument();
    expect(screen.getByText(/gemma4:31b-it-q8_0 \(262144 ctx\)/)).toBeInTheDocument();
    expect(screen.getByText('Interrupted 1 running request')).toBeInTheDocument();
    expect(screen.getByText(/› Snapshot saved/)).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('button', { name: 'Restore and reopen' })).toBeDisabled();
    expect(screen.getByText('The runtimes are still being released.')).toBeInTheDocument();
  });

  it('restores once the entry released every runtime', async () => {
    closedWith(operation());
    render(<MaintenanceConsole />);

    await userEvent.click(screen.getByRole('button', { name: 'Restore and reopen' }));
    expect(screen.getByText(/stays closed until every node verifies/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Restore' }));
    expect(state.restore).toHaveBeenCalled();
  });

  it.each([
    [node({ snapshot: null, snapshot_error: 'unobserved' }), /No snapshot for local/],
    [node({ accounting: 'unresolved' }), /outcome is unknown/],
  ])('says why a restore would not put everything back', (step, reason) => {
    closedWith(operation({ nodes: [step] }));
    render(<MaintenanceConsole />);

    expect(screen.getByRole('button', { name: 'Restore and reopen' })).toBeDisabled();
    expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
  });

  it('offers retry for a failed step, with its error', async () => {
    closedWith(
      operation({
        kind: 'restore',
        status: 'failed',
        error: 'local at pending: revision_mismatch',
        nodes: [node({ phase: 'pending', status: 'failed', error: 'revision_mismatch' })],
      }),
    );
    render(<MaintenanceConsole />);

    expect(screen.getByText('Restoring the models')).toBeInTheDocument();
    expect(screen.getByText('Models restored').nextSibling).toHaveTextContent(
      'Stopped with an error',
    );
    expect(screen.getByText('revision_mismatch')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(state.retry).toHaveBeenCalled();
  });

  it('ignores an operation from an earlier hold', () => {
    closedWith(operation({ epoch: 0 }));
    render(<MaintenanceConsole />);

    expect(screen.queryByText('Releasing the runtimes')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Restore and reopen' })).toBeDisabled();
  });
});
