import { readdirSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { NAV } from './app-shell-navigation-catalog';

// Anchored to this file, not to the working directory: a cwd-relative path
// answered existsSync(false) — silently green in the wrong direction — the
// moment the suite ran from anywhere but frontend/.
const APP_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../../app');

/** Every route the app directory actually serves, route groups stripped. */
function servedRoutes(): Set<string> {
  const routes = new Set<string>();
  for (const entry of readdirSync(APP_DIR, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile() || entry.name !== 'page.tsx') continue;
    const relative = resolve(entry.parentPath, entry.name)
      .slice(APP_DIR.length)
      .split(sep)
      .filter((segment) => segment && !segment.startsWith('(') && segment !== 'page.tsx');
    routes.add('/' + relative.join('/'));
  }
  return routes;
}

describe('the navigation catalog', () => {
  it('maps every entry to a page that actually owns its route', () => {
    const routes = servedRoutes();
    for (const item of NAV) {
      expect(routes.has(item.href), `${item.label} -> ${item.href} has no page.tsx`).toBe(true);
    }
  });

  it('keeps the navigation guard pinned to the Dashboard route that owns the page', () => {
    // The forbidden-route guard matches the catalog's own hrefs; moving the
    // page without this entry restores the authz.denied noise of 2026-08-14.
    const entry = NAV.find((item) => item.label === 'Dashboard');
    expect(entry?.href).toBe('/dashboard');
  });
});
