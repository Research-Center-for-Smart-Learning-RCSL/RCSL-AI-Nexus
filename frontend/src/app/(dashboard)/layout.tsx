import type { ReactNode } from 'react';

import { AppShellWithAssistant } from '@/components/composed/app-shell';

export default function DashboardLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <AppShellWithAssistant>{children}</AppShellWithAssistant>;
}
