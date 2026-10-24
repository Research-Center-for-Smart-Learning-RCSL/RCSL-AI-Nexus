import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import AuthLayout from '@/app/(auth)/layout';

const maintenance = vi.hoisted(() => ({
  closed: false,
  status: null as null | {
    closed: boolean;
    phase: string;
    message: string | null;
    expected_return_at: string | null;
    revision: number;
  },
}));

vi.mock('@/lib/maintenance', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/maintenance')>()),
  useMaintenance: () => ({ ...maintenance, unavailable: false, refresh: vi.fn() }),
}));

describe('the authentication layout', () => {
  it('makes the complete brand a route back to the public home page', () => {
    render(<AuthLayout>Authentication screen</AuthLayout>);

    const home = screen.getByRole('link', { name: 'RCSL AI Nexus, home' });
    expect(home).toHaveAttribute('href', '/');
    expect(home).toHaveTextContent('RCSL AI Nexus');
    expect(home).toHaveTextContent('Management');
  });

  it('says who sign-in is open to while the platform is closed (#61)', () => {
    maintenance.closed = true;
    maintenance.status = {
      closed: true,
      phase: 'maintenance',
      message: 'Back after the runtime upgrade.',
      expected_return_at: null,
      revision: 1,
    };
    render(<AuthLayout>Authentication screen</AuthLayout>);

    expect(screen.getByText('Closed for maintenance')).toBeInTheDocument();
    expect(screen.getByText('Back after the runtime upgrade.')).toBeInTheDocument();
    // Sign-in itself stays: administrators need it.
    expect(screen.getByText('Authentication screen')).toBeInTheDocument();
  });
});
