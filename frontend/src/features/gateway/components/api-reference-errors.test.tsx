import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { elementToMarkdown } from '@/lib/markdown-export';
import { API_ERROR_CATALOGUE } from './api-reference-error-catalogue';
import { ErrorsSection } from './api-reference-errors';
import { API_REFERENCE_SECTION_CATALOGUE } from './api-reference-section-catalogue';

const ERRORS_SECTION = API_REFERENCE_SECTION_CATALOGUE.find(
  (section) => section.renderKey === 'errors',
);
if (!ERRORS_SECTION) throw new Error('Errors section is missing from the catalogue.');

function renderErrors() {
  return render(<ErrorsSection section={ERRORS_SECTION} />);
}

function visibleCodes(): string[] {
  const table = screen.getByRole('table');
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[1]?.textContent ?? '');
}

function expectCompleteCatalogueExport(markdown: string): void {
  const codes = API_ERROR_CATALOGUE.map((error) => error.code);
  expect(new Set(codes).size).toBe(API_ERROR_CATALOGUE.length);

  for (const error of API_ERROR_CATALOGUE) {
    const escapedCode = error.code.replaceAll('_', '\\_');
    const rowPrefix = `| ${error.status} | ${escapedCode} |`;
    expect(markdown.split(rowPrefix)).toHaveLength(2);
  }

  const dataRows = markdown
    .split('\n')
    .filter(
      (line) =>
        line.startsWith('| ') &&
        !line.startsWith('| Status |') &&
        !line.startsWith('| --- |'),
    );
  expect(dataRows).toHaveLength(API_ERROR_CATALOGUE.length);
}

describe('ErrorsSection search', () => {
  it('starts with the complete labelled catalogue and announces its count', () => {
    renderErrors();

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
    renderErrors();

    await user.type(screen.getByRole('searchbox'), '429');

    expect(visibleCodes()).toEqual(['rate_limited', 'quota_exceeded']);
    expect(screen.getByText('2 of 17 errors shown.')).toBeInTheDocument();
  });

  it('matches exact and partial error codes case-insensitively', async () => {
    const user = userEvent.setup();
    renderErrors();
    const search = screen.getByRole('searchbox');

    await user.type(search, 'QuOtA_ExCeEdEd');
    expect(visibleCodes()).toEqual(['quota_exceeded']);

    await user.clear(search);
    await user.type(search, 'QuOtA_Ex');
    expect(visibleCodes()).toEqual(['quota_exceeded']);
  });

  it('matches visible remediation text', async () => {
    const user = userEvent.setup();
    renderErrors();

    await user.type(screen.getByRole('searchbox'), 'token budget');

    expect(visibleCodes()).toEqual(['quota_exceeded']);
  });

  it('normalises punctuation in visible remediation text', async () => {
    const user = userEvent.setup();
    renderErrors();

    await user.type(screen.getByRole('searchbox'), 'request id');

    expect(visibleCodes()).toEqual(['context_too_long', 'internal_error']);
  });

  it('supports a catalogue alias for the status-less stream marker', async () => {
    const user = userEvent.setup();
    renderErrors();

    await user.type(screen.getByRole('searchbox'), 'stream marker');

    expect(visibleCodes()).toEqual(['stream_interrupted']);
  });

  it('matches the visible stream marker and rejects other punctuation-only queries', async () => {
    const user = userEvent.setup();
    renderErrors();
    const search = screen.getByRole('searchbox');

    await user.type(search, '—');
    expect(visibleCodes()).toEqual(['stream_interrupted']);

    await user.clear(search);
    await user.type(search, '???');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('0 of 17 errors shown.')).toBeInTheDocument();
  });

  it('treats whitespace-only input as an unfiltered catalogue', async () => {
    const user = userEvent.setup();
    renderErrors();

    await user.type(screen.getByRole('searchbox'), '   ');

    expect(visibleCodes()).toHaveLength(17);
    expect(screen.getByText('17 of 17 errors shown.')).toBeInTheDocument();
  });

  it('keeps recovery controls available when no record matches', async () => {
    const user = userEvent.setup();
    renderErrors();
    const search = screen.getByRole('searchbox');

    await user.type(search, 'definitely-not-an-api-error');

    expect(screen.getByRole('heading', { name: 'Errors' })).toBeInTheDocument();
    expect(search).toHaveValue('definitely-not-an-api-error');
    expect(screen.getByText('0 of 17 errors shown.')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('No matching errors')).toBeInTheDocument();

    const clear = screen.getByRole('button', { name: 'Clear search' });
    clear.focus();
    await user.keyboard('{Enter}');

    expect(search).toHaveValue('');
    expect(search).toHaveFocus();
    expect(visibleCodes()).toHaveLength(17);
  });

  it('allows an unbroken no-results query to wrap inside the empty state', () => {
    renderErrors();
    const longQuery = 'x'.repeat(120);

    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: longQuery },
    });

    const description = screen.getByText(
      `No status, error code, or remediation matches “${longQuery}”.`,
    );
    expect(description.closest('[data-md-skip]')).toHaveClass(
      '[&_p]:[overflow-wrap:anywhere]',
    );
  });

  it('exports every authored record even while the visible table is filtered', async () => {
    const user = userEvent.setup();
    const { container } = renderErrors();

    await user.type(screen.getByRole('searchbox'), 'quota_exceeded');
    expect(visibleCodes()).toEqual(['quota_exceeded']);

    const markdown = elementToMarkdown(container);
    expectCompleteCatalogueExport(markdown);
    expect(markdown).not.toContain('Search errors');
  });

  it('keeps the complete export when the visual state has no results', async () => {
    const user = userEvent.setup();
    const { container } = renderErrors();

    await user.type(screen.getByRole('searchbox'), 'no-such-error');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();

    const markdown = elementToMarkdown(container);
    expectCompleteCatalogueExport(markdown);
    expect(markdown).not.toContain('No matching errors');
  });
});
