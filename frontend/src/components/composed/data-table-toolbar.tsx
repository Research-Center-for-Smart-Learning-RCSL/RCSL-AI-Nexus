'use client';

import type { Dispatch, ReactNode, RefObject, SetStateAction } from 'react';
import type { Table } from '@tanstack/react-table';
import { SettingsIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export function columnLabel(header: unknown, id: string): string {
  if (typeof header === 'string' && header.length > 0) return header;
  const words = id.replace(/[_-]+/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type DataTableToolbarProps<TData> = {
  table: Table<TData>;
  searchPlaceholder?: string;
  toolbar?: ReactNode;
  globalFilter: string;
  setGlobalFilter: Dispatch<SetStateAction<string>>;
  showColumnMenu: boolean;
  setShowColumnMenu: Dispatch<SetStateAction<boolean>>;
  columnMenuRef: RefObject<HTMLDivElement | null>;
};

export function DataTableToolbar<TData>({
  table,
  searchPlaceholder,
  toolbar,
  globalFilter,
  setGlobalFilter,
  showColumnMenu,
  setShowColumnMenu,
  columnMenuRef,
}: DataTableToolbarProps<TData>) {
  if (!searchPlaceholder && !toolbar) return null;
  return (
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
  );
}
