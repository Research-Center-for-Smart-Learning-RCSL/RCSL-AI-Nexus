import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { IssuableCapability } from '@/features/models/schema';

import { CapabilityPicker } from './capability-picker';
import { NO_DEFAULT } from '../schema';

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
