'use client';

import { useState } from 'react';
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  CopyIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
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
import { describeAccount, usersById } from '@/features/refusals/account';
import { useRefusals } from '@/features/refusals/hooks/use-refusals';
import { refusalToMarkdown, refusalsToMarkdown } from '@/features/refusals/markdown';
import { FIGURE_LABELS, remedyFor, type Refusal } from '@/features/refusals/schema';
import { useUsers } from '@/features/users/hooks/use-users';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';
import { cn } from '@/lib/utils';

const PAGE_SIZE = 50;
const BASE_COLUMNS = ['When', 'Code', 'What you were told', 'Where', 'Request', ''];
/** The account column appears only when the page may contain more than one. */
const ACCOUNT_COLUMN = 'Account';

/** 4xx is the caller's to fix and 5xx is the platform's, which is the one
 *  distinction a colour should carry here. Everything finer is the code. */
function statusTone(status: number): 'secondary' | 'destructive' {
  return status >= 500 ? 'destructive' : 'secondary';
}

function figureText(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined) return '—';
  return String(value);
}

/**
 * The figures, laid out as labelled pairs with the long one last.
 *
 * `composition` is a sentence and everything else is a number, so a uniform
 * grid would either wrap the numbers absurdly or truncate the sentence that
 * says which of three remedies applies. It is the field that ended the
 * 2026-08-17 incident, so it gets its own line — clamped to that one line
 * until the row is opened, because a page is read by scanning it.
 */
