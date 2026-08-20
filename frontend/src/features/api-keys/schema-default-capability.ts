import { z } from 'zod';

import type { IssuableCapability } from '@/features/models/schema';

export const NO_DEFAULT = 'refuse';

export function defaultCapabilityPayload(value: string): string | null {
  return value === NO_DEFAULT ? null : value;
}

export function defaultCapabilityField(value: string | null): string {
  return value ?? NO_DEFAULT;
}

export function defaultCapabilityOptions(
  scopes: IssuableCapability[],
  current: string,
): string[] {
  if (current === NO_DEFAULT || current === '') return scopes;
  return scopes.includes(current as IssuableCapability)
    ? scopes
    : [...scopes, current];
}

export function defaultWithinScopes<
  T extends { scopes: IssuableCapability[]; default_capability: string },
>(values: T, ctx: z.RefinementCtx): void {
  if (values.default_capability === NO_DEFAULT) return;
  if (values.scopes.includes(values.default_capability as IssuableCapability)) {
    return;
  }
  ctx.addIssue({
    code: 'custom',
    path: ['default_capability'],
    message: 'Choose a capability this key is being issued for.',
  });
}
