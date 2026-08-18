import { api } from '@/lib/api-client';
import { refusalPageSchema, type RefusalFilters, type RefusalPage } from '@/features/refusals/schema';

const BASE = '/refusals';

export async function listRefusals(filters: RefusalFilters): Promise<RefusalPage> {
  return refusalPageSchema.parse(
    await api.get<unknown>(BASE, {
      query: {
        code: filters.code || undefined,
        request_id: filters.request_id || undefined,
        actor_id: filters.actor_id || undefined,
        actor_display: filters.actor_display || undefined,
        since: filters.since || undefined,
        until: filters.until || undefined,
        limit: filters.limit,
        offset: filters.offset,
      },
    }),
  );
}
