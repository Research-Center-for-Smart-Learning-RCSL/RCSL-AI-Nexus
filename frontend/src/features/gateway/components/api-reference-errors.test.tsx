import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { elementToMarkdown } from '@/lib/markdown-export';
import { ErrorsSection } from './api-reference-errors';

function visibleCodes(): string[] {
  const table = screen.getByRole('table');
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1]?.textContent ?? '');
}

describe('ErrorsSection search', () => {
  it('starts with the complete labelled catalogue and announces its count', () => {
    render(<ErrorsSection />);

    expect(screen.getByRole('searchbox', { name: 'Search errors' })).toHaveValue(
      '',
    );
    expect(visibleCodes()).toHaveLength(17);
    expect(screen.getByText('17 of 17 errors shown.')).toHaveAttribute(
      'aria-live',
      'polite',
    );
  });

  it('matches every record with a status code', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), '429');

    expect(visibleCodes()).toEqual(['rate_limited', 'quota_exceeded']);
    expect(screen.getByText('2 of 17 errors shown.')).toBeInTheDocument();
  });

  it('matches exact and partial error codes case-insensitively', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);
    const search = screen.getByRole('searchbox');

    await user.type(search, 'QuOtA_ExCeEdEd');
    expect(visibleCodes()).toEqual(['quota_exceeded']);

    await user.clear(search);
    await user.type(search, 'QuOtA_Ex');
    expect(visibleCodes()).toEqual(['quota_exceeded']);
  });

  it('matches visible remediation text', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), 'token budget');

    expect(visibleCodes()).toEqual(['quota_exceeded']);
  });

  it('normalises punctuation in visible remediation text', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), 'request id');

    expect(visibleCodes()).toEqual(['context_too_long', 'internal_error']);
  });

  it('supports a catalogue alias for the status-less stream marker', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), 'stream marker');

    expect(visibleCodes()).toEqual(['stream_interrupted']);
  });

  it('treats whitespace-only input as an unfiltered catalogue', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), '   ');

    expect(visibleCodes()).toHaveLength(17);
    expect(screen.getByText('17 of 17 errors shown.')).toBeInTheDocument();
  });

  it('keeps recovery controls available when no record matches', async () => {
    const user = userEvent.setup();
    render(<ErrorsSection />);
    const search = screen.getByRole('searchbox');

    await user.type(search, 'definitely-not-an-api-error');

    expect(screen.getByRole('heading', { name: 'Errors' })).toBeInTheDocument();
    expect(search).toHaveValue('definitely-not-an-api-error');
    expect(screen.getByText('0 of 17 errors shown.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('No matching errors')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear search' }));

    expect(search).toHaveValue('');
    expect(visibleCodes()).toHaveLength(17);
  });

  it('exports every authored record even while the visible table is filtered', async () => {
    const user = userEvent.setup();
    const { container } = render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), 'quota_exceeded');
    expect(visibleCodes()).toEqual(['quota_exceeded']);

    const markdown = elementToMarkdown(container);
    expect(markdown).toContain('| 429 | quota\\_exceeded |');
    expect(markdown).toContain('| 401 | not\\_authenticated |');
    expect(markdown).toContain('| — | stream\\_interrupted |');
    expect(markdown).not.toContain('Search errors');
  });

  it('keeps the complete export when the visual state has no results', async () => {
    const user = userEvent.setup();
    const { container } = render(<ErrorsSection />);

    await user.type(screen.getByRole('searchbox'), 'no-such-error');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    const markdown = elementToMarkdown(container);
    expect(markdown).toContain('| 400 | untrusted\\_proxy |');
    expect(markdown).toContain('| 500 | internal\\_error |');
    expect(markdown).not.toContain('No matching errors');
  });
});
