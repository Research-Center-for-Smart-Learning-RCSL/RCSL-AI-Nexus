import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { RefusalsTable } from '@/features/refusals/components/refusals-table';
import type { Refusal } from '@/features/refusals/schema';

/**
 * What a row does when its content is long, which on this screen is routine.
 *
 * The stored `context_too_long` carries a 287-character message, three
 * figures, a 113-character composition and a 295-character remedy — about
 * seven hundred characters of prose in one cell, beside a `rate_limited` whose
 * entire message is eighteen. Capping the *width* stopped the table running
 * off the right edge and did nothing about the height: one row stood four
 * times taller than its neighbours, and the remedy — which is advice per code
 * rather than per row — printed once for every row sharing that code.
 *
 * jsdom performs no layout, so nothing here observes a height. What it can
 * observe is what bounds it: the long fields are clamped until somebody opens
 * the row, and the remedy is not in the document at all until then.
 */

const LONG: Refusal = {
  id: 'r1',
  at: '2026-08-18T00:40:46.354Z',
  code: 'context_too_long',
  status: 413,
  actor_id: 'u1',
  actor_display: 'teacher@example.test',
  api_key_id: '979e405245fd70d8',
  surface: 'gateway',
  method: 'POST',
  path: '/v1/chat/completions',
  request_id: 'req_ab40e7554c4d42c0',
  message:
    'This input is 125,340 tokens against a limit of 122,880, counting tool definitions and every replayed turn. Retrying it unchanged cannot succeed and waiting does not clear it: send less — start a new conversation, continue from a summary of this one, or stop reading large files into it.',
  figures: {
    estimated: 125340,
    limit: 122880,
    basis: 'tokenizer',
    composition:
      '~125329 in 1 messages (largest turn ~125329, 100% of the whole), ~0 in prior tool calls, ~0 in 0 tool definitions',
  },
};

vi.mock('@/features/refusals/hooks/use-refusals', () => ({
  useRefusals: () => ({
    data: { entries: [LONG], total: 1, limit: 50, offset: 0, scoped_to_self: true },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock('@/features/users/hooks/use-users', () => ({
  useUsers: () => ({ data: undefined }),
}));

const REMEDY = /Read the composition before choosing a fix/;

function paragraphHolding(text: string | RegExp): HTMLElement {
  const node = screen.getByText(text, { exact: false });
  return node.closest('p') ?? node;
}

describe('a row whose content is longer than the row', () => {
  it('clamps the message until the row is opened', () => {
    render(<RefusalsTable />);

    const message = paragraphHolding('This input is 125,340 tokens');
    expect(message.className).toMatch(/line-clamp-2/);
    // The clamp says there is more; the title is where the more lives.
    expect(message).toHaveAttribute('title');
  });

  it('clamps the composition to the one line it is scanned on', () => {
    render(<RefusalsTable />);

    const composition = paragraphHolding('~125329 in 1 messages');
    expect(composition.className).toMatch(/line-clamp-1/);
  });

  it('keeps the remedy out of the document until somebody asks for it', () => {
    // Advice per code, not per row: fifty 413s would otherwise print the same
    // paragraph fifty times.
    render(<RefusalsTable />);

    expect(screen.queryByText(REMEDY)).toBeNull();
  });

  it('shows everything in full once the row is opened, and clamps it again', () => {
    render(<RefusalsTable />);

    fireEvent.click(screen.getByLabelText('Show all of this refusal'));

    expect(screen.getByText(REMEDY)).toBeTruthy();
    expect(paragraphHolding('This input is 125,340 tokens').className).not.toMatch(/line-clamp/);
    expect(paragraphHolding('~125329 in 1 messages').className).not.toMatch(/line-clamp/);

    fireEvent.click(screen.getByLabelText('Show less of this refusal'));

    expect(screen.queryByText(REMEDY)).toBeNull();
  });

  it('wraps the tooltip, because a native title renders on one line however long it is', () => {
    /**
     * The helper is unit-tested on its own; what this pins is that the cell
     * actually uses it. A `title` carrying the 287-character message renders
     * as a strip of text wider than the window, clipped by the screen edge,
     * with the end of the sentence somewhere off it — and passing the raw
     * string here reads as the obvious thing to do.
     */
    render(<RefusalsTable />);

    const title = paragraphHolding('This input is 125,340 tokens').getAttribute('title');

    expect(title).toContain('\n');
    for (const line of title!.split('\n')) expect(line.length).toBeLessThanOrEqual(72);
    // Wrapped, not shortened.
    expect(title!.replace(/\n/g, ' ')).toBe(LONG.message);
  });

  it('caps the wide columns on a block inside the cell, not on the cell', () => {
    // The same defect the audit log records, which this table had repeated in
    // four columns: a `max-width` on a `td` is advisory under the automatic
    // table layout, so the cap is ignored and one long value widens the table.
    render(<RefusalsTable />);

    const path = screen.getByText(/\/v1\/chat\/completions/).closest('td');
    expect(path?.className).not.toMatch(/max-w-/);
    expect(path?.querySelector('div')?.className).toMatch(/truncate/);
    expect(path).toHaveAttribute('title');
  });
});
