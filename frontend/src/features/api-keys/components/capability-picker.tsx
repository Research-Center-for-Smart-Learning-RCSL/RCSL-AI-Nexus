'use client';

import { Label } from '@/components/ui/label';
import {
  issuableCapabilitySchema,
  type IssuableCapability,
} from '@/features/models/schema';
import { useGatewayInfo } from '@/features/gateway/hooks/use-gateway';

/**
 * Which capabilities a key may invoke.
 *
 * Two things are true at once and the control has to show both. The five names
 * are what a key *can* be issued for, fixed in the backend's
 * `ISSUABLE_CAPABILITIES`. What a request will actually be *served* depends on
 * a routing policy existing, and a key issued for a capability nothing routes
 * authenticates perfectly and then answers `no_available_model` forever — an
 * error deliberately indistinguishable from every node being busy, so the
 * holder has no way to tell it was never going to work.
 *
 * So the unrouted ones are shown, disabled, and labelled. Hiding them would
 * make the list look like the whole set and leave an administrator wondering
 * where `vision` went; offering them would keep selling keys that cannot work.
 *
 * The reverse case never reaches this control. `assist` has a routing policy
 * and is still not offered, because it is not in the issuable set at all — and
 * `useGatewayInfo` does not return it either, since `ListCapabilities` filters
 * what it derives from the policy table. Two independent reasons, which is
 * deliberate: this component enumerates a hardcoded list, and a list that
 * silently gained a name would otherwise start selling it.
 */
export function CapabilityPicker({
  value,
  onChange,
  error,
}: {
  value: IssuableCapability[];
  onChange: (next: IssuableCapability[]) => void;
  error?: string;
}) {
  const { data, isLoading } = useGatewayInfo();
  const servable = new Set(data?.capabilities ?? []);

  return (
    <div className="space-y-2">
      <Label>Capabilities</Label>
      <div className="flex flex-wrap gap-3">
        {issuableCapabilitySchema.options.map((option) => {
          // While loading, nothing is known to be unroutable yet. Disabling
          // everything for a moment would make the form look broken, and the
          // selection is re-checked by the server regardless.
          const routable = isLoading || servable.has(option);
          const selected = value.includes(option);
          // Only ever disabled on the way *in*. A key already issued for a
          // capability whose policy has since been deleted must still be
          // narrowable — removing it is exactly what this control is for, and
          // disabling a checked box makes the one capability nothing serves
          // the one nobody can take away.
          const locked = !routable && !selected;
          return (
            <label
              key={option}
              className={`flex items-center gap-1.5 text-sm ${
                routable ? '' : 'text-muted-foreground'
              }`}
            >
              <input
                type="checkbox"
                disabled={locked}
                checked={selected}
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
        refused any capability it was not issued for, unless a default capability
        is set below — which serves one of the key&apos;s own instead of
        refusing, and can never reach one it does not hold.{' '}
        <code>embedding</code> and <code>rerank</code> may be issued and routed,
        but the gateway mounts only <code>/v1/chat/completions</code> and{' '}
        <code>/v1/responses</code>, so a key carrying either has no endpoint to
        call with it yet.
      </p>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
