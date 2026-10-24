import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MaintenanceConsole } from './maintenance-console';

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
  },
  enter: vi.fn(async () => undefined),
  reopen: vi.fn(async () => undefined),
}));

vi.mock('../hooks/use-maintenance-admin', () => ({
  useMaintenanceAdmin: () => ({ data: state.data, isPending: false, isError: false }),
  useEnterMaintenance: () => ({ mutateAsync: state.enter }),
  useReopenAfterMaintenance: () => ({ mutateAsync: state.reopen }),
  useSetMaintenanceMessage: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

beforeEach(() => {
  state.data = { ...state.data, closed: false, enabled: true, message: null };
  state.enter.mockClear();
  state.reopen.mockClear();
});

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

    await userEvent.click(screen.getByRole('button', { name: 'Reopen the platform' }));
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    expect(state.reopen).toHaveBeenCalled();
  });
});
