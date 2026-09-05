import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';
import { PageHeader } from './page-header';

describe('PageHeader disclosure feedback', () => {
  afterEach(() => vi.restoreAllMocks());

  it('changes its native disclosure state immediately when reduced motion is requested', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true });
    render(
      <PageHeader title="A screen" lead="A brief explanation." detailsLabel="More detail">
        Additional guidance.
      </PageHeader>,
    );

    const details = screen.getByText('Additional guidance.').closest('details');
    if (!details) throw new Error('Expected the page header disclosure.');

    expect(details.open).toBe(false);
    expect(details.querySelector('svg')).toHaveClass(
      'nexus-disclosure-chevron',
      'group-open:rotate-90',
    );

    fireEvent.click(screen.getByText('More detail'));

    expect(details.open).toBe(true);
  });
});
