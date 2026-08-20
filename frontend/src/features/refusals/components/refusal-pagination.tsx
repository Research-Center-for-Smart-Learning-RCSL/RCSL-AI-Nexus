import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';

export function RefusalPagination({
  offset,
  pageSize,
  to,
  total,
  isFetching,
  turnTo,
}: {
  offset: number;
  pageSize: number;
  to: number;
  total: number;
  isFetching: boolean;
  turnTo: (offset: number) => void;
}) {
  return (
    <div className="flex items-center justify-end gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={() => turnTo(Math.max(0, offset - pageSize))}
        disabled={offset === 0 || isFetching}
        aria-label="Previous page"
      >
        <ChevronLeftIcon className="size-4" />
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={() => turnTo(offset + pageSize)}
        disabled={to >= total || isFetching}
        aria-label="Next page"
      >
        <ChevronRightIcon className="size-4" />
      </Button>
    </div>
  );
}
