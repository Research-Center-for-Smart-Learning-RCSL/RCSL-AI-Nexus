export type ApiReferenceSectionDefinition = {
  id: string;
  title: string | readonly { text: string; code?: true }[];
  renderKey:
    | 'endpoint'
    | 'capabilities'
    | 'request'
    | 'tool-calling'
    | 'wire-protocols'
    | 'grounding'
    | 'model-limitations'
    | 'response'
    | 'timeouts'
    | 'errors'
    | 'limits';
};

/**
 * The authored order and public anchors of the API Reference.
 *
 * Rendering and both navigation surfaces iterate this catalogue directly. A
 * section cannot be reordered, renamed, or added without changing the same
 * record that supplies its anchor and navigation label.
 */
export const API_REFERENCE_SECTION_CATALOGUE = [
  { id: 'endpoint', title: 'Endpoint', renderKey: 'endpoint' },
  {
    id: 'capabilities',
    title: [
      { text: 'model', code: true },
      { text: ' names a capability, not a model' },
    ],
    renderKey: 'capabilities',
  },
  { id: 'request', title: 'A request', renderKey: 'request' },
  {
    id: 'tool-calling',
    title: 'Tool calling, and agent clients',
    renderKey: 'tool-calling',
  },
  {
    id: 'wire-protocols',
    title: 'Two wire protocols',
    renderKey: 'wire-protocols',
  },
  {
    id: 'grounding',
    title: 'Grounding on the knowledge base',
    renderKey: 'grounding',
  },
  {
    id: 'model-limitations',
    title: 'A measured limit of the models, not of the API',
    renderKey: 'model-limitations',
  },
  { id: 'response', title: 'What comes back', renderKey: 'response' },
  {
    id: 'timeouts',
    title: 'Timeouts, and client timeout sizing',
    renderKey: 'timeouts',
  },
  { id: 'errors', title: 'Errors', renderKey: 'errors' },
  { id: 'limits', title: 'Limits', renderKey: 'limits' },
] as const satisfies readonly ApiReferenceSectionDefinition[];

export type ApiReferenceSection =
  (typeof API_REFERENCE_SECTION_CATALOGUE)[number];
export type ApiReferenceSectionId = ApiReferenceSection['id'];

export function apiReferenceHeadingId(id: ApiReferenceSectionId): string {
  return `api-reference-${id}-heading`;
}

export function apiReferenceSectionTitleText(
  section: ApiReferenceSection,
): string {
  return typeof section.title === 'string'
    ? section.title
    : section.title.map((part) => part.text).join('');
}

export function isApiReferenceSectionId(
  value: string,
): value is ApiReferenceSectionId {
  return API_REFERENCE_SECTION_CATALOGUE.some((section) => section.id === value);
}
