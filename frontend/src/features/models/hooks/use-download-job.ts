'use client';

import { useQuery } from '@tanstack/react-query';

import { getDownloadJob } from '@/features/models/api';

/**
 * Download progress is a polling case (frontend.md section 5). Polling stops as
 * soon as the job reaches a terminal state, otherwise a finished download keeps
 * a request in flight for as long as the page is open.
 */
export function useDownloadJob(jobId: string | null) {
  return useQuery({
    queryKey: ['models', 'download-job', jobId],
    queryFn: () => getDownloadJob(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      // A job that cannot be read is as terminal as one that finished. Job
      // entries expire from the cache after a day and the endpoint then 404s,
      // and this predicate only looked at `data.state` — which is undefined on
      // an error, so it fell through to 2_000 and polled a dead id every two
      // seconds for as long as the screen stayed open. Reachable now that the
      // id survives a reload in sessionStorage.
      if (query.state.status === 'error') return false;
      const state = query.state.data?.state;
      return state === 'succeeded' || state === 'failed' ? false : 2_000;
    },
    // The id came from storage or from a mutation, so it is either right or
    // gone; retrying a 404 three times only delays saying so.
    retry: false,
  });
}
