import { api } from '@/lib/api-client';
import { hostStatusSchema, type HostStatus } from '@/features/host/schema';

export async function getHostStatus(): Promise<HostStatus> {
  return hostStatusSchema.parse(await api.get<unknown>('/host'));
}
