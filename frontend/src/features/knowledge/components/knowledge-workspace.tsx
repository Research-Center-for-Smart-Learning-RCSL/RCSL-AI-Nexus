'use client';

import { useState } from 'react';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CollectionList } from '@/features/knowledge/components/collection-list';
import { DocumentTable } from '@/features/knowledge/components/document-table';
import { SearchPanel } from '@/features/knowledge/components/search-panel';

/**
 * The selected collection is held here rather than in the URL.
 *
 * It is a filter over a view, not a location: the documents and the search both
 * read it, and putting a collection id in the address bar would make an
 * operator's shared link carry one tenant's identifier into a place it does not
 * belong.
 */
export function KnowledgeWorkspace() {
  const [collectionId, setCollectionId] = useState<string | undefined>(undefined);

  return (
    <div className="grid gap-6 md:grid-cols-[220px_1fr]">
      <aside>
        <CollectionList selectedId={collectionId} onSelect={setCollectionId} />
      </aside>

      <Tabs defaultValue="documents" className="min-w-0 space-y-4">
        <TabsList>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="search">Search</TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          <DocumentTable collectionId={collectionId} />
        </TabsContent>

        <TabsContent value="search">
          <SearchPanel collectionId={collectionId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
