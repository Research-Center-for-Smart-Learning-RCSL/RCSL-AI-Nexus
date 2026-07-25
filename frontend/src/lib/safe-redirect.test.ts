import { describe, expect, it } from 'vitest';

import { DEFAULT_REDIRECT, sameOriginPath } from '@/lib/safe-redirect';

const ORIGIN = 'https://app.example';

describe('sameOriginPath', () => {
  it('falls back to the default for empty input', () => {
    expect(sameOriginPath(null, ORIGIN)).toBe(DEFAULT_REDIRECT);
    expect(sameOriginPath(undefined, ORIGIN)).toBe(DEFAULT_REDIRECT);
    expect(sameOriginPath('', ORIGIN)).toBe(DEFAULT_REDIRECT);
  });

  it('keeps a same-origin relative path with its query', () => {
    expect(sameOriginPath('/models', ORIGIN)).toBe('/models');
    expect(sameOriginPath('/models?tab=loaded', ORIGIN)).toBe('/models?tab=loaded');
  });

  it('accepts an absolute URL on the same origin, reduced to path and query', () => {
    expect(sameOriginPath(`${ORIGIN}/users?role=admin`, ORIGIN)).toBe('/users?role=admin');
  });

  it('drops the fragment deliberately', () => {
    expect(sameOriginPath('/models#section', ORIGIN)).toBe('/models');
    expect(sameOriginPath('/models?tab=x#section', ORIGIN)).toBe('/models?tab=x');
  });

  // The regression this module exists for: a backslash after the leading slash
  // is normalised to a second slash for http(s), so a prefix check would let it
  // escape the origin. See the module docstring.
  it('rejects the backslash open-redirect trick', () => {
    expect(sameOriginPath('/\\evil.example', ORIGIN)).toBe(DEFAULT_REDIRECT);
  });

  it('rejects a protocol-relative target', () => {
    expect(sameOriginPath('//evil.example/path', ORIGIN)).toBe(DEFAULT_REDIRECT);
  });

  it('rejects an absolute URL on a different origin', () => {
    expect(sameOriginPath('https://evil.example/path', ORIGIN)).toBe(DEFAULT_REDIRECT);
    expect(sameOriginPath('http://app.example/path', ORIGIN)).toBe(DEFAULT_REDIRECT);
  });

  it('falls back to the default when the value cannot be parsed', () => {
    expect(sameOriginPath('http://[', ORIGIN)).toBe(DEFAULT_REDIRECT);
  });
});
