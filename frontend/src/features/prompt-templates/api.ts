import { api } from '@/lib/api-client';
import {
  promptTemplateListSchema,
  promptTemplateSchema,
  type PromptTemplate,
  type PromptTemplateFormValues,
} from '@/features/prompt-templates/schema';

const BASE = '/prompt-templates';

export async function listPromptTemplates(): Promise<PromptTemplate[]> {
  return promptTemplateListSchema.parse(await api.get<unknown>(BASE));
}

export async function createPromptTemplate(
  input: PromptTemplateFormValues,
): Promise<PromptTemplate> {
  return promptTemplateSchema.parse(await api.post<unknown>(BASE, input));
}

/** `PATCH`, so editing a description does not require resending the body. */
export async function updatePromptTemplate(
  id: string,
  input: Partial<PromptTemplateFormValues>,
): Promise<PromptTemplate> {
  return promptTemplateSchema.parse(await api.patch<unknown>(`${BASE}/${id}`, input));
}

/**
 * A conversation already sent is unaffected: the template was copied into that
 * request's messages. The next request naming it is refused with a 404 rather
 * than served without it.
 */
export async function deletePromptTemplate(id: string): Promise<void> {
  await api.delete<void>(`${BASE}/${id}`);
}
