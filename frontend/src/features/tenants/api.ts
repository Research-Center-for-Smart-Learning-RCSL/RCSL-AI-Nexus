import { api } from '@/lib/api-client';
import {
  createTenantResponseSchema,
  tenantListSchema,
  type CreateTenantInput,
  type CreateTenantResponse,
  type Tenant,
} from '@/features/tenants/schema';

const BASE = '/tenants';

export async function listTenants(): Promise<Tenant[]> {
  return tenantListSchema.parse(await api.get<unknown>(BASE));
}

export async function createTenant(
  input: CreateTenantInput,
): Promise<CreateTenantResponse> {
  return createTenantResponseSchema.parse(await api.post<unknown>(BASE, input));
}
