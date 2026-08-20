import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { asked, TestRefusalsTable } from './refusals-table-test-support';

describe('narrowing to one account by the name the screen shows', () => {
  it('completes to the login, because that is what the searched column holds', () => {
    // `actor_display` is written from `actor.display` — a login on an admin
    // entrance, a key handle on the gateway, never a display name. Offering
    // display names meant the completion the screen itself suggested could
    // land on a search that no row can match.
    render(<TestRefusalsTable />);

    const options = [...document.querySelectorAll('#refusal-account-names option')].map(
      (option) => [
        (option as HTMLOptionElement).value,
        (option as HTMLOptionElement).label,
      ],
    );
    expect(options).toEqual([
      ['chen@example.test', 'Chen'],
      ['wu@example.test', 'Wu Mei'],
    ]);
  });

  it('sends a name it can resolve as that account’s id', async () => {
    render(<TestRefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'Wu Mei' },
    });

    await vi.waitFor(() =>
      expect(asked.actor_id).toBe('11111111-2222-3333-4444-555555555555'),
    );
    expect(asked.actor_display).toBeUndefined();
  });

  it('sends a name it cannot resolve as a search of the recorded names', async () => {
    // The deleted account, whose login survives on the row and nowhere else.
    render(<TestRefusalsTable />);

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'departed' },
    });

    await vi.waitFor(() => expect(asked.actor_display).toBe('departed'));
    expect(asked.actor_id).toBeUndefined();
  });

  it('waits for the typing to stop before asking', async () => {
    /**
     * A name search is `ILIKE '%…%'` on an unindexed column, run twice per
     * request — once for the page and once for the count — and every
     * cross-account request also writes a `refusal.read_any` audit row. Typing
     * a twelve-character name used to be twelve requests, twenty-four scans
     * and twelve audit rows naming each successive prefix.
     */
    render(<TestRefusalsTable />);
    const box = screen.getByLabelText(/Show one account's refusals/);

    for (const prefix of ['d', 'de', 'dep', 'depa']) {
      fireEvent.change(box, { target: { value: prefix } });
    }

    // None of the prefixes reached the server on its own.
    expect(asked.actor_display).toBeUndefined();
    await vi.waitFor(() => expect(asked.actor_display).toBe('depa'));
  });

  it('filters by the id a row already carries rather than guessing at it', async () => {
    render(<TestRefusalsTable />);

    fireEvent.click(screen.getAllByRole('button', { name: /student@example.test/ })[0]);

    // Pinned, not parsed back out of the box: an exact filter is the only one
    // that also catches this account's gateway refusals, whose recorded name
    // is the key's handle rather than the person's — and `u2` is not a string
    // any guess would read as an id.
    await vi.waitFor(() => expect(asked.actor_id).toBe('u2'));
    expect(asked.actor_display).toBeUndefined();
  });

  it('lets go of that id as soon as somebody types over it', async () => {
    render(<TestRefusalsTable />);

    fireEvent.click(screen.getAllByRole('button', { name: /student@example.test/ })[0]);
    await vi.waitFor(() => expect(asked.actor_id).toBe('u2'));

    fireEvent.change(screen.getByLabelText(/Show one account's refusals/), {
      target: { value: 'departed' },
    });

    await vi.waitFor(() => expect(asked.actor_display).toBe('departed'));
    expect(asked.actor_id).toBeUndefined();
  });
});
