'use client';

import { Button } from '@/components/ui/button';
import { CopySuccessIcon } from '@/components/composed/copy-success-icon';
import { FIGURE_LABELS, type Refusal } from '@/features/refusals/schema';
import { refusalToMarkdown } from '@/features/refusals/markdown';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';
import { cn } from '@/lib/utils';
import { wrapTooltip } from '@/lib/wrap-tooltip';

export function statusTone(status: number): 'secondary' | 'destructive' {
  return status >= 500 ? 'destructive' : 'secondary';
}

function figureText(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ');
  if (value === null || value === undefined) return '—';
  return String(value);
}

export function RefusalFigures({
  figures,
  expanded,
}: {
  figures: Record<string, unknown>;
  expanded: boolean;
}) {
  const keys = Object.keys(figures);
  if (keys.length === 0) return null;
  const short = keys.filter((key) => key !== 'composition');
  const composition = figures.composition;
  return (
    <div className="mt-1 space-y-1">
      {short.length > 0 ? (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {short.map((key) => (
            <span
              key={key}
              className="inline-flex max-w-[18rem] gap-1 tabular-nums"
              title={wrapTooltip(
                `${FIGURE_LABELS[key] ?? key}: ${figureText(figures[key])}`,
              )}
            >
              <span className="text-muted-foreground/70">
                {FIGURE_LABELS[key] ?? key}:
              </span>
              <span className="truncate">{figureText(figures[key])}</span>
            </span>
          ))}
        </div>
      ) : null}
      {typeof composition === 'string' ? (
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

export function CopyRefusal({
  refusal,
  account,
}: {
  refusal: Refusal;
  account?: string;
}) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <Button
      size="sm"
      variant="ghost"
      type="button"
      aria-label={`Copy this ${refusal.code} refusal as Markdown`}
      onClick={() => void copy(refusalToMarkdown(refusal, { account }))}
    >
      <CopySuccessIcon copied={copied} className="size-4" />
      <span className="sr-only sm:not-sr-only">
        {copied ? 'Copied' : 'Copy'}
      </span>
    </Button>
  );
}

export function Tick({
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
      ref={(node) => {
        if (node) node.indeterminate = indeterminate;
      }}
      onChange={onChange}
      disabled={disabled}
      aria-label={label}
    />
  );
}
