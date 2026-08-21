'use client';

import type { Table } from '@tanstack/react-table';
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';

/**
 * Row count first, page controls after.
 *
 * "Page 2 of 7" says where the reader is and not how much there is, which is
 * the question an operator actually arrives with — whether the eleven rows in
 * front of them are the whole audit log or the first screen of nine hundred.
 * The count is therefore shown whether or not there is a second page, and it
 * distinguishes a filtered subset from the whole set, because a search that
 * matched almost everything looks identical to one that matched everything.
 */
export function DataTablePagination<TData>({ table }: { table: Table<TData> }) {
  const filtered = table.getFilteredRowModel().rows.length;
  const total = table.getCoreRowModel().rows.length;
  const pages = table.getPageCount();

  if (total === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
      <span aria-live="polite" className="tabular-nums">
        {filtered === total
          ? `${total.toLocaleString()} ${total === 1 ? 'row' : 'rows'}`
          : `${filtered.toLocaleString()} of ${total.toLocaleString()} rows match`}
      </span>
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
