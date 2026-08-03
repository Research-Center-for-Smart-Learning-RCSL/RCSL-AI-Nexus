import { Spinner } from '@/components/composed/spinner';

/**
 * Rendered inside the shell, so the nav stays put while a segment resolves.
 * Most of these pages fetch from client components and never reach this, but a
 * cold navigation to a not-yet-loaded chunk does.
 */
export default function DashboardLoading() {
  return (
    <div className="flex flex-1 items-center justify-center py-16">
      <Spinner label="Loading this screen" />
    </div>
  );
}
