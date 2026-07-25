import { api } from '@/lib/api-client';
import {
  nodeListSchema,
  nodeSchema,
  type CreateNodeInput,
  type Node,
  type UpdateNodeInput,
} from '@/features/nodes/schema';

const BASE = '/nodes';

/**
 * Responses are parsed rather than cast, so a backend newer than the last
 * `pnpm sync-types` run surfaces as a parse failure rather than `undefined`
 * downstream (frontend.md section 4).
 */
export async function listNodes(): Promise<Node[]> {
  return nodeListSchema.parse(await api.get<unknown>(BASE));
}

export async function createNode(input: CreateNodeInput): Promise<Node> {
  return nodeSchema.parse(await api.post<unknown>(BASE, input));
}

export async function updateNode(
  id: string,
  input: UpdateNodeInput,
): Promise<Node> {
  return nodeSchema.parse(await api.patch<unknown>(`${BASE}/${id}`, input));
}

export async function deleteNode(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/${id}`);
}

/** Probe the node now and return its freshly observed status. */
export async function checkNodeHealth(id: string): Promise<Node> {
  return nodeSchema.parse(await api.post<unknown>(`${BASE}/${id}/check`));
}
