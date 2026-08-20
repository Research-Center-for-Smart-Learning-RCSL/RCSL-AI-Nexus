import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AUDIT_ACTIONS } from '@/features/logs/schema';

const OUTCOMES = [
  { value: '', label: 'All' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'denied', label: 'Denied' },
];

export function LogFilters({
  actionText,
  setActionText,
  action,
  outcome,
  changeOutcome,
  unknownAction,
  total,
  from,
  to,
}: {
  actionText: string;
  setActionText: (value: string) => void;
  action: string;
  outcome: string;
  changeOutcome: (value: string) => void;
  unknownAction: boolean;
  total: number;
  from: number;
  to: number;
}) {
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <div className="max-w-xs flex-1">
          <Input
            value={actionText}
            onChange={(event) => setActionText(event.target.value)}
            placeholder="Exact action, e.g. user.invited"
            list="audit-actions"
            aria-label="Filter by action, matched exactly"
            aria-describedby="audit-action-hint"
          />
          <datalist id="audit-actions">
            {AUDIT_ACTIONS.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        </div>
        <div className="flex gap-1">
          {OUTCOMES.map((option) => (
            <Button
              key={option.value || 'all'}
              size="sm"
              variant={option.value === outcome ? 'default' : 'outline'}
              onClick={() => changeOutcome(option.value)}
              aria-pressed={option.value === outcome}
            >
              {option.label}
            </Button>
          ))}
        </div>
        <span className="ml-auto text-sm text-muted-foreground tabular-nums">
          {total === 0 ? 'No entries' : `${from}–${to} of ${total}`}
        </span>
      </div>
      <p id="audit-action-hint" className="text-xs text-muted-foreground">
        The action filter matches the whole name, not part of one. Start typing
        to pick from the {AUDIT_ACTIONS.length} the platform records.
        {unknownAction ? (
          <span className="text-destructive">
            {' '}
            <strong>{action}</strong> is not one of them, so this can only ever
            return nothing.
          </span>
        ) : null}
      </p>
    </>
  );
}
