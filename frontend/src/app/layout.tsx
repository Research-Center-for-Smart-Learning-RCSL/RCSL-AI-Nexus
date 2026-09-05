import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';

import './globals.css';
import { QueryProvider } from '@/lib/query-provider';
import { SessionProvider } from '@/lib/session';
import { ThemeProvider } from '@/lib/theme-provider';
import { Toaster } from '@/components/ui/sonner';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  title: 'RCSL AI Nexus',
  description: 'Management UI for the RCSL AI Nexus platform.',
};

/**
 * Shell only. Server components never call the admin API: doing so would put
 * the Next.js server on the authentication path and force it to forward session
 * cookies and Tailscale headers, duplicating trust logic the backend owns
 * (frontend.md section 1). All data fetching happens in client components.
 *
 * SessionProvider sits here rather than in the dashboard group because the auth
 * screens also need to know when a session already exists.
 */
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full overflow-hidden antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <ThemeProvider>
          <QueryProvider>
            <SessionProvider>{children}</SessionProvider>
            <Toaster />
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
