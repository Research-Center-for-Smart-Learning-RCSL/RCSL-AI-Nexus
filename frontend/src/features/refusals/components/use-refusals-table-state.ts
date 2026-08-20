'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  accountOptions,
  accountQuery,
  usersById,
  type AccountQuery,
} from '@/features/refusals/account';
import { useRefusals } from '@/features/refusals/hooks/use-refusals';
import type { Refusal, RefusalFilters } from '@/features/refusals/schema';
import { toInstant } from '@/features/refusals/time-range';
import { useUsers } from '@/features/users/hooks/use-users';
import { useDebounced } from '@/lib/use-debounced';

export const PAGE_SIZE = 50;
export const NOTHING: ReadonlySet<string> = new Set();

export function useRefusalsTableState() {
  const [requestId, setRequestId] = useState('');
  const [code, setCode] = useState('');
  const [account, setAccount] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<ReadonlySet<string>>(NOTHING);
  const [mayReadAll, setMayReadAll] = useState(false);
  const [pinnedAccount, setPinnedAccount] = useState<AccountQuery | null>(null);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());

  const users = useUsers({ enabled: mayReadAll });
  const accounts = useMemo(() => usersById(users.data), [users.data]);
  const settledCode = useDebounced(code.trim());
  const settledRequestId = useDebounced(requestId.trim());
  const settledAccount = useDebounced(account.trim());
  const accountFilter = pinnedAccount ?? accountQuery(settledAccount, accounts);
  const filters: RefusalFilters = {
    code: settledCode || undefined,
    request_id: settledRequestId || undefined,
    ...accountFilter,
    since: toInstant(since),
    until: toInstant(until),
    limit: PAGE_SIZE,
    offset,
  };
  const query = useRefusals(filters);

  useEffect(() => {
    if (query.data && !query.data.scoped_to_self) setMayReadAll(true);
  }, [query.data]);
  useEffect(() => {
    setOffset(0);
    setSelected(NOTHING);
  }, [settledCode, settledRequestId, settledAccount, pinnedAccount, since, until]);

  const entries: Refusal[] = query.data?.entries ?? [];
  const total = query.data?.total ?? 0;
  const picked = entries.filter((entry) => selected.has(entry.id));

  function toggleOpened(id: string) {
    setOpened((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }
  function toggleSelected(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }
  function turnTo(next: number) {
    setOffset(next);
    setSelected(NOTHING);
  }

  return {
    requestId,
    setRequestId,
    code,
    setCode,
    account,
    setAccount,
    since,
    setSince,
    until,
    setUntil,
    offset,
    selected,
    setSelected,
    pinnedAccount,
    setPinnedAccount,
    opened,
    toggleOpened,
    toggleSelected,
    turnTo,
    accounts,
    filters,
    entries,
    total,
    picked,
    copying: picked.length > 0 ? picked : entries,
    allPicked: entries.length > 0 && picked.length === entries.length,
    showAccount: Boolean(query.data && !query.data.scoped_to_self),
    names: accountOptions(accounts),
    ...query,
  };
}
