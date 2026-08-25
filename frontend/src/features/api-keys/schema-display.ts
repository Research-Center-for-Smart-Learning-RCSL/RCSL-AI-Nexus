import type { ApiKey } from './schema-response';

export const DEFAULT_EXPIRY_DAYS = 90;

export function expiryFromToday(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

export function defaultExpiry(): string {
  return expiryFromToday(DEFAULT_EXPIRY_DAYS);
}

/** Quick-pick shortcuts shown beside the date field. The 3650-day ceiling
 * (`api_key_max_lifetime_days`, see security.md §4.2) is what "10 years"
 * lands on exactly. */
export const EXPIRY_PRESETS = [
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
  { label: '3 years', days: 365 * 3 },
  { label: '10 years', days: 3650 },
] as const;

export function keyStatus(key: ApiKey): 'active' | 'revoked' | 'expired' {
  if (key.revoked_at) return 'revoked';
  if (new Date(key.expires_at).getTime() <= Date.now()) return 'expired';
  return 'active';
}

export function toDateInput(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toISOString().slice(0, 10);
}

export function canManageKey(
  key: ApiKey,
  viewer: { id: string | null; mayWriteAny: boolean; mayWriteOwn: boolean },
): boolean {
  if (viewer.mayWriteAny) return true;
  return viewer.mayWriteOwn && viewer.id !== null && key.owner_id === viewer.id;
}
