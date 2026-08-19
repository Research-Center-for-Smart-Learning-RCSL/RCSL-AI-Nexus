import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { asked, TestRefusalsTable, written } from './refusals-table-test-support';

describe('what the paste says it is', () => {
  it('names every filter in force, not the two this screen started with', async () => {
    /**
     * The account filter was added without being added to the subtitle, so a
     * page copied while narrowed to one person was headed "from all accounts"
     * — the exact misleading excerpt the exporter was written to prevent,
     * produced by its own caller.
     */
    render(<TestRefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'Wu Mei' },
    });
    fireEvent.change(screen.getByLabelText('From, inclusive'), {
      target: { value: '2026-08-17T19:00' },
    });
    await vi.waitFor(() =>
      expect(asked.actor_id).toBe('11111111-2222-3333-4444-555555555555'),
    );
    fireEvent.click(screen.getByRole('button', { name: /Copy this page/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('account 11111111-2222-3333-4444-555555555555');
    expect(written[0]).toContain(`from ${new Date('2026-08-17T19:00').toISOString()}`);
  });
});
