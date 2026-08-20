'use client';

import { ErrorState } from '@/components/composed/error-state';
import { describeAccount } from '@/features/refusals/account';
import { refusalsToMarkdown } from '@/features/refusals/markdown';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';

import { columnsFor, filterSummary } from './refusal-filter-summary';
import { RefusalFilters } from './refusal-filters';
import { RefusalPagination } from './refusal-pagination';
import { RefusalTimeRange } from './refusal-time-range';
import { RefusalsGrid } from './refusals-grid';
import { PAGE_SIZE, useRefusalsTableState } from './use-refusals-table-state';

export function RefusalsTable() {
  const state = useRefusalsTableState();
  const page = useCopyToClipboard();

  if (state.error) {
    return (
      <ErrorState
        error={state.error}
        onRetry={() => void state.refetch()}
      />
    );
  }

  const from = state.total === 0 ? 0 : state.offset + 1;
  const to = Math.min(state.offset + PAGE_SIZE, state.total);
  const summary = filterSummary(state.filters);
  const onScreenSummary = filterSummary(state.filters, {
    time: (iso) => new Date(iso).toLocaleString(),
    account: state.account.trim(),
  });
  const columns = columnsFor(state.showAccount);

  function copyRows() {
    void page.copy(
      refusalsToMarkdown(state.copying, {
        accountOf: (refusal) =>
          describeAccount(refusal, state.accounts).name,
        total: state.total,
        scopedToSelf: state.data?.scoped_to_self ?? true,
        picked: state.picked.length > 0,
        filter: summary,
        sourceUrl:
          typeof window === 'undefined' ? undefined : window.location.href,
      }),
    );
  }

  return (
    <div className="space-y-3">
      <RefusalFilters
        requestId={state.requestId}
        setRequestId={state.setRequestId}
        code={state.code}
        setCode={state.setCode}
        showAccount={state.showAccount}
        account={state.account}
        setAccount={state.setAccount}
        setPinnedAccount={state.setPinnedAccount}
        names={state.names}
        total={state.total}
        from={from}
        to={to}
        copyingCount={state.copying.length}
        pickedCount={state.picked.length}
        copied={page.copied}
        onCopy={copyRows}
      />
      <RefusalTimeRange
        since={state.since}
        until={state.until}
        setSince={state.setSince}
        setUntil={state.setUntil}
      />
      {state.data?.scoped_to_self ? (
        <p className="text-xs text-muted-foreground">
          Showing refusals from this account and its API keys. Seeing everyone’s
          needs <code className="font-mono">refusal:read_all</code>.
        </p>
      ) : null}
      <RefusalsGrid
        columns={columns}
        isLoading={state.isLoading}
        entries={state.entries}
        filtered={summary !== undefined}
        onScreenSummary={onScreenSummary}
        requestId={state.requestId}
        allPicked={state.allPicked}
        pickedCount={state.picked.length}
        setSelected={state.setSelected}
        showAccount={state.showAccount}
        accounts={state.accounts}
        opened={state.opened}
        selected={state.selected}
        toggleSelected={state.toggleSelected}
        toggleOpened={state.toggleOpened}
        setAccount={state.setAccount}
        setPinnedAccount={state.setPinnedAccount}
      />
      <RefusalPagination
        offset={state.offset}
        pageSize={PAGE_SIZE}
        to={to}
        total={state.total}
        isFetching={state.isFetching}
        turnTo={state.turnTo}
      />
    </div>
  );
}
