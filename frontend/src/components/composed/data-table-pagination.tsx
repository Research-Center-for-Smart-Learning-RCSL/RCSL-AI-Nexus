'use client';

import type { Table } from '@tanstack/react-table';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Row count first, page controls after.
 *
 * "Page 2 of 7" says where the reader is and not how much there is, which is
 * the question an operator actually arrives with — whether the eleven rows in
 * front of them are the whole audit log or the first screen of nine hundred.
 * The count is therefore shown whether or not there is a second page.
 *
 * **It says "match" whenever a filter is set, even when the filter matched
 * everything.** A search that matched all 137 rows and no search at all are
 * different states, and rendering both as a bare "137 rows" makes an active
 * filter invisible at exactly the moment it looks like it did nothing.
 *
 * `showRowCount` is off for a table that pages on the server. There the rows
 * this component can see are one page of them, so its total would be the page
 * size sitting directly above the screen's own "1–25 of 137" — two counters
 * disagreeing about the same table.
 */
export function DataTablePagination<TData>({
  table,
  showRowCount = true,
}: {
  table: Table<TData>;
  showRowCount?: boolean;
}) {
  const filtered = table.getFilteredRowModel().rows.length;
  const total = table.getCoreRowModel().rows.length;
  const pages = table.getPageCount();
  const filtering = Boolean(table.getState().globalFilter);

  if (total === 0) return null;
  if (!showRowCount && pages <= 1) return null;

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 text-sm text-muted-foreground',
        showRowCount ? 'justify-between' : 'justify-end',
      )}
    >
      {showRowCount ? (
        <span aria-live="polite" className="tabular-nums">
          {filtering
            ? `${filtered.toLocaleString()} of ${total.toLocaleString()} rows match`
            : `${total.toLocaleString()} ${total === 1 ? 'row' : 'rows'}`}
        </span>
      ) : null}
      {pages > 1 ? (
        <div className="flex items-center gap-2">
          <span className="tabular-nums">
            Page {table.getState().pagination.pageIndex + 1} of {pages}
          </span>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Previous page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronLeftIcon />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Next page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronRightIcon />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
