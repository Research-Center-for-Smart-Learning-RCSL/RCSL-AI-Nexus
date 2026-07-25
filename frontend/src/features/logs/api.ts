import { api } from '@/lib/api-client';
import { auditLogSchema, type AuditLogPage, type LogFilters } from '@/features/logs/schema';

export async function getLogs(filters: LogFilters): Promise<AuditLogPage> {
  return auditLogSchema.parse(
    await api.get<unknown>('/logs', {
      query: {
        action: filters.action || undefined,
        outcome: filters.outcome || undefined,
        limit: filters.limit,
        offset: filters.offset,
      },
    }),
  );
}
