import { Label } from '@/components/ui/label';
import {
  MODEL_STATES,
  NODE_STATUSES,
} from '@/features/routing-policies/schema';

export function PolicyRequirementsEditor({
  nodeStatus,
  modelState,
  onToggle,
}: {
  nodeStatus: string[];
  modelState: string[];
  onToggle: (
    key: 'node_status' | 'model_state',
    current: string[],
    value: string,
    checked: boolean,
  ) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label className="text-xs text-muted-foreground">
          Required node status
        </Label>
        <div className="flex flex-wrap gap-3">
          {NODE_STATUSES.map((status) => (
            <label key={status} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={nodeStatus.includes(status)}
                onChange={(event) =>
                  onToggle(
                    'node_status',
                    nodeStatus,
                    status,
                    event.target.checked,
                  )
                }
              />
              {status}
            </label>
          ))}
        </div>
      </div>
      <div className="space-y-1.5">
        <Label className="text-xs text-muted-foreground">
          Required model state
        </Label>
        <div className="flex flex-wrap gap-3">
          {MODEL_STATES.map((state) => (
            <label key={state} className="flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={modelState.includes(state)}
                onChange={(event) =>
                  onToggle(
                    'model_state',
                    modelState,
                    state,
                    event.target.checked,
                  )
                }
              />
              {state}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
