/**
 * Constrain a caller-supplied redirect target to this origin.
 *
 * Prefix checks do not work here. An earlier version accepted anything
 * starting with `/` that did not start with `//`, which lets `/\evil.example`
 * through: the URL parser normalises a backslash after the leading slash into
 * a second slash for special schemes, so the browser resolves it to
 * `https://evil.example/` and navigates off-site.
 *
 * That is worth more than a normal open redirect on a login page. The victim
 * authenticates on the genuine origin, including the second factor, and only
 * then lands on a clone that says the session expired and asks them to sign in
 * again. Everything before the redirect looks correct because it is correct.
 *
 * So resolve the value properly and compare origins, rather than reasoning
 * about which prefixes are dangerous.
 */
export const DEFAULT_REDIRECT = '/dashboard';

export function sameOriginPath(
  requested: string | null | undefined,
  origin: string = typeof window === 'undefined' ? 'http://localhost' : window.location.origin,
): string {
  if (!requested) return DEFAULT_REDIRECT;
  try {
    const url = new URL(requested, origin);
    if (url.origin !== origin) return DEFAULT_REDIRECT;
    // Rebuilt from the parsed parts, so nothing from the original string
    // survives unexamined. The fragment is dropped deliberately.
    return `${url.pathname}${url.search}`;
  } catch {
    return DEFAULT_REDIRECT;
  }
}
