'use client';

import { Button } from '@/components/ui/button';
import { CopySuccessIcon } from '@/components/composed/copy-success-icon';
import { Input } from '@/components/ui/input';
import type { AccountOption, AccountQuery } from '@/features/refusals/account';

type RefusalFiltersProps = {
  requestId: string;
  setRequestId: (value: string) => void;
  code: string;
  setCode: (value: string) => void;
  showAccount: boolean;
  account: string;
  setAccount: (value: string) => void;
  setPinnedAccount: (value: AccountQuery | null) => void;
  names: AccountOption[];
  total: number;
  from: number;
  to: number;
  copyingCount: number;
  pickedCount: number;
  copied: boolean;
  onCopy: () => void;
};

export function RefusalFilters(props: RefusalFiltersProps) {
  const {
    requestId,
    setRequestId,
    code,
    setCode,
    showAccount,
    account,
    setAccount,
    setPinnedAccount,
    names,
    total,
    from,
    to,
    copyingCount,
    pickedCount,
    copied,
    onCopy,
  } = props;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="max-w-xs flex-1">
        <Input
          value={requestId}
          onChange={(event) => setRequestId(event.target.value)}
          placeholder="Request id, e.g. req_9f2a…"
          aria-label="Find a refusal by the request id the caller was given"
        />
      </div>
      <div className="max-w-[12rem] flex-1">
        <Input
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="Code, e.g. context_too_long"
          aria-label="Filter by error code"
        />
      </div>
      {showAccount ? (
        <div className="max-w-[16rem] flex-1">
          <Input
            value={account}
            list="refusal-account-names"
            onChange={(event) => {
              setAccount(event.target.value);
              setPinnedAccount(null);
            }}
            placeholder="Login, full name, or an id"
            aria-label="Show one account's refusals, by login, full name, or id"
          />
          <datalist id="refusal-account-names">
            {names.map((option) => (
              <option
                key={option.value}
                value={option.value}
                label={option.label}
              />
            ))}
          </datalist>
        </div>
      ) : null}
      <span className="ml-auto text-sm text-muted-foreground tabular-nums">
        {total === 0 ? 'No refusals' : `${from}–${to} of ${total}`}
      </span>
      <Button
        size="sm"
        variant="outline"
        type="button"
        disabled={copyingCount === 0}
        onClick={onCopy}
      >
        <CopySuccessIcon copied={copied} className="size-4" />
        {copied
          ? 'Copied'
          : pickedCount > 0
            ? `Copy ${pickedCount} selected`
            : 'Copy this page'}
      </Button>
    </div>
  );
}
