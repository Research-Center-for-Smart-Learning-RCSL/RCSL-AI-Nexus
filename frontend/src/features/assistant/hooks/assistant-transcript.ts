import { z } from 'zod';

import {
  assistRoleSchema,
  proposalSchema,
  type Proposal,
} from '@/features/assistant/schema';

export type AssistantTurn = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  proposal?: Proposal;
  finishReason?: string;
  error?: string;
};

const STORAGE_KEY = 'nexus:assistant:transcript';

const storedTurnSchema = z.object({
  id: z.string(),
  role: assistRoleSchema,
  content: z.string(),
  proposal: proposalSchema.optional(),
  finishReason: z.string().optional(),
  error: z.string().optional(),
});

export function loadTurns(): AssistantTurn[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((turn) => {
      const result = storedTurnSchema.safeParse(turn);
      return result.success ? [result.data] : [];
    });
  } catch {
    return [];
  }
}

export function persistTurns(turns: AssistantTurn[]): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(turns));
  } catch {
    // Storage failure must not discard the conversation currently on screen.
  }
}
