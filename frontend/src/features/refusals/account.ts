import type { Refusal } from '@/features/refusals/schema';
import type { User } from '@/features/users/schema';

/**
 * Who a refusal belongs to, in the order a reader can actually use.
 *
 * The row carries two handles and neither is a name a person recognises: the
 * account id is a uuid, and `actor_display` is the *credential's* display —
 * a login for somebody on an admin entrance, but the key handle for a gateway
 * caller, which is a second hex string. A page of other people's refusals made
 * of those is a page nobody can read.
 *
 * So the name is resolved against the accounts the reader can already list,
 * and the handles are kept rather than replaced: the id is what an
 * investigation quotes, and the recorded `actor_display` is what the platform
 * saw at the time, which is the part worth keeping when an account has since
 * been renamed. Both stay reachable on the hover.
 *
 * **Every fallback is a real state, not a defensive default.** No user row: the
 * account was deleted, which is exactly when the denormalised name earns its
 * place. No `actor_display` either: a row written before that column existed.
 * The id is always there, so there is always something to show.
 */
export type Account = {
  /** What to show. A person's name where one is knowable. */
  name: string;
  /** The account id, kept visible because it is what an audit quotes. */
  id: string;
  /** Everything known about the account, for the hover. */
  title: string;
};

export function describeAccount(refusal: Refusal, users?: Map<string, User>): Account {
  const user = users?.get(refusal.actor_id);
  const login = user?.login?.trim() || '';
  const name = user?.display_name?.trim() || login || refusal.actor_display || refusal.actor_id;
  const parts = [name];
  if (login && login !== name) parts.push(login);
  parts.push(refusal.actor_id);
  if (refusal.actor_display && refusal.actor_display !== name && refusal.actor_display !== login) {
    // What the platform recorded at the time, which is not always what the
    // account is called now — and for a gateway caller is the key handle.
    parts.push(`recorded as ${refusal.actor_display}`);
  }
  return { name, id: refusal.actor_id, title: parts.join(' · ') };
}

export function usersById(users: User[] | undefined): Map<string, User> | undefined {
  return users ? new Map(users.map((user) => [user.id, user])) : undefined;
}

/** Whether a typed account filter is an id or a name. Never both, never neither. */
export type AccountQuery = { actor_id?: string; actor_display?: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * What one account box should ask the server for.
 *
 * The box takes what the screen shows — a name — and the server has two ways to
 * answer that, which are not interchangeable:
 *
 * - **By id**, when the text names an account this reader can list. Exact, and
 *   it follows the *account* rather than the recorded string, which is the
 *   only way to catch that person's gateway refusals: those rows record the
 *   API key's handle in `actor_display`, so a name search misses every one of
 *   them. Resolving to an id where one is knowable is a coverage decision, not
 *   a tidiness one.
 * - **By name, otherwise — and "name" here means the string the row actually
 *   holds.** `actor_display` is written once, from `actor.display`, which is
 *   the account's **login** on an admin entrance and the API key's handle on
 *   the gateway. It is never a `display_name`. So this branch finds the
 *   deleted account whose login survives on the row and nowhere else, and
 *   finds a key by the handle it is known by — and it will not find anybody by
 *   a display name that differs from their login, because no row contains one.
 *   `accountOptions` offers logins for exactly that reason.
 *
 * A pasted uuid is taken as an id whether or not the reader can list it: the
 * accounts fetch is a convenience, and an id quoted out of an audit row must
 * not silently become a substring search for a uuid-shaped display name.
 */
export function accountQuery(text: string, users?: Map<string, User>): AccountQuery {
  const typed = text.trim();
  if (!typed) return {};
  if (users?.has(typed) || UUID.test(typed)) return { actor_id: typed };

  const folded = typed.toLowerCase();
  // Exact, not prefix. A partial name is a search, and treating it as an id
  // would silently pick one of several people who share it.
  const named = [...(users?.values() ?? [])].filter(
    (user) =>
      user.display_name.trim().toLowerCase() === folded ||
      user.login.trim().toLowerCase() === folded,
  );
  if (named.length === 1) return { actor_id: named[0].id };

  return { actor_display: typed };
}

/** One completion: the value that goes in the box, and the name beside it. */
export type AccountOption = { value: string; label: string };

/**
 * The accounts to offer as completions.
 *
 * **The value is the login, not the display name, and that is the whole point
 * of this function.** An earlier version offered display names, which are what
 * the table shows — and they are the one string that works on neither of the
 * paths a completion can take. `accountQuery` resolves an unambiguous one to
 * an id, so it worked by accident; two colleagues called "Sam" fall through to
 * the name search instead, and `refusals.actor_display` holds
 * `sam.one@example.test` and `sam.two@example.test`, so picking "Sam" from the
 * list the screen offered returned nothing at all. A completion that cannot
 * match is worse than no completion: it reads as an answer.
 *
 * The login works on both paths. It resolves exactly, because `accountQuery`
 * matches it; and if it ever falls through, it is a substring of what the row
 * stores. The display name rides along as the option's label, which is what a
 * reader recognises and what the browser shows beside the value.
 *
 * Only ever non-empty for a reader who may see other people's, because that is
 * the only reader for whom the accounts are fetched at all — and the only one
 * for whom the filter does anything.
 */
export function accountOptions(users?: Map<string, User>): AccountOption[] {
  const options: AccountOption[] = [];
  for (const user of users?.values() ?? []) {
    const value = user.login.trim();
    if (!value) continue;
    const name = user.display_name.trim();
    options.push({ value, label: name && name !== value ? name : value });
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}
