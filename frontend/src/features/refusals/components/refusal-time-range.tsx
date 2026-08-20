import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PRESETS, toLocalInput } from '@/features/refusals/time-range';

export function RefusalTimeRange({
  since,
  until,
  setSince,
  setUntil,
}: {
  since: string;
  until: string;
  setSince: (value: string) => void;
  setUntil: (value: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-muted-foreground">When</span>
      {PRESETS.map((preset) => (
        <Button
          key={preset.id}
          size="sm"
          variant="outline"
          type="button"
          onClick={() => {
            setSince(toLocalInput(preset.from(new Date())));
            setUntil('');
          }}
        >
          {preset.label}
        </Button>
      ))}
      <Input
        type="datetime-local"
        className="w-auto"
        value={since}
        onChange={(event) => setSince(event.target.value)}
        aria-label="From, inclusive"
      />
      <Input
        type="datetime-local"
        className="w-auto"
        value={until}
        onChange={(event) => setUntil(event.target.value)}
        aria-label="Before, exclusive"
      />
      {since || until ? (
        <Button
          size="sm"
          variant="ghost"
          type="button"
          onClick={() => {
            setSince('');
            setUntil('');
          }}
        >
          Clear
        </Button>
      ) : null}
    </div>
  );
}
