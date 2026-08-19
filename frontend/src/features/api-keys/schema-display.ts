import type { ApiKey } from './schema-response';

export const DEFAULT_EXPIRY_DAYS = 90;

export function defaultExpiry(): string {
  const date = new Date();
  date.setDate(date.getDate() + DEFAULT_EXPIRY_DAYS);
  return date.toISOString().slice(0, 10);
}

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
