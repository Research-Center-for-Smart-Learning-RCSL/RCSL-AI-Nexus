import type { Metadata } from 'next';

import { LandingPage } from '@/components/composed/landing-page';

export const metadata: Metadata = {
  title: 'RCSL AI Nexus',
  description: 'A self-hosted LLM gateway and management platform.',
};

export default function HomePage() {
  return <LandingPage />;
}
