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
import {
  accountOptions,
  accountQuery,
  describeAccount,
  usersById,
  type AccountQuery,
} from '@/features/refusals/account';
import { useRefusals } from '@/features/refusals/hooks/use-refusals';
import { refusalToMarkdown, refusalsToMarkdown } from '@/features/refusals/markdown';
import {
  FIGURE_LABELS,
  remedyFor,
  type Refusal,
  type RefusalFilters,
} from '@/features/refusals/schema';
import { PRESETS, toInstant, toLocalInput } from '@/features/refusals/time-range';
import { useUsers } from '@/features/users/hooks/use-users';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';
import { cn } from '@/lib/utils';
import { wrapTooltip } from '@/lib/wrap-tooltip';

const PAGE_SIZE = 50;

/** No selection, as one value, so that clearing it does not make a new object
 *  every time and re-render a table of fifty rows for nothing. */
const NOTHING: ReadonlySet<string> = new Set();

/**
 * The header row.
 *
 * Two of these are blank deliberately: the tick box and the per-row buttons are
 * controls, and a heading over either would name something the cells below it
 * do not contain. They are still columns here rather than being rendered
 * around the loop, because `colSpan` on the empty state and the skeleton has to
 * count them.
 *
 * `Account` appears only when the page may hold more than one.
 */
function columnsFor(showAccount: boolean): string[] {
  return [
    '',
    'When',
    ...(showAccount ? ['Account'] : []),
    'Code',
    'What you were told',
    'Where',
    'Request',
    '',
  ];
}

/**
 * The filters in force, as a sentence for the paste's subtitle.
 *
 * **Every control, not the two this screen started with.** The account filter
 * was added without being added here, so a page copied while narrowed to one
 * person's refusals was headed "from all accounts" — which is precisely the
 * misleading excerpt `refusalsToMarkdown` was written to prevent, produced by
 * its own caller. A filter that is not named here is one the paste denies.
 *
 * The window is quoted as the instant that was sent rather than as the local
 * text in the box, because a paste is read by somebody who was not looking at
 * this screen and may not be in this timezone.
 */
