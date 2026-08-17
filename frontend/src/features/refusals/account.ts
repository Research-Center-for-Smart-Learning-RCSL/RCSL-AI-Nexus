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
