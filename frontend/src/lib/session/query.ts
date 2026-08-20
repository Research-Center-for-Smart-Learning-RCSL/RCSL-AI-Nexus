import { api } from '@/lib/api-client';

import type { Me } from './types';

export const ME_QUERY_KEY = ['session', 'me'] as const;

export function fetchMe(): Promise<Me> {
  return api.get<Me>('/me');
}
