'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
} from '@tanstack/react-table';

import { cn } from '@/lib/utils';
import { ErrorState } from '@/components/composed/error-state';

import { DataTableContent } from './data-table-content';
import { DataTablePagination } from './data-table-pagination';
import { DataTableToolbar } from './data-table-toolbar';

export { columnLabel } from './data-table-toolbar';

export type DataTableProps<TData, TValue> = {
  columns: ColumnDef<TData, TValue>[];
  data: TData[] | undefined;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  searchPlaceholder?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  toolbar?: ReactNode;
  pageSize?: number;
  /** Off where the screen pages on the server and owns the authoritative count. */
  showRowCount?: boolean;
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
  emptyTitle = 'No records',
  emptyDescription,
  emptyAction,
  toolbar,
  pageSize = 20,
  showRowCount = true,
  getRowId,
  className,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState('');
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});
  const [showColumnMenu, setShowColumnMenu] = useState(false);
  const columnMenuRef = useRef<HTMLDivElement | null>(null);

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

  return (
    <div data-slot="data-table" className={cn('space-y-3', className)}>
      <DataTableToolbar
        table={table}
        searchPlaceholder={searchPlaceholder}
        toolbar={toolbar}
        globalFilter={globalFilter}
        setGlobalFilter={setGlobalFilter}
        showColumnMenu={showColumnMenu}
        setShowColumnMenu={setShowColumnMenu}
        columnMenuRef={columnMenuRef}
      />
      <DataTableContent
        table={table}
        isLoading={isLoading}
        globalFilter={globalFilter}
        setGlobalFilter={setGlobalFilter}
        emptyTitle={emptyTitle}
        emptyDescription={emptyDescription}
        emptyAction={emptyAction}
      />
      <DataTablePagination table={table} showRowCount={showRowCount} />
    </div>
  );
}
