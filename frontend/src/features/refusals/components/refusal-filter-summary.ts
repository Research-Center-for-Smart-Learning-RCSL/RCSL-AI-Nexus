import type { RefusalFilters } from '@/features/refusals/schema';

export function columnsFor(showAccount: boolean): string[] {
  return [
    '',
    'When',
    ...(showAccount ? ['Account'] : []),
    'Code',
    'Message to the caller',
    'Where',
    'Request',
    '',
  ];
}

export function filterSummary(
  filters: RefusalFilters,
  {
    time = (iso: string) => iso,
    account = '',
  }: { time?: (iso: string) => string; account?: string } = {},
): string | undefined {
  const parts = [
    filters.code && `code ${filters.code}`,
    filters.request_id && `request id ${filters.request_id}`,
    filters.actor_id && `account ${account || filters.actor_id}`,
    filters.actor_display &&
      `account login containing “${filters.actor_display}”`,
    filters.since && `from ${time(filters.since)}`,
    filters.until && `before ${time(filters.until)}`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(', ') : undefined;
}
