import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { asked, TestRefusalsTable } from './refusals-table-test-support';

describe('narrowing to when it happened', () => {
  it('asks for no window until somebody sets one', () => {
    render(<TestRefusalsTable />);

    expect(asked.since).toBeUndefined();
    expect(asked.until).toBeUndefined();
  });

  it('sends the instant a typed local time names', () => {
    render(<TestRefusalsTable />);

    fireEvent.change(screen.getByLabelText('From, inclusive'), {
      target: { value: '2026-08-17T19:00' },
    });

    expect(asked.since).toBe(new Date('2026-08-17T19:00').toISOString());
  });

  it('fills the boxes from a preset rather than replacing them', () => {
    // So the reader can see what "last hour" meant and then move it — and so
    // the boundary stays put while they page through what it matched.
    render(<TestRefusalsTable />);

    fireEvent.click(screen.getByRole('button', { name: 'Today' }));

    const from = screen.getByLabelText('From, inclusive') as HTMLInputElement;
    expect(from.value).toMatch(/T00:00$/);
    expect(asked.since).toBeDefined();
  });

  it('clears both ends at once', () => {
    render(<TestRefusalsTable />);

    fireEvent.change(screen.getByLabelText('Before, exclusive'), {
      target: { value: '2026-08-18T00:00' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

    expect(asked.until).toBeUndefined();
  });
});
