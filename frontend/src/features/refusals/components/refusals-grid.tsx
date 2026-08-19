'use client';

import type { Dispatch, SetStateAction } from 'react';
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/composed/empty-state';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { describeAccount, type AccountQuery } from '@/features/refusals/account';
import { remedyFor, type Refusal } from '@/features/refusals/schema';
import type { User } from '@/features/users/schema';
import { cn } from '@/lib/utils';
import { wrapTooltip } from '@/lib/wrap-tooltip';

import { CopyRefusal, RefusalFigures, statusTone, Tick } from './refusal-cells';
import { NOTHING } from './use-refusals-table-state';

type RefusalsGridProps = {
  columns: string[];
  isLoading: boolean;
  entries: Refusal[];
  filtered: boolean;
  onScreenSummary: string | undefined;
  requestId: string;
  allPicked: boolean;
  pickedCount: number;
  setSelected: Dispatch<SetStateAction<ReadonlySet<string>>>;
  showAccount: boolean;
  accounts: Map<string, User> | undefined;
  opened: ReadonlySet<string>;
  selected: ReadonlySet<string>;
  toggleSelected: (id: string) => void;
  toggleOpened: (id: string) => void;
  setAccount: (value: string) => void;
  setPinnedAccount: (value: AccountQuery | null) => void;
};

