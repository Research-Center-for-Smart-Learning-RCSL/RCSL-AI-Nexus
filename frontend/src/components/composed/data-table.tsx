'use client';

/**
 * The single table used by every module (frontend.md section 2). It owns sort,
 * global filter, pagination and column visibility so that eleven modules do not
 * each invent their own, and so that loading, empty and error rendering stays
 * consistent (section 5).
 */

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
} from '@tanstack/react-table';
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  SettingsIcon,
} from 'lucide-react';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState } from '@/components/composed/empty-state';
import { ErrorState } from '@/components/composed/error-state';

/**
 * What to call a column in the visibility menu.
 *
 * The menu listed `column.id`, so it offered `expires_at`, `cidrs` and
 * `passages` while the header above the same column read Expires, Sources and
 * Passages. A string header is the label the operator already knows; anything
 * else (a component, or no header at all) falls back to the id with its
 * separators turned back into spaces.
 */
export function columnLabel(header: unknown, id: string): string {
  if (typeof header === 'string' && header.length > 0) return header;
  const words = id.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export type DataTableProps<TData, TValue> = {
  columns: ColumnDef<TData, TValue>[];
  data: TData[] | undefined;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  /** Hides the search box when omitted. */
  searchPlaceholder?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  /** Extra controls rendered next to the search box, typically a create button. */
  toolbar?: ReactNode;
  pageSize?: number;
  getRowId?: (row: TData, index: number) => string;
  className?: string;
};

export function DataTable<TData, TValue>({
  columns,
  data,
  isLoading = false,
  error,
  onRetry,
  searchPlaceholder,
  emptyTitle = 'Nothing here yet',
  emptyDescription,
  emptyAction,
  toolbar,
  pageSize = 20,
  getRowId,
  className,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [showColumnMenu, setShowColumnMenu] = useState(false);
  const columnMenuRef = useRef<HTMLDivElement | null>(null);

  // Hand-rolled, unlike the Select and Dialog next to it, so it had none of the
  // dismissal behaviour those bring: clicking away left it open over the table
  // and Escape did nothing. Both are what anyone who has used the rest of this
  // UI already expects.
  useEffect(() => {
    if (!showColumnMenu) return;

    function onPointerDown(event: PointerEvent) {
      const root = columnMenuRef.current;
      if (root && !root.contains(event.target as Node)) setShowColumnMenu(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setShowColumnMenu(false);
    }

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [showColumnMenu]);

  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting, globalFilter, columnVisibility },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  if (error) {
    return <ErrorState error={error} onRetry={onRetry} className={className} />;
  }

  const rows = table.getRowModel().rows;
  const hasToolbar = Boolean(searchPlaceholder || toolbar);

  return (
    <div data-slot="data-table" className={cn('space-y-3', className)}>
      {hasToolbar ? (
        <div className="flex flex-wrap items-center gap-2">
          {searchPlaceholder ? (
            <Input
              value={globalFilter}
              onChange={(event) => setGlobalFilter(event.target.value)}
              placeholder={searchPlaceholder}
              className="max-w-xs"
              aria-label={searchPlaceholder}
            />
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {toolbar}
            <div className="relative" ref={columnMenuRef}>
              <Button
                variant="outline"
                size="sm"
                aria-expanded={showColumnMenu}
                aria-haspopup="menu"
                onClick={() => setShowColumnMenu((open) => !open)}
              >
                <SettingsIcon />
                Columns
              </Button>
              {showColumnMenu ? (
                <div className="absolute right-0 z-50 mt-1 w-48 rounded-lg bg-popover p-1 text-popover-foreground ring-1 ring-foreground/10">
                  {table
                    .getAllLeafColumns()
                    .filter((column) => column.getCanHide())
                    .map((column) => (
                      <label
                        key={column.id}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent"
                      >
                        <input
                          type="checkbox"
                          checked={column.getIsVisible()}
                          onChange={(event) =>
                            column.toggleVisibility(event.target.checked)
                          }
                        />
                        {columnLabel(column.columnDef.header, column.id)}
                      </label>
                    ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead key={header.id}>
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          className="inline-flex items-center gap-1 hover:text-foreground"
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          {sorted === 'asc' ? (
                            <ChevronUpIcon className="size-3.5" />
                          ) : sorted === 'desc' ? (
                            <ChevronDownIcon className="size-3.5" />
                          ) : null}
                        </button>
                      ) : (
                        flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 3 }).map((_, rowIndex) => (
                <TableRow key={`skeleton-${rowIndex}`}>
                  {table.getVisibleLeafColumns().map((column) => (
                    <TableCell key={column.id}>
                      <div className="h-4 w-full animate-pulse rounded bg-muted" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={table.getVisibleLeafColumns().length}
                  className="p-0"
                >
                  {/* An active search is its own reason for an empty table, and
                      not the caller's to explain: every `emptyDescription` in
                      this codebase describes an empty *dataset* ("Issue a key to
                      let an application reach the gateway"), which is a false
                      statement about a table holding rows the query did not
                      match — and the worse for being addressed to someone who
                      typed the name of a row they know exists. The caller's
                      message is restored the moment the query is cleared. */}
                  {globalFilter ? (
                    <EmptyState
                      title="No matches"
                      description={`Nothing here matches "${globalFilter}".`}
                      action={
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setGlobalFilter('')}
                        >
                          Clear search
                        </Button>
                      }
                      className="border-0"
                    />
                  ) : (
                    <EmptyState
                      title={emptyTitle}
                      description={emptyDescription}
                      action={emptyAction}
                      className="border-0"
                    />
                  )}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {table.getPageCount() > 1 ? (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          <span>
            Page {table.getState().pagination.pageIndex + 1} of{' '}
            {table.getPageCount()}
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
