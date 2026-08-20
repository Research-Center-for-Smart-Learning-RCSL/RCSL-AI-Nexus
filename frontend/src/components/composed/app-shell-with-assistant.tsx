'use client';

import type { ReactNode } from 'react';

import { AssistantContextProvider } from '@/features/assistant/context';

import { AppShell } from './app-shell-runtime';

/** Keeps assistant context mounted across every session-gate branch. */
export function AppShellWithAssistant({ children }: { children: ReactNode }) {
  return (
    <AssistantContextProvider>
      <AppShell>{children}</AppShell>
    </AssistantContextProvider>
  );
}
