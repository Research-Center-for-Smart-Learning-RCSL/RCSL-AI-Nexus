import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiKeyTable } from '@/features/api-keys/components/api-key-table';
import type { ApiKey } from '@/features/api-keys/schema';

/**
 * Hiding revoked keys, and the two ways that could go quietly wrong: rows that
 * vanish with no way back, and an empty table that blames the reader for not
 * having issued a key.
 *
 * The situation it was built for is real rather than imagined. This deployment
 * reached seven keys of which six were single-use verification keys revoked
 * minutes after being issued, and the seventh was revoked once it turned out
 * nothing had used it in nine days — so the screen's entire content was
 * history, and the one row anybody would come back for is the one that is not
 * there yet.
 */

const keys: ApiKey[] = [];

vi.mock('@/features/api-keys/hooks/use-api-keys', () => ({
  useApiKeys: () => ({ data: keys, isLoading: false, error: null, refetch: vi.fn() }),
  useRevokeApiKey: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock('@/features/assistant/context', () => ({
  useAssistantSurface: () => {},
}));

// Both are dialogs mounted beside the table and neither is under test here.
vi.mock('@/features/api-keys/components/create-api-key-dialog', () => ({
  CreateApiKeyDialog: () => null,
}));
vi.mock('@/features/api-keys/components/edit-api-key-dialog', () => ({
  EditApiKeyDialog: () => null,
}));

vi.mock('@/lib/session', () => ({
  useSession: () => ({
    me: { id: 'u1' },
    can: (scope: string) => scope === 'api_key:write_own',
  }),
}));

function key(name: string, revoked: boolean): ApiKey {
  return {
    key_id: `id-${name}`,
    name,
    scopes: ['chat'],
    rate_limit_rpm: 60,
    quota_tokens_per_day: 1000,
    allowed_cidrs: [],
    expires_at: '2027-01-01T00:00:00Z',
    owner_id: 'u1',
    owner_display: 'someone@example.test',
    revoked_at: revoked ? '2026-08-04T12:31:23Z' : null,
    created_at: '2026-07-26T00:00:00Z',
    last_used_at: null,
  };
}

function listedKeys(names: string[]) {
  keys.length = 0;
  keys.push(...names.map((n) => key(n, n.startsWith('revoked'))));
}

beforeEach(() => {
  listedKeys(['active-one', 'revoked-one', 'revoked-two']);
});

describe('hiding revoked keys', () => {
  it('leaves them out until asked', () => {
    render(<ApiKeyTable />);

    expect(screen.getByText('active-one')).toBeInTheDocument();
    expect(screen.queryByText('revoked-one')).not.toBeInTheDocument();
  });

  it('says how many are hidden, so they are not merely missing', () => {
    // The whole reason hiding by default is safe. Without the count the reader
    // is left hunting for a key they know they created.
    render(<ApiKeyTable />);

    expect(screen.getByRole('button', { name: 'Show 2 revoked' })).toBeInTheDocument();
  });

  it('brings them back, and offers to hide them again', async () => {
    const user = userEvent.setup();
    render(<ApiKeyTable />);

    await user.click(screen.getByRole('button', { name: 'Show 2 revoked' }));

    expect(screen.getByText('revoked-one')).toBeInTheDocument();
    expect(screen.getByText('revoked-two')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Hide 2 revoked' }));
    expect(screen.queryByText('revoked-one')).not.toBeInTheDocument();
  });

  it('offers no toggle when there is nothing to hide', () => {
    // A control that filters nothing is a question the reader has to answer
    // for no reason.
    listedKeys(['active-one']);
    render(<ApiKeyTable />);

    expect(screen.queryByRole('button', { name: /revoked/ })).toBeNull();
  });
});

describe('searching while revoked keys are hidden', () => {
  it('does not tell someone with keys that they have none', async () => {
    // The failure a review caught, and the exact path the whole change exists
    // to prevent: search runs *after* this filter, so typing the name of a key
    // you know you created — and have revoked — emptied the table and answered
    // with "No API keys / Issue a key to let an application reach the gateway".
    // The way out stays on screen throughout: the toggle above still reads
    // "Show 2 revoked".
    const user = userEvent.setup();
    render(<ApiKeyTable />);

    await user.type(screen.getByLabelText('Search keys'), 'revoked-one');

    expect(screen.getByText('No matches')).toBeInTheDocument();
    expect(screen.queryByText('No API keys')).toBeNull();
    expect(
      screen.getByRole('button', { name: 'Show 2 revoked' }),
    ).toBeInTheDocument();
  });

  it('clears the search from the message it shows', async () => {
    const user = userEvent.setup();
    render(<ApiKeyTable />);

    await user.type(screen.getByLabelText('Search keys'), 'zzz');
    await user.click(screen.getByRole('button', { name: 'Clear search' }));

    expect(screen.getByText('active-one')).toBeInTheDocument();
  });
});

describe('when every key has been revoked', () => {
  it('says so rather than suggesting none was ever issued', async () => {
    // The failure this guards against: filtering all the rows out leaves the
    // table in the same state as a fresh deployment, and the stock empty
    // message then tells someone with seven keys to go and issue one.
    listedKeys(['revoked-one', 'revoked-two']);
    render(<ApiKeyTable />);

    expect(screen.getByText('No active keys')).toBeInTheDocument();
    expect(
      screen.getByText(/Every key here has been revoked/),
    ).toBeInTheDocument();

    // And the way out is named in the message and present on the screen.
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Show 2 revoked' }));
    expect(screen.getByText('revoked-one')).toBeInTheDocument();
  });
});