function filterSummary(filters: RefusalFilters): string | undefined {
  const parts = [
    filters.code && `code ${filters.code}`,
    filters.request_id && `request id ${filters.request_id}`,
    filters.actor_id && `account ${filters.actor_id}`,
    filters.actor_display && `account name containing “${filters.actor_display}”`,
    filters.since && `from ${filters.since}`,
    filters.until && `before ${filters.until}`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(', ') : undefined;
}

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
              title={wrapTooltip(`${FIGURE_LABELS[key] ?? key}: ${figureText(figures[key])}`)}
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
          title={wrapTooltip(composition)}
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


/**
 * A tick box, native.
 *
 * `components/ui` has no checkbox and this is the first screen that wants one.
 * A native input is the whole of what is needed here — it is keyboard
 * reachable, it announces its own state, and it is the only element that can
 * be `indeterminate`, which is the state the header box spends most of its
 * time in. Adding a styled primitive to the design system for one table would
 * be a component nothing else uses and a third thing to keep in step.
 */
function Tick({
  checked,
  indeterminate = false,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: () => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <input
      type="checkbox"
      className="size-4 accent-foreground align-middle"
      checked={checked}
      // `indeterminate` is a property and not an attribute, so React cannot set
      // it from JSX and it has to be written to the node.
      ref={(node) => {
        if (node) node.indeterminate = indeterminate;
      }}
      onChange={onChange}
      disabled={disabled}
      aria-label={label}
    />
  );
}

export function RefusalsTable() {
  const [requestId, setRequestId] = useState('');
  const [code, setCode] = useState('');
  const [account, setAccount] = useState('');
  // The window, held as what `datetime-local` puts in the box rather than as
  // the instant that goes to the server. The box is the thing the reader
  // adjusts, and a round trip through UTC and back is where an hour goes
  // missing.
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [offset, setOffset] = useState(0);
  // **Which refusals somebody has ticked, to copy those and not the page.**
  // Copying was all-or-one: the whole fifty, or one row's button. An
  // investigation is usually three of them — the 413 and the two 409s that
  // followed it — and there was no way to say so.
  //
  // Ids rather than rows, like `opened` below, because the row objects are
  // replaced on every refetch and this table refetches every ten seconds.
  const [selected, setSelected] = useState<ReadonlySet<string>>(NOTHING);

  /**
   * What the account box asks the server for, beside what it says.
   *
   * A pair rather than one value because they are two different things: the
   * text is what the reader typed, and the query is which of the server's two
   * account filters that text turned out to mean — an exact id when the name
   * belongs to an account this reader can list, a substring of the recorded
   * name otherwise. `accountQuery` decides, and its doc comment says why the
   * choice matters.
   *
   * Resolved when the box changes rather than while rendering, because the
   * accounts it resolves against are fetched on the strength of the refusals
   * response, which is fetched with these filters. In an event handler that
   * circle does not exist: the accounts are whatever had loaded by the moment
   * somebody typed.
   */
  const [accountFilter, setAccountFilter] = useState<AccountQuery>({});
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

  const toggleSelected = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  /**
   * Change what the table is showing.
   *
   * Every control that changes which rows are on screen goes through here, so
   * that two things happen together: the offset returns to the first page, and
   * the selection is dropped. A tick means "this refusal, the one I am looking
   * at" — carrying it across a filter change leaves the copy button offering a
   * count of rows the reader can no longer see and cannot check.
   */
  const narrow = (apply: () => void) => {
    apply();
    setOffset(0);
    setSelected(NOTHING);
  };

  const turnTo = (next: number) => {
    setOffset(next);
    setSelected(NOTHING);
  };

  const filters: RefusalFilters = {
    code: code.trim() || undefined,
    request_id: requestId.trim() || undefined,
    ...accountFilter,
    since: toInstant(since),
    until: toInstant(until),
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
  const summary = filterSummary(filters);
  const filtered = summary !== undefined;
  // Shown only when the reader may see other people's. Their own name repeated
  // down every row of their own list is a column that says nothing.
  const showAccount = Boolean(data && !data.scoped_to_self);
  const COLUMNS = columnsFor(showAccount);
  const names = showAccount ? accountOptions(accounts) : [];

  // The rows a tick actually refers to. Intersected with what is on screen
  // rather than trusted: a refusal can leave the page under a refetch — the
  // table is append-only and reloads every ten seconds — and a count that
  // outran the rows would be a button promising to copy something it has not
  // got.
  const picked = entries.filter((entry) => selected.has(entry.id));
  const allPicked = entries.length > 0 && picked.length === entries.length;
  const copying = picked.length > 0 ? picked : entries;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-xs flex-1">
          <Input
            value={requestId}
            onChange={(e) => narrow(() => setRequestId(e.target.value))}
            placeholder="Request id, e.g. req_9f2a…"
            aria-label="Find a refusal by the request id the caller was given"
          />
        </div>
        <div className="max-w-[12rem] flex-1">
          <Input
            value={code}
            onChange={(e) => narrow(() => setCode(e.target.value))}
            placeholder="Code, e.g. context_too_long"
            aria-label="Filter by error code"
          />
        </div>
        {/* Offered only to a reader who may see more than their own. For
            anybody else the server narrows to them whatever this said, so the
            control would be one that visibly does nothing. */}
        {showAccount ? (
          <div className="max-w-[16rem] flex-1">
            {/* **It takes the name the table shows, not the uuid it stores.**
                This box wanted an account id, and nothing on this screen is
                one a person could type: the column shows a name resolved in
                the browser, and the two handles under it are a uuid and a
                credential's display. So the one filter that answers "whose?"
                could only be used by somebody who had already gone and looked
                the answer up somewhere else.

                A `datalist` rather than a select, because the set it completes
                is not the set it accepts. The completions are the accounts
                this reader can list; what a reader may also want is a deleted
                account whose name survives only on the row, an API key by its
                handle, or a uuid pasted out of an audit entry — none of which
                a closed list would let them ask for. */}
            <Input
              value={account}
              list="refusal-account-names"
              onChange={(e) =>
                narrow(() => {
                  setAccount(e.target.value);
                  setAccountFilter(accountQuery(e.target.value, accounts));
                })
              }
              placeholder="Account name, or an id"
              aria-label="Show one account's refusals, by name or by id"
            />
            <datalist id="refusal-account-names">
              {names.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </div>
        ) : null}
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {total === 0 ? 'No refusals' : `${from}–${to} of ${total}`}
        </span>
        {/* One button for both, rather than two. What it copies is whatever
            the reader has in front of them: the rows they ticked, or the page
            if they ticked none. A second permanently-disabled "copy selected"
            beside it would be a control that spends most of its life saying
            no, and the label already says which of the two this is about to
            do. */}
        <Button
          size="sm"
          variant="outline"
          type="button"
          disabled={copying.length === 0}
          onClick={() =>
            void page.copy(
              refusalsToMarkdown(copying, {
                accountOf: (refusal) => describeAccount(refusal, accounts).name,
                total,
                scopedToSelf: data?.scoped_to_self ?? true,
                picked: picked.length > 0,
                filter: summary,
                sourceUrl:
                  typeof window === 'undefined' ? undefined : window.location.href,
              }),
            )
          }
        >
          {page.copied ? <CheckIcon className="size-4" /> : <CopyIcon className="size-4" />}
          {page.copied
            ? 'Copied'
            : picked.length > 0
              ? `Copy ${picked.length} selected`
              : 'Copy this page'}
        </Button>
      </div>

      {/* **The window, which is the question this screen was built to
          answer.** Its own explanation says somebody had to ask "what happened
          at 19:16?" and had no way to; the backend has filtered on `since` and
          `until` since the table existed, and nothing ever sent either.

          The presets fill the boxes rather than replacing them, so a reader
          can see what "last hour" meant and then move it — and so the boundary
          stays put while they page through what it matched. `time-range.ts`
          says why a live window would be the wrong thing here.

          "Before" rather than "to", because the server's comparison is
          exclusive and a label that rounded that off would be wrong about
          exactly one minute — the minute somebody typed in because it is the
          one they care about. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">When</span>
        {PRESETS.map((preset) => (
          <Button
            key={preset.id}
            size="sm"
            variant="outline"
            type="button"
            onClick={() =>
              narrow(() => {
                setSince(toLocalInput(preset.from(new Date())));
                setUntil('');
              })
            }
          >
            {preset.label}
          </Button>
        ))}
        <Input
          type="datetime-local"
          className="w-auto"
          value={since}
          onChange={(e) => narrow(() => setSince(e.target.value))}
          aria-label="From, inclusive"
        />
        <Input
          type="datetime-local"
          className="w-auto"
          value={until}
          onChange={(e) => narrow(() => setUntil(e.target.value))}
          aria-label="Before, exclusive"
        />
        {since || until ? (
          <Button
            size="sm"
            variant="ghost"
            type="button"
            onClick={() =>
              narrow(() => {
                setSince('');
                setUntil('');
              })
            }
          >
            Clear
          </Button>
        ) : null}
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
                <TableHead key={c || `control-${i}`} className={i === 0 ? 'w-8' : undefined}>
                  {i === 0 ? (
                    // Every row on this page, and nothing beyond it: a tick
                    // here cannot reach the forty-nine rows on the next one,
                    // because copying works from what was fetched. Saying
                    // "on this page" is the whole of the promise.
                    <Tick
                      checked={allPicked}
                      indeterminate={picked.length > 0 && !allPicked}
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
                          `No refusal matches ${summary}.` +
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
                          onClick={() =>
                            narrow(() => {
                              setAccount(account_.name);
                              // The id, not the name that was just put in the
                              // box: this row knows exactly whose it is, and
                              // an exact filter is the one that also catches
                              // this person's gateway refusals, whose recorded
                              // name is the key's handle rather than theirs.
                              setAccountFilter({ actor_id: entry.actor_id });
                            })
                          }
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
          onClick={() => turnTo(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0 || isFetching}
          aria-label="Previous page"
        >
          <ChevronLeftIcon className="size-4" />
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => turnTo(offset + PAGE_SIZE)}
          disabled={to >= total || isFetching}
          aria-label="Next page"
        >
          <ChevronRightIcon className="size-4" />
        </Button>
      </div>
    </div>
  );
}
