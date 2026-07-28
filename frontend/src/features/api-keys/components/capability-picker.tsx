'use client';

import { Label } from '@/components/ui/label';
import { capabilitySchema, type Capability } from '@/features/models/schema';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';

/**
 * Which capabilities a key may invoke.
 *
 * Two things are true at once and the control has to show both. The five names
 * are what a key *can* be issued for, fixed in the backend's
 * `KNOWN_CAPABILITIES`. What a request will actually be *served* depends on a
 * routing policy existing, and a key issued for a capability nothing routes
 * authenticates perfectly and then answers `no_available_model` forever — an
 * error deliberately indistinguishable from every node being busy, so the
 * holder has no way to tell it was never going to work.
 *
 * So the unrouted ones are shown, disabled, and labelled. Hiding them would
 * make the list look like the whole set and leave an administrator wondering
 * where `vision` went; offering them would keep selling keys that cannot work.
 */
export function CapabilityPicker({
  value,
  onChange,
  error,
}: {
  value: Capability[];
  onChange: (next: Capability[]) => void;
  error?: string;
}) {
  const { data, isLoading } = useGatewayInfo();
  const servable = new Set(data?.capabilities ?? []);

  return (
    <div className="space-y-2">
      <Label>Capabilities</Label>
      <div className="flex flex-wrap gap-3">
        {capabilitySchema.options.map((option) => {
          // While loading, nothing is known to be unroutable yet. Disabling
          // everything for a moment would make the form look broken, and the
          // selection is re-checked by the server regardless.
          const routable = isLoading || servable.has(option);
          return (
            <label
              key={option}
              className={`flex items-center gap-1.5 text-sm ${
                routable ? '' : 'text-muted-foreground'
              }`}
            >
              <input
                type="checkbox"
                disabled={!routable}
                checked={value.includes(option)}
                onChange={(event) => {
                  onChange(
                    event.target.checked
                      ? [...value, option]
                      : value.filter((scope) => scope !== option),
                  );
                }}
              />
              {option}
              {routable ? null : (
                <span className="text-xs">(nothing serves this yet)</span>
              )}
            </label>
          );
        })}
      </div>
      <p className="text-sm text-muted-foreground">
        A request names one of these in its <code>model</code> field. A key is
        refused any capability it was not issued for.
      </p>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
