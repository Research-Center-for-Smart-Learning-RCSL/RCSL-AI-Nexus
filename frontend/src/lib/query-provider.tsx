'use client';

import { useState, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { isUnauthorized } from '@/lib/api-client';

/**
 * All server state goes through TanStack Query (frontend.md section 5). The
 * client is created inside a component rather than at module scope so that a
 * server render never shares a cache between requests.
 */
export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // A 401 is an answer. Retrying it only delays the redirect and
            // burns rate-limit budget on the login endpoint.
            retry: (failureCount, error) =>
              !isUnauthorized(error) && failureCount < 2,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
