import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ROWS, TestRefusalsTable, tickFor, written } from './refusals-table-test-support';

describe('copying some of the rows rather than all or one', () => {
  it('copies the page when nothing is ticked', async () => {
    render(<TestRefusalsTable />);

    expect(screen.getByRole('button', { name: /Copy this page/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Copy this page/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('3 of 120 shown');
  });

  it('copies only the ticked rows, and counts them on the button', async () => {
    render(<TestRefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    fireEvent.click(tickFor(ROWS[2]));

    fireEvent.click(screen.getByRole('button', { name: /Copy 2 selected/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('`req_one`');
    expect(written[0]).toContain('`req_three`');
    expect(written[0]).not.toContain('`req_two`');
  });

  it('says a hand-picked paste is one', async () => {
    /**
     * Two rows out of a hundred and twenty, pasted into a ticket with no note,
     * read as the whole of what happened. A whole page at least tells the
     * reader how much of the window they are holding; a selection is a
     * *choice*, and nothing in the numbers says which of the rest were passed
     * over or why. It is the more misleading of the two, so it is the one that
     * has to say so.
     */
    render(<TestRefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    fireEvent.click(screen.getByRole('button', { name: /Copy 1 selected/ }));
    await vi.waitFor(() => expect(written).toHaveLength(1));

    expect(written[0]).toContain('1 hand-picked out of 120 matching');
  });

  it('ticks and clears the whole page from the header', () => {
    render(<TestRefusalsTable />);

    fireEvent.click(screen.getByLabelText('Select every refusal on this page'));
    expect(screen.getByRole('button', { name: /Copy 3 selected/ })).toBeTruthy();

    fireEvent.click(screen.getByLabelText('Clear the selection'));
    expect(screen.getByRole('button', { name: /Copy this page/ })).toBeTruthy();
  });

  it('shows the header box as part-way when only some rows are ticked', () => {
    render(<TestRefusalsTable />);

    fireEvent.click(tickFor(ROWS[1]));

    const all = screen.getByLabelText('Select every refusal on this page') as HTMLInputElement;
    expect(all.indeterminate).toBe(true);
    expect(all.checked).toBe(false);
  });

  it('drops the selection when the rows underneath it change', async () => {
    // A tick means "this refusal, the one I am looking at". Carried across a
    // filter change it leaves the button offering a count of rows the reader
    // can no longer see and cannot check.
    render(<TestRefusalsTable />);

    fireEvent.click(tickFor(ROWS[0]));
    expect(screen.getByRole('button', { name: /Copy 1 selected/ })).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Filter by error code/), {
      target: { value: 'quota_exceeded' },
    });

    await screen.findByRole('button', { name: /Copy this page/ });
  });
});
