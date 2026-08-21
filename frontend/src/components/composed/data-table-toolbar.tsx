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
  const hideable = table.getAllLeafColumns().filter((column) => column.getCanHide());

  // Hiding columns is a property of the table, not of whether that table also
  // offers a search box. Returning null on `!searchPlaceholder && !toolbar`
  // withdrew the control from exactly the tables whose columns are widest, so
  // the same table offered different capabilities on different screens for a
  // reason no reader could see.
  if (!searchPlaceholder && !toolbar && hideable.length === 0) return null;

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
        {hideable.length > 0 ? (
          <div className="relative" ref={columnMenuRef}>
            <Button
              variant="outline"
              size="sm"
              // A disclosure, not a menu. The panel holds checkboxes, which are
              // form controls with their own keyboard behaviour; claiming
              // `haspopup="menu"` promised menu semantics the contents do not
              // implement and cannot without losing the checkbox role.
              aria-expanded={showColumnMenu}
              aria-controls="data-table-columns"
              onClick={() => setShowColumnMenu((open) => !open)}
            >
              <SettingsIcon />
              Columns
            </Button>
            {showColumnMenu ? (
              <div
                id="data-table-columns"
                role="group"
                aria-label="Columns to show"
                className="absolute right-0 z-50 mt-1 w-48 rounded-lg bg-popover p-1 text-popover-foreground ring-1 ring-foreground/10"
              >
                {hideable.map((column) => (
                  <label
                    key={column.id}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent"
                  >
                    <input
                      type="checkbox"
                      className="size-4 accent-primary"
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
        ) : null}
      </div>
    </div>
  );
}
