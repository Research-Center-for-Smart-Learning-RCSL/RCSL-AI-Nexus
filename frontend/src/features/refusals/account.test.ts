import { describe, expect, it } from 'vitest';

import { accountOptions, accountQuery } from '@/features/refusals/account';
import type { User } from '@/features/users/schema';

/**
 * Which of the server's two account filters a typed name means.
 *
 * The screen had one box and it wanted an account id, which is a uuid — and
 * nothing on this screen is a uuid a person could have typed. The name in the
 * column is resolved in the browser against the accounts the reader can list;
 * the row's own `actor_display` is the *credential's* display, which for a
 * gateway caller is the key handle. So the filter that answers "whose?" could
 * only be used by somebody who had already answered it somewhere else.
 *
 * The two filters are not interchangeable, which is what these pin. An id
 * follows the account and catches its gateway refusals, whose recorded name is
 * the key's rather than the person's. A name search is the only thing that
 * finds a deleted account's, whose name survives on the row and nowhere else.
 */

function user(over: Partial<User> & { id: string }): User {
  return {
    login: 'someone@example.test',
    display_name: 'Someone',
    tailscale_login: null,
    has_local_credentials: true,
    has_totp: true,
    role: 'user',
    debug_logging_until: null,
    created_at: null,
    ...over,
  };
}

const WU = user({ id: '11111111-2222-3333-4444-555555555555', display_name: 'Wu Mei', login: 'wu@example.test' });
const CHEN = user({ id: '66666666-7777-8888-9999-000000000000', display_name: 'Chen', login: 'chen@example.test' });
const USERS = new Map([WU, CHEN].map((u) => [u.id, u]));

describe('accountQuery', () => {
  it('asks nothing of the server for an empty box', () => {
    expect(accountQuery('   ', USERS)).toEqual({});
  });

  it('turns a name it can resolve into that account’s id', () => {
    // The point of resolving rather than searching: this person's gateway
    // refusals record the API key's handle in `actor_display`, so a name
    // search would return their admin refusals and silently drop the rest.
    expect(accountQuery('Wu Mei', USERS)).toEqual({ actor_id: WU.id });
    expect(accountQuery('  wu mei  ', USERS)).toEqual({ actor_id: WU.id });
    expect(accountQuery('chen@example.test', USERS)).toEqual({ actor_id: CHEN.id });
  });

  it('searches by name when no account answers to it', () => {
    // A deleted account, an API key's handle, or a name half-typed. All three
    // are real states and all three are only findable on the row itself.
    expect(accountQuery('departed', USERS)).toEqual({ actor_display: 'departed' });
    expect(accountQuery('979e4052', USERS)).toEqual({ actor_display: '979e4052' });
  });

  it('does not pick one of several people who share a name', () => {
    const twins = new Map(
      [
        user({ id: 'a1', display_name: 'Sam', login: 'sam.one@example.test' }),
        user({ id: 'a2', display_name: 'Sam', login: 'sam.two@example.test' }),
      ].map((u) => [u.id, u]),
    );

    // A search returns both and says so. Resolving to whichever came first in
    // the map would show one person's refusals under the other's name.
    expect(accountQuery('Sam', twins)).toEqual({ actor_display: 'Sam' });
  });

  it('takes a pasted uuid as an id even when it cannot list that account', () => {
    // The id quoted in an audit row is how an investigation crosses from one
    // screen to this one, and the account it names may be gone. Treating it as
    // a substring would search for rows whose *display* looked like a uuid.
    expect(accountQuery('99999999-8888-7777-6666-555555555555', USERS)).toEqual({
      actor_id: '99999999-8888-7777-6666-555555555555',
    });
    expect(accountQuery('99999999-8888-7777-6666-555555555555')).toEqual({
      actor_id: '99999999-8888-7777-6666-555555555555',
    });
  });

  it('searches by name when the accounts have not arrived yet', () => {
    // A working query rather than a broken one. The box is only shown to a
    // reader whose accounts are being fetched, so this is the gap before they
    // land — a name search is narrower coverage, not a wrong answer.
    expect(accountQuery('Wu Mei')).toEqual({ actor_display: 'Wu Mei' });
  });
});

describe('accountOptions', () => {
  it('offers each name once, in an order somebody can scan', () => {
    expect(accountOptions(USERS)).toEqual(['Chen', 'Wu Mei']);
  });

  it('falls back to the login where an account has no display name', () => {
    const nameless = new Map([['x', user({ id: 'x', display_name: '  ', login: 'x@example.test' })]]);
    expect(accountOptions(nameless)).toEqual(['x@example.test']);
  });

  it('is empty before the accounts arrive', () => {
    expect(accountOptions(undefined)).toEqual([]);
  });
});
