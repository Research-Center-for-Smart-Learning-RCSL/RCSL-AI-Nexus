import Link from 'next/link';
import { CompassIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/composed/empty-state';

/**
 * Sends people to Chat rather than to `/`, because the index is the dashboard
 * and that route is admin-only: a `user` who mistypes a URL would otherwise be
 * offered a link that bounces them straight back out again.
 */
export default function NotFound() {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <EmptyState
        icon={<CompassIcon className="size-6" />}
        title="No such screen"
        description="The address does not match any page in the management UI. It may have been a stale bookmark."
        action={
          // An anchor, so it must not claim native button semantics.
          <Button
            variant="outline"
            size="sm"
            nativeButton={false}
            render={<Link href="/chat" />}
          >
            Go to Chat
          </Button>
        }
        className="max-w-md"
      />
    </div>
  );
}