function Figures({
  figures,
  expanded,
}: {
  figures: Record<string, unknown>;
  expanded: boolean;
}) {
  const keys = Object.keys(figures);
  if (keys.length === 0) return null;
  const short = keys.filter((k) => k !== 'composition');
  const composition = figures.composition;

  return (
    <div className="mt-1 space-y-1">
      {short.length > 0 ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {short.map((key) => (
            // Capped and truncated per value, with the whole of it on the
            // hover. `available` is a list that grows with the deployment's
            // capabilities and `reason` is a sentence, so a figure is not a
            // short value by nature — and one long one here would push the
            // column past every other row's.
            <span
              key={key}
              className="inline-flex max-w-[18rem] gap-1 tabular-nums"
              title={`${FIGURE_LABELS[key] ?? key}: ${figureText(figures[key])}`}
            >
              <span className="text-muted-foreground/70">{FIGURE_LABELS[key] ?? key}:</span>
              <span className="truncate">{figureText(figures[key])}</span>
            </span>
          ))}
        </div>
      ) : null}
      {typeof composition === 'string' ? (
        // Wrapped rather than truncated: it names which of three remedies
        // applies, so it is the one long value on this screen worth reading in
        // full. `break-words` is for a single unbroken token — a path, a base64
        // blob quoted back — which would otherwise run past the cap.
        <p
          className={cn(
            'max-w-[34rem] font-mono text-[0.7rem] leading-relaxed break-words text-muted-foreground',
            expanded ? '' : 'line-clamp-1',
          )}
          title={composition}
        >
          {composition}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Copy one refusal as Markdown.
 *
 * Its own component so each row owns its own two seconds of feedback: a single
 * shared flag would light up every row in the table when one of them was
 * pressed, which reads as "all of these were copied".
 */
function CopyRefusal({ refusal, account }: { refusal: Refusal; account?: string }) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <Button
      size="sm"
      variant="ghost"
      type="button"
      aria-label={`Copy this ${refusal.code} refusal as Markdown`}
      onClick={() => void copy(refusalToMarkdown(refusal, { account }))}
    >
      {copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
      <span className="sr-only sm:not-sr-only">{copied ? 'Copied' : 'Copy'}</span>
    </Button>
  );
}


export function RefusalsTable() {
  const [requestId, setRequestId] = useState('');
  const [code, setCode] = useState('');
  const [account, setAccount] = useState('');
  const [offset, setOffset] = useState(0);
  // **Collapsed by default, because one row was four times the height of its
  // neighbours.** The stored 413 carries a 287-character message, three
  // figures, a 113-character composition and a 295-character remedy — about
  // 700 characters of prose in one cell, next to a 429 whose whole message is
  // eighteen. Capping the width fixed the table running off the right edge and
  // did nothing about that, and a page of fifty is read by scanning it.
  //
  // Per row rather than a single flag: opening one refusal to read it should
  // not re-lay-out every other row on the page.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const toggle = (id: string) =>
    setOpened((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const filters = {
    code: code.trim() || undefined,
    request_id: requestId.trim() || undefined,
    actor_id: account.trim() || undefined,
    limit: PAGE_SIZE,
    offset,
  };
  const { data, isLoading, isFetching, error, refetch } = useRefusals(filters);
  const page = useCopyToClipboard();
  // Above the early return, like every hook: the accounts are fetched only for
  // a reader who may see other people's refusals, which is exactly the set of
  // roles that also holds `user:read` — so this asks for nothing the reader
  // could not already list, and asks for nothing at all on the page every
  // account opens to see its own.
  const accounts = usersById(
    useUsers({ enabled: data?.scoped_to_self === false }).data,
  );

  if (error) {
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }

  const entries: Refusal[] = data?.entries ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const filtered = Boolean(code.trim() || requestId.trim() || account.trim());
  // Shown only when the reader may see other people's. Their own name repeated
  // down every row of their own list is a column that says nothing.
  const showAccount = Boolean(data && !data.scoped_to_self);
  const COLUMNS = showAccount
    ? [BASE_COLUMNS[0], ACCOUNT_COLUMN, ...BASE_COLUMNS.slice(1)]
    : BASE_COLUMNS;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-xs flex-1">
          <Input
            value={requestId}
            onChange={(e) => {
              setRequestId(e.target.value);
              setOffset(0);
            }}
            placeholder="Request id, e.g. req_9f2a…"
            aria-label="Find a refusal by the request id the caller was given"
          />
        </div>
        <div className="max-w-[12rem] flex-1">
          <Input
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setOffset(0);
            }}
            placeholder="Code, e.g. context_too_long"
            aria-label="Filter by error code"
          />
        </div>
        {/* Offered only to a reader who may see more than their own. For
            anybody else the server narrows to them whatever this said, so the
            control would be one that visibly does nothing. */}
        {data && !data.scoped_to_self ? (
          <div className="max-w-[14rem] flex-1">
            <Input
              value={account}
              onChange={(e) => {
                setAccount(e.target.value);
                setOffset(0);
              }}
              placeholder="Account id"
              aria-label="Show one account's refusals"
            />
          </div>
        ) : null}
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {total === 0 ? 'No refusals' : `${from}–${to} of ${total}`}
        </span>
        <Button
          size="sm"
          variant="outline"
          type="button"
          disabled={entries.length === 0}
          onClick={() =>
            void page.copy(
              refusalsToMarkdown(entries, {
                accountOf: (refusal) => describeAccount(refusal, accounts).name,
                total,
                scopedToSelf: data?.scoped_to_self ?? true,
                filter:
                  [
                    code.trim() ? `code ${code.trim()}` : null,
                    requestId.trim() ? `request id ${requestId.trim()}` : null,
                  ]
                    .filter(Boolean)
                    .join(' and ') || undefined,
                sourceUrl:
                  typeof window === 'undefined' ? undefined : window.location.href,
              }),
            )
          }
        >
          {page.copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
          {page.copied ? 'Copied' : 'Copy this page'}
        </Button>
      </div>

      {/* Said rather than implied. A reader who may see only their own is
          looking at a complete answer to a narrower question, and a page that
          quietly returns a subset of what its controls imply is the shape
          somebody mistakes for "there is nothing there". */}
      {data?.scoped_to_self ? (
        <p className="text-xs text-muted-foreground">
          Showing refusals from your own account and its API keys. Seeing
          everyone’s needs <code className="font-mono">refusal:read_all</code>.
        </p>
      ) : null}

      <div className="rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              {COLUMNS.map((c, i) => (
                <TableHead key={c || `actions-${i}`}>{c}</TableHead>
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
                        ? 'No refusal matches this. The request id has to be the whole value from the error — the one in the `request_id` field of the response body, or in the X-Request-Id header.'
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
                    <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">
                      {new Date(entry.at).toLocaleString()}
                    </TableCell>
                    {showAccount ? (
                      <TableCell title={account_.title}>
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
                          onClick={() => {
                            setAccount(entry.actor_id);
                            setOffset(0);
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
                          title={entry.message}
                        >
                          {entry.message}
                        </p>
                        {/* The figures stay visible collapsed: they are short,
                            they are what a reader scans for, and they are the
                            part that differs between two refusals carrying the
                            same sentence. */}
                        <Figures figures={entry.figures} expanded={isOpen} />
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
                      title={`${entry.method} ${entry.path}`}
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
                      title={[entry.request_id, entry.api_key_id && `key ${entry.api_key_id}`]
                        .filter(Boolean)
                        .join('\n')}
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
                        onClick={() => toggle(entry.id)}
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

      <div className="flex items-center justify-end gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || isFetching}
          aria-label="Previous page"
        >
          <ChevronLeftIcon className="size-4" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOffset(offset + PAGE_SIZE)}
          disabled={to >= total || isFetching}
          aria-label="Next page"
        >
          <ChevronRightIcon className="size-4" />
        </Button>
      </div>
    </div>
  );
}
