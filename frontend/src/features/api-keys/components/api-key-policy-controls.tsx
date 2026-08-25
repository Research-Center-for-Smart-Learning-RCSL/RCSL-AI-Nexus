import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { IssuableCapability } from '@/features/models/schema';

import { CapabilityPicker } from './capability-picker';
import { EXPIRY_PRESETS, expiryFromToday, NO_DEFAULT } from '../schema';

export function ApiKeyCapabilities({
  scopes,
  onChange,
  error,
}: {
  scopes: IssuableCapability[];
  onChange: (scopes: IssuableCapability[]) => void;
  error?: string;
}) {
  return <CapabilityPicker value={scopes} onChange={onChange} error={error} />;
}

export function DefaultCapabilitySelect({
  value,
  onChange,
  scopes,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  scopes: IssuableCapability[];
  options: string[];
}) {
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (next !== null) onChange(next);
      }}
    >
      <SelectTrigger className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_DEFAULT}>
          Refuse, and say what this key may call
        </SelectItem>
        {options.map((capability) => (
          <SelectItem key={capability} value={capability}>
            Serve {capability}
            {scopes.includes(capability as IssuableCapability)
              ? ''
              : ' (not among this key’s capabilities)'}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** The custom date field stays the source of truth; the preset buttons are
 * shortcuts that write into it rather than a separate control, so switching
 * between them and typing a date never fights over which one wins. */
export function ExpiryField({
  value,
  onChange,
  onBlur,
}: {
  value: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {EXPIRY_PRESETS.map((preset) => (
          <Button
            key={preset.label}
            type="button"
            variant={value === expiryFromToday(preset.days) ? 'secondary' : 'outline'}
            size="xs"
            onClick={() => onChange(expiryFromToday(preset.days))}
          >
            {preset.label}
          </Button>
        ))}
      </div>
      <Input
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
      />
    </div>
  );
}

export function CidrTextarea({
  id,
  value,
  onChange,
  onBlur,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  return (
    <textarea
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
      rows={2}
      placeholder="203.0.113.0/24"
      className="w-full rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
    />
  );
}
