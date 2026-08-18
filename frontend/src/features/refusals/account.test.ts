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

    // Resolving to whichever came first in the map would show one person's
    // refusals under the other's name, so it stays a search — and a search for
    // "Sam" finds nothing, because `actor_display` holds logins rather than
    // display names. That is why `accountOptions` completes to the login: the
    // reader is never handed the string that lands here.
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
  it('completes to the login, and labels it with the name', () => {
    /**
     * **The value has to be a string that works, and a display name is the one
     * string that works on neither path.** `accountQuery` resolves an
     * unambiguous one to an id, so offering names looked correct; two people
     * called "Sam" fall through to the name search instead, and
     * `refusals.actor_display` holds `sam.one@…` and `sam.two@…` — it is
     * written from `actor.display`, which is the *login* on an admin entrance
     * and the API key's handle on the gateway, never a display name. So the
     * completion the screen itself offered returned nothing.
     *
     * A login resolves exactly, and is a substring of what the row stores if
     * it ever falls through. The name rides along as the label.
     */
    expect(accountOptions(USERS)).toEqual([
      { value: 'chen@example.test', label: 'Chen' },
      { value: 'wu@example.test', label: 'Wu Mei' },
    ]);
  });

  it('offers a completion that a search would actually match', () => {
    const twins = new Map(
      [
        user({ id: 'a1', display_name: 'Sam', login: 'sam.one@example.test' }),
        user({ id: 'a2', display_name: 'Sam', login: 'sam.two@example.test' }),
      ].map((u) => [u.id, u]),
    );

    // The ambiguous case, which is the one that falls through to a search.
    // Both completions resolve to an id; neither is the string "Sam" that no
    // row contains.
    for (const option of accountOptions(twins)) {
      expect(accountQuery(option.value, twins).actor_id).toBeTruthy();
    }
  });

  it('labels with the login where an account has no display name', () => {
    const nameless = new Map([['x', user({ id: 'x', display_name: '  ', login: 'x@example.test' })]]);
    expect(accountOptions(nameless)).toEqual([
      { value: 'x@example.test', label: 'x@example.test' },
    ]);
  });

  it('is empty before the accounts arrive', () => {
    expect(accountOptions(undefined)).toEqual([]);
  });
});
