'use client';

import { useState } from 'react';
import { SearchIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useSearchKnowledge } from '@/features/knowledge/hooks/use-knowledge';

export type SearchPanelProps = {
  collectionId: string | undefined;
};

/**
 * What the index actually returns for a question, which is the only way an
 * operator can tell a knowledge base that works from one that merely has
 * documents in it.
 */
export function SearchPanel({ collectionId }: SearchPanelProps) {
  const [query, setQuery] = useState('');
  const search = useSearchKnowledge();

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!query.trim()) return;
          search.mutate({ query, collectionId });
        }}
      >
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask what the documents say"
          maxLength={2000}
        />
        <Button type="submit" disabled={search.isPending || !query.trim()}>
          <SearchIcon />
          {search.isPending ? 'Searching…' : 'Search'}
        </Button>
      </form>

      {search.data?.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing matched. A document has to finish indexing before it can be
          found, and the <code>embedding</code> capability needs a routing
          policy.
        </p>
      ) : null}

      <ul className="space-y-2">
        {search.data?.map((passage) => (
          <li
            key={`${passage.document_id}:${passage.index}`}
            className="rounded-md border p-3"
          >
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span className="font-mono">
                {passage.document_id.slice(0, 8)} · passage {passage.index}
              </span>
              <span>{passage.score.toFixed(3)}</span>
            </div>
            {/*
              `whitespace-pre-wrap` on plain text, deliberately not the markdown
              renderer the chat uses. A passage is quoted from a file somebody
              uploaded, so it is displayed as characters and never interpreted
              as markup (security.md 7.3, frontend.md 7).
            */}
            <p className="mt-2 whitespace-pre-wrap text-sm">{passage.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
