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
      const state = query.state.data?.state;
      return state === 'succeeded' || state === 'failed' ? false : 2_000;
    },
  });
}
