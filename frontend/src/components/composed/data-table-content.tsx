'use client';

import type { Dispatch, ReactNode, SetStateAction } from 'react';
import { flexRender, type Table as TableModel } from '@tanstack/react-table';
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState } from '@/components/composed/empty-state';

type DataTableContentProps<TData> = {
  table: TableModel<TData>;
  isLoading: boolean;
  globalFilter: string;
  setGlobalFilter: Dispatch<SetStateAction<string>>;
  emptyTitle: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
};

export function DataTableContent<TData>({
  table,
  isLoading,
  globalFilter,
  setGlobalFilter,
  emptyTitle,
  emptyDescription,
  emptyAction,
}: DataTableContentProps<TData>) {
  const rows = table.getRowModel().rows;
  return (
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
  );
}
