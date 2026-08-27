import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { NAV } from './app-shell-navigation-catalog';

describe('the dashboard route', () => {
  it('keeps the navigation guard pinned to the route that owns the page', () => {
    const entry = NAV.find((item) => item.label === 'Dashboard');
    const page = resolve('src/app/(dashboard)/dashboard/page.tsx');

    expect(entry?.href).toBe('/dashboard');
    expect(existsSync(page)).toBe(true);
  });
});
