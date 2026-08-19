import type { AssistMessage } from '@/features/assistant/schema';

import type { AssistantTurn } from './assistant-transcript';

const MAX_TURNS = 40;

export function historyFor(
  turns: AssistantTurn[],
  question: string,
): AssistMessage[] {
  return [
    ...turns
      .filter((turn) => turn.content)
      .slice(-(MAX_TURNS - 1))
      .map((turn) => ({ role: turn.role, content: turn.content })),
    { role: 'user' as const, content: question },
  ];
}
