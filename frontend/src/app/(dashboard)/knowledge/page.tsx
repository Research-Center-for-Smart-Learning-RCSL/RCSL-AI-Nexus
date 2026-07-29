import type { Metadata } from 'next';

import { KnowledgeWorkspace } from '@/features/knowledge/components/knowledge-workspace';

export const metadata: Metadata = { title: 'Knowledge' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function KnowledgePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Knowledge</h1>
        <p className="text-sm text-muted-foreground">
          Documents the chat can answer from. Uploads are read by an isolated
          parser, split into passages and indexed for retrieval. Everything here
          belongs to your tenant and is not visible to any other.
        </p>
      </div>
      <KnowledgeWorkspace />
    </div>
  );
}
