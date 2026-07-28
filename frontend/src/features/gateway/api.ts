import { api } from '@/lib/api-client';
import {
  gatewayInfoSchema,
  type GatewayInfo,
} from '@/features/gateway/schema';

export async function readGatewayInfo(): Promise<GatewayInfo> {
  return gatewayInfoSchema.parse(await api.get<unknown>('/gateway'));
}