export function RefusalsGrid({
  columns: COLUMNS,
  isLoading,
  entries,
  filtered,
  onScreenSummary,
  requestId,
  allPicked,
  pickedCount,
  setSelected,
  showAccount,
  accounts,
  opened,
  selected,
  toggleSelected,
  toggleOpened,
  setAccount,
  setPinnedAccount,
}: RefusalsGridProps) {
  return (
<div className="rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c, i) => (
                <TableHead key={c || `control-${i}`} className={i === 0 ? 'w-8' : undefined}>
                  {i === 0 ? (
                    // Every row on this page, and nothing beyond it: a tick
                    // here cannot reach the forty-nine rows on the next one,
                    // because copying works from what was fetched. Saying
                    // "on this page" is the whole of the promise.
                    <Tick
                      checked={allPicked}
                      indeterminate={pickedCount > 0 && !allPicked}
                      disabled={entries.length === 0}
                      onChange={() =>
                        setSelected(allPicked ? NOTHING : new Set(entries.map((e) => e.id)))
                      }
                      label={
                        allPicked
                          ? 'Clear the selection'
                          : 'Select every refusal on this page'
                      }
                    />
                  ) : (
                    c
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {COLUMNS.map((c, j) => (
                    <TableCell key={c || `cell-${j}`}>
                      <div className="h-4 w-full animate-pulse rounded bg-muted" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : entries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} className="p-0">
                  <EmptyState
                    title={filtered ? 'Nothing matched' : 'Nothing has been refused'}
                    description={
                      filtered
                        ? // Says which filters were in force, because there
                          // are now five of them and "nothing matched" does
                          // not say which one to loosen. The request-id advice
                          // is only offered when a request id is what was
                          // asked for: as an unconditional sentence it named
                          // the wrong cause every time the filter was a window
                          // or a name.
                          `Nothing matches these filters: ${onScreenSummary}.` +
                          (requestId.trim()
                            ? ' The request id has to be the whole value from the error — the one in the `request_id` field of the response body, or in the X-Request-Id header.'
                            : '')
                        : 'Refusals appear here as they happen: a request over the context ceiling, a key using a capability it was not issued, an expiry beyond the maximum. An empty list means nothing has been turned away in the retention window.'
                    }
                    className="border-0"
                  />
                </TableCell>
              </TableRow>
            ) : (
              entries.map((entry) => {
                const remedy = remedyFor(entry.code);
                const account_ = describeAccount(entry, accounts);
                const isOpen = opened.has(entry.id);
                return (
                  <TableRow key={entry.id} className="align-top">
                    <TableCell className="pt-4">
                      <Tick
                        checked={selected.has(entry.id)}
                        onChange={() => toggleSelected(entry.id)}
                        // Named by its code and its time, because a page of
                        // fifty "select this refusal" boxes is fifty
                        // indistinguishable controls to anybody listening to
                        // it rather than looking at it.
                        label={`Select the ${entry.code} refusal from ${new Date(entry.at).toLocaleString()}`}
                      />
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">
                      {new Date(entry.at).toLocaleString()}
                    </TableCell>
                    {showAccount ? (
                      <TableCell title={wrapTooltip(account_.title)}>
                        {/* A name first, the handle under it. Neither of the
                            two values the row stores is a name a person
                            recognises — the account id is a uuid and
                            `actor_display` is the *credential's* display, which
                            for a gateway caller is the key handle — so the name
                            is resolved against the accounts this reader can
                            already list. The id stays visible because it is
                            what an audit quotes, and the hover carries
                            everything including what the platform recorded at
                            the time. */}
                        <button
                          type="button"
                          className="block max-w-[13rem] text-left underline-offset-2 hover:underline"
                          // The box says who, and the filter is the id this
                          // row already carries — pinned rather than parsed
                          // back out of the text, because an exact filter is
                          // the only one that also catches this account's
                          // gateway refusals, whose recorded name is the key's
                          // handle rather than theirs.
                          onClick={() => {
                            setAccount(account_.name);
                            setPinnedAccount({ actor_id: entry.actor_id });
                          }}
                        >
                          <span className="block truncate text-sm">{account_.name}</span>
                          <span className="block truncate font-mono text-[0.7rem] text-muted-foreground">
                            {account_.id}
                          </span>
                        </button>
                      </TableCell>
                    ) : null}
                    <TableCell title={entry.code}>
                      <Badge variant={statusTone(entry.status)} className="font-mono text-xs">
                        {entry.status}
                      </Badge>
                      {/* Capped even though the column is `String(64)`: sixty
                          four characters of code is still three times this
                          column's share of the table. */}
                      <div className="mt-1 max-w-[11rem] truncate font-mono text-xs text-muted-foreground">
                        {entry.code}
                      </div>
                    </TableCell>
                    {/* The message the caller actually received, first. This
                        screen exists because the sentence people were given was
                        the only thing they had, and twice it named the wrong
                        subject; showing it beside the figures is what lets
                        somebody tell those two failures apart. */}
                    {/* Every cap on this screen constrains a block *inside*
                        the cell rather than the cell itself. `max-width` on a
                        `td` is advisory under the automatic table layout these
                        tables use — the column is sized from its content first
                        — so a cap there is ignored and one long value widens
                        the whole table until it runs past the right edge. The
                        audit log found this the same way and its comment says
                        so; this table repeated it in four columns. */}
                    <TableCell>
                      <div className="max-w-[34rem] space-y-1">
                        <p
                          className={cn('text-sm break-words', isOpen ? '' : 'line-clamp-2')}
                          title={wrapTooltip(entry.message)}
                        >
                          {entry.message}
                        </p>
                        {/* The figures stay visible collapsed: they are short,
                            they are what a reader scans for, and they are the
                            part that differs between two refusals carrying the
                            same sentence. */}
                        <RefusalFigures figures={entry.figures} expanded={isOpen} />
                        {/* The remedy is advice per *code*, not per row, so a
                            page of fifty 413s would print the same paragraph
                            fifty times. It belongs to the row somebody opened. */}
                        {remedy && isOpen ? (
                          <p className="text-xs break-words text-muted-foreground">{remedy}</p>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell
                      className="text-xs text-muted-foreground"
                      title={wrapTooltip(`${entry.method} ${entry.path}`)}
                    >
                      {/* `path` is an unbounded column: a query-shaped route or
                          a long collection name would otherwise set this
                          column's width for every row. */}
                      <div className="max-w-[16rem] truncate font-mono">
                        {entry.method} {entry.path}
                      </div>
                      <div className="mt-1">{entry.surface}</div>
                    </TableCell>
                    <TableCell
                      className="font-mono text-xs text-muted-foreground"
                      title={wrapTooltip(
                        [entry.request_id, entry.api_key_id && `key ${entry.api_key_id}`]
                          .filter(Boolean)
                          .join('\n'),
                      )}
                    >
                      {/* The ellipsis is what tells anyone there is more to
                          hover over, which is the whole reason these carry a
                          title as well as a cap. */}
                      <div className="max-w-[12rem] truncate">{entry.request_id ?? '—'}</div>
                      {entry.api_key_id ? (
                        <div className="mt-1 max-w-[12rem] truncate">key {entry.api_key_id}</div>
                      ) : null}
                    </TableCell>
                    {/* The paste is the point of this column: a refusal is
                        usually read in order to send it to somebody who can
                        act on it, and selecting the rendered row loses the
                        composition's structure and truncates the id. */}
                    <TableCell className="text-right whitespace-nowrap">
                      <Button
                        size="sm"
                        variant="ghost"
                        type="button"
                        aria-expanded={isOpen}
                        aria-label={
                          isOpen ? 'Show less of this refusal' : 'Show all of this refusal'
                        }
                        onClick={() => toggleOpened(entry.id)}
                      >
                        {isOpen ? (
                          <ChevronUpIcon className="size-4" />
                        ) : (
                          <ChevronDownIcon className="size-4" />
                        )}
                      </Button>
                      <CopyRefusal refusal={entry} account={account_.name} />
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
  );
}
