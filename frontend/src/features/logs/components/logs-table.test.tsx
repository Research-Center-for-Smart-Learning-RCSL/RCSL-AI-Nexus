import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { LogsTable } from '@/features/logs/components/logs-table';
import type { AuditEntry } from '@/features/logs/schema';

/**
 * Where the width cap on the wide columns lives.
 *
 * This asserts a structural detail on purpose, because the structural detail
 * *was* the defect. `max-w-[20rem] truncate` sat on the `<td>`, and under the
 * automatic table layout these tables use, a cell's `max-width` is advisory —
 * the column is sized from its content first. So the cap did nothing,
 * `truncate` had nothing to truncate against, and a long value widened the
 * table until it ran off the right edge, reachable only through the wrapper's
 * horizontal scrollbar and never showing an ellipsis to say there was more.
 * `detail` joins every key and value of an audit entry into one line, so that
 * column found it first.
 *
 * jsdom performs no layout, so nothing here can observe the overflow itself.
 * What it can observe is the one thing that fixes it and the one thing a
 * future edit would undo: the cap constrains a block *inside* the cell. Moving
 * it back onto the `<td>` — which reads as a tidy simplification — fails here.
 */

const entry: AuditEntry = {
  id: 'e1',
  actor_id: 'u1',
  actor_display: 'someone@example.test',
  actor_source: 'local',
  action: 'api_key.revoked',
  target: 'a-target-long-enough-to-need-the-cap-that-was-not-being-applied',
  outcome: 'success',
  detail: {
    reason: 'a detail line long enough to widen the column past the viewport',
    key_id: '916af6c60060174b',
  },
  at: '2026-08-04T12:31:23Z',
};

vi.mock('@/features/logs/hooks/use-logs', () => ({
  useLogs: () => ({
    data: { entries: [entry], total: 1, limit: 50, offset: 0 },
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock('@/features/assistant/context', () => ({
  useAssistantSurface: () => {},
}));

function cellHolding(text: string): HTMLElement {
  const node = screen.getByText(text, { exact: false });
  const cell = node.closest('td');
  if (!cell) throw new Error(`no cell around ${text}`);
  return cell;
}

describe('the columns that can hold something wider than the screen', () => {
  it('caps the detail column on a block inside the cell, not on the cell', () => {
    render(<LogsTable />);

    const cell = cellHolding('a detail line long enough');
    expect(cell.className).not.toMatch(/max-w-/);

    const inner = cell.querySelector('div');
    expect(inner?.className).toMatch(/max-w-/);
    expect(inner?.className).toMatch(/truncate/);
  });

  it('caps the target column the same way', () => {
    render(<LogsTable />);

    const cell = cellHolding('a-target-long-enough');
    expect(cell.className).not.toMatch(/max-w-/);
    expect(cell.querySelector('div')?.className).toMatch(/truncate/);
  });

  it('keeps the full text reachable on the cell that shows a clipped one', () => {
    // The ellipsis says there is more; the title is where the more lives. One
    // without the other is either a dead end or an invisible affordance.
    render(<LogsTable />);

    expect(cellHolding('a detail line long enough')).toHaveAttribute('title');
    expect(cellHolding('a-target-long-enough')).toHaveAttribute('title');
  });
});
