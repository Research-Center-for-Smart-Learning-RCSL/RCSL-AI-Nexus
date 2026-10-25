import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { UnknownOperations } from './unknown-operations';

const state = vi.hoisted(() => ({
  data: {
    operations: [
      {
        node_id: 'local',
        op_id: 'op-1',
        kind: 'inference',
        reason: 'relay_cancelled',
        submitted_at: null as string | null,
      },
    ],
    reset_available: true,
  },
  reset: vi.fn(),
}));

vi.mock('../hooks/use-maintenance-admin', () => ({
  useUnknownOperations: () => ({ data: state.data, isPending: false, isError: false }),
  useResetRuntime: () => ({ mutateAsync: state.reset, isPending: false }),
}));

beforeEach(() => {
  state.data = { ...state.data, reset_available: true };
  state.reset.mockReset();
});

describe('operations with an unknown outcome', () => {
  it('resets a node only with the evidence relied on, and says it cleared', async () => {
    state.reset.mockResolvedValue({
      node_id: 'local',
      op_id: 'op-1',
      cleared: true,
      detail: "cleared; the node's gate is serving",
    });
    render(<UnknownOperations />);

    await userEvent.click(screen.getByRole('button', { name: 'Reset runtime' }));
    expect(screen.getByText(/witness must then see a new one/)).toBeInTheDocument();
    const confirm = screen.getAllByRole('button', { name: 'Reset runtime' }).at(-1)!;
    expect(confirm).toBeDisabled();

    await userEvent.type(screen.getByLabelText('What you relied on'), 'client gave up');
    await userEvent.click(confirm);

    expect(state.reset).toHaveBeenCalledWith({
      node_id: 'local',
      op_id: 'op-1',
      evidence: 'client gave up',
    });
    expect(await screen.findByRole('status')).toHaveTextContent('gate is serving');
  });

  it('shows a refusal as the agent gave it', async () => {
    state.reset.mockResolvedValue({
      node_id: 'local',
      op_id: 'op-1',
      cleared: false,
      detail: 'the runtime witness did not answer the challenge',
    });
    render(<UnknownOperations />);

    await userEvent.click(screen.getByRole('button', { name: 'Reset runtime' }));
    await userEvent.type(screen.getByLabelText('What you relied on'), 'x');
    await userEvent.click(screen.getAllByRole('button', { name: 'Reset runtime' }).at(-1)!);

    expect(await screen.findByRole('status')).toHaveTextContent(
      'op-1 was not cleared: the runtime witness did not answer',
    );
  });

  it('will not reset from an entrance without runtime control, and says why', () => {
    state.data = { ...state.data, reset_available: false };
    render(<UnknownOperations />);

    expect(screen.getByRole('button', { name: 'Reset runtime' })).toBeDisabled();
    expect(screen.getByText(/only available from the tailnet admin/)).toBeInTheDocument();
  });

  it('says when no node is blocked', () => {
    state.data = { operations: [], reset_available: true };
    render(<UnknownOperations />);
    expect(screen.getByText('No node is blocked.')).toBeInTheDocument();
  });
});
