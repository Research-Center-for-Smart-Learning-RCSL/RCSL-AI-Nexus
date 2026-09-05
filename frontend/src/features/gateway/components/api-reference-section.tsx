import type { ReactNode } from 'react';

import {
  apiReferenceHeadingId,
  type ApiReferenceSection,
} from './api-reference-section-catalogue';

export type ApiReferenceSectionProps = {
  section: ApiReferenceSection;
};

export function ApiReferenceSectionLayout({
  section,
  children,
}: ApiReferenceSectionProps & { children: ReactNode }) {
  const headingId = apiReferenceHeadingId(section.id);

  return (
    <section
      id={section.id}
      aria-labelledby={headingId}
      data-api-reference-section={section.renderKey}
      className="scroll-mt-4 space-y-3"
    >
      <h2
        id={headingId}
        tabIndex={-1}
        className="font-heading text-base font-semibold outline-none focus:outline-2 focus:outline-solid focus:outline-offset-4 focus:outline-ring"
      >
        {typeof section.title === 'string'
          ? section.title
          : section.title.map((part, index) =>
              'code' in part && part.code ? (
                <code key={`${part.text}-${index}`}>{part.text}</code>
              ) : (
                part.text
              ),
            )}
      </h2>
      {children}
    </section>
  );
}
