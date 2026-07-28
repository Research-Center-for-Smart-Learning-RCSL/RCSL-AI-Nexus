'use client';

import Link from 'next/link';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { CodeBlock } from '@/components/composed/code-block';
import { integrationSnippets } from '@/features/gateway/schema';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';

/**
 * How to actually use the key that was just issued.
 *
 * This exists because the journey used to end at the clipboard. The holder had
 * a secret and no endpoint, no header, and no way to learn that the `model`
 * field takes a capability rather than a model name — `/openapi.json` is
 * disabled on the gateway in production, so nothing on the wire would have
 * told them either.
 */
export function IntegrationSnippet({
  plaintext,
  capability,
}: {
  plaintext: string;
  /** The capability the key was issued for, so the sample runs as shown. */
  capability: string;
}) {
  const { data, isLoading, error } = useGatewayInfo();

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Loading the endpoint...</p>
    );
  }

  // Deliberately not a blocking error. The key is on screen and unrecoverable;
  // failing to fetch a base URL must not take the dialog down with it.
  if (error || !data) {
    return (
      <p className="text-sm text-muted-foreground">
        The endpoint could not be loaded. See{' '}
        <Link href="/api-docs" className="underline">
          the API documentation
        </Link>{' '}
        for how to use this key.
      </p>
    );
  }

  const snippets = integrationSnippets({
    baseUrl: data.base_url,
    plaintext,
    capability,
  });

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <p className="font-medium">Using it</p>
        <p className="text-sm text-muted-foreground">
          The key is already filled in below. <code>model</code> takes a{' '}
          <strong>capability</strong>, not a model name — routing decides what
          serves it, which is what lets models change without touching your
          code. See{' '}
          <Link href="/api-docs" className="underline">
            the API documentation
          </Link>
          .
        </p>
      </div>

      <Tabs defaultValue={snippets[0].label}>
        <TabsList>
          {snippets.map((snippet) => (
            <TabsTrigger key={snippet.label} value={snippet.label}>
              {snippet.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {snippets.map((snippet) => (
          <TabsContent key={snippet.label} value={snippet.label}>
            <CodeBlock
              code={snippet.code}
              label={`Copy the ${snippet.label} example`}
            />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
