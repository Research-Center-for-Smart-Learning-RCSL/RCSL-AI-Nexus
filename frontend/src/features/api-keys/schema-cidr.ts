import { z } from 'zod';

const CIDR_PATTERN = /^([0-9.]+|[0-9a-fA-F:]+)\/\d{1,3}$/;

export function parseCidrText(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export const cidrTextSchema = z
  .string()
  .refine(
    (text) => parseCidrText(text).every((entry) => CIDR_PATTERN.test(entry)),
    'Expected addresses with a prefix, for example 203.0.113.0/24.',
  );
