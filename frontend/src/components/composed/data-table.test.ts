import { describe, expect, it } from 'vitest';

import { columnLabel } from '@/components/composed/data-table';

/**
 * The visibility menu used to render `column.id` verbatim, so it named columns
 * `expires_at` and `cidrs` while their own headers read Expires and Sources.
 */
describe('columnLabel', () => {
  it('prefers the header a column already displays', () => {
    expect(columnLabel('Expires', 'expires_at')).toBe('Expires');
    expect(columnLabel('Sources', 'cidrs')).toBe('Sources');
  });

  it('humanises the id when the header is not a plain string', () => {
    // A header rendered by a component, which is not something to put in a menu.
    expect(columnLabel(() => null, 'expires_at')).toBe('Expires at');
    expect(columnLabel(undefined, 'rate_limit_rpm')).toBe('Rate limit rpm');
    expect(columnLabel(undefined, 'created-at')).toBe('Created at');
  });

  it('falls back for an empty header rather than showing a blank row', () => {
    // The actions column has `header: ''`, and a blank checkbox label is
    // unclickable in the sense that matters: nobody knows what it toggles.
    expect(columnLabel('', 'actions')).toBe('Actions');
  });

  it('leaves an already-spaced id alone apart from its first letter', () => {
    expect(columnLabel(undefined, 'owner')).toBe('Owner');
  });
});
