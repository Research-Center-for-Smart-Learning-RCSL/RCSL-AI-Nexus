import { api } from '@/lib/api-client';
import {
  downloadJobSchema,
  modelListSchema,
  modelSchema,
  nodeListSchema,
  type CreateModelInput,
  type DownloadJob,
  type Model,
  type Node,
  type UpdateModelInput,
} from '@/features/models/schema';

const BASE = '/models';

/**
 * Responses are parsed rather than cast. Generated types (frontend.md section
 * 4) catch drift at compile time; parsing catches a backend that is newer than
 * the last `pnpm sync-types` run.
 */
export async function listModels(): Promise<Model[]> {
  return modelListSchema.parse(await api.get<unknown>(BASE));
}

export async function getModel(id: string): Promise<Model> {
  return modelSchema.parse(await api.get<unknown>(`${BASE}/${id}`));
}

export async function createModel(input: CreateModelInput): Promise<Model> {
  return modelSchema.parse(await api.post<unknown>(BASE, input));
}

export async function updateModel(
  id: string,
  input: UpdateModelInput,
): Promise<Model> {
  return modelSchema.parse(await api.patch<unknown>(`${BASE}/${id}`, input));
}

export async function deleteModel(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/${id}`);
}

/** Refused server-side when the memory budget would be exceeded. */
export async function loadModel(id: string): Promise<void> {
  await api.post<void>(`${BASE}/${id}/load`);
}

export async function unloadModel(id: string): Promise<void> {
  await api.post<void>(`${BASE}/${id}/unload`);
}

export async function startDownload(id: string): Promise<DownloadJob> {
  return downloadJobSchema.parse(await api.post<unknown>(`${BASE}/${id}/download`));
}

export async function getDownloadJob(jobId: string): Promise<DownloadJob> {
  return downloadJobSchema.parse(
    await api.get<unknown>(`/download-jobs/${jobId}`),
  );
}

/**
 * The node list, for the model form's node dropdown. Full node management
 * (register, edit, delete, health check) lives in `features/nodes`, which
 * shipped in Phase 2 with the SSRF guard (security.md section 7.2).
 */
export async function listNodes(): Promise<Node[]> {
  return nodeListSchema.parse(await api.get<unknown>('/nodes'));
}
