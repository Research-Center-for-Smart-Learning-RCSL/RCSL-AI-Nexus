import { api } from '@/lib/api-client';
import {
  routingPolicyListSchema,
  routingPolicySchema,
  type RoutingPolicy,
  type SavePolicyRequest,
} from '@/features/routing-policies/schema';

const BASE = '/routing-policies';

/** Responses are parsed rather than cast, so backend drift surfaces here. */
export async function listRoutingPolicies(): Promise<RoutingPolicy[]> {
  return routingPolicyListSchema.parse(await api.get<unknown>(BASE));
}

/**
 * A capability has exactly one policy, so this is a PUT keyed by capability:
 * writing the same body twice means the same thing (routing_policies.py).
 */
export async function saveRoutingPolicy(
  capability: string,
  body: SavePolicyRequest,
): Promise<RoutingPolicy> {
  return routingPolicySchema.parse(await api.put<unknown>(`${BASE}/${capability}`, body));
}

export async function deleteRoutingPolicy(capability: string): Promise<void> {
  await api.delete<void>(`${BASE}/${capability}`);
}
