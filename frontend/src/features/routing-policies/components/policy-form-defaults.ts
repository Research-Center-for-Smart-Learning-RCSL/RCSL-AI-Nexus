import type { Capability } from '@/features/models/schema';
import {
  thinkingToForm,
  type RoutingPolicy,
  type SavePolicyInput,
} from '@/features/routing-policies/schema';

export function emptyCandidate(): SavePolicyInput['candidates'][number] {
  return {
    model_alias: '',
    priority: 100,
    require: { node_status: [], model_state: [], min_free_memory_gb: '' },
  };
}

export function policyFormDefaults(
  policy: RoutingPolicy | undefined,
  capability: Capability,
): SavePolicyInput {
  if (!policy) {
    return { capability, candidates: [emptyCandidate()], thinking: 'default' };
  }
  return {
    capability: policy.capability,
    thinking: thinkingToForm(policy.thinking),
    candidates: policy.candidates.map((candidate) => ({
      model_alias: candidate.model_alias,
      priority: candidate.priority,
      require: {
        node_status: [...candidate.require.node_status],
        model_state: [...candidate.require.model_state],
        min_free_memory_gb:
          candidate.require.min_free_memory_gb === null
            ? ''
            : String(candidate.require.min_free_memory_gb),
      },
    })),
  };
}
