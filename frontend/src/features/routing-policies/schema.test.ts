import { describe, expect, it } from 'vitest';

import {
  routingPolicySchema,
  savePolicyFormSchema,
} from '@/features/routing-policies/schema';

const baseCandidate = {
  model_alias: 'qwen-coder',
  priority: '100',
  require: { node_status: [], model_state: [], min_free_memory_gb: '' },
};

function parseForm(overrides: Record<string, unknown> = {}) {
  return savePolicyFormSchema.safeParse({
    capability: 'chat',
    candidates: [{ ...baseCandidate, ...overrides }],
  });
}

describe('savePolicyFormSchema', () => {
  it('coerces the priority string to a number', () => {
    const result = parseForm();
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.candidates[0].priority).toBe(100);
  });

  it('treats a blank memory floor as null rather than zero', () => {
    const result = parseForm({
      require: { node_status: [], model_state: [], min_free_memory_gb: '' },
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.candidates[0].require.min_free_memory_gb).toBeNull();
  });

  it('coerces a supplied memory floor to a positive number', () => {
    const result = parseForm({
      require: { node_status: [], model_state: [], min_free_memory_gb: '16' },
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.candidates[0].require.min_free_memory_gb).toBe(16);
  });

  it('rejects a zero or negative memory floor', () => {
    expect(
      parseForm({ require: { node_status: [], model_state: [], min_free_memory_gb: '0' } }).success,
    ).toBe(false);
    expect(
      parseForm({ require: { node_status: [], model_state: [], min_free_memory_gb: '-4' } }).success,
    ).toBe(false);
  });

  it('preserves the requirement arrays', () => {
    const result = parseForm({
      require: { node_status: ['online'], model_state: ['loaded'], min_free_memory_gb: '' },
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.candidates[0].require.node_status).toEqual(['online']);
      expect(result.data.candidates[0].require.model_state).toEqual(['loaded']);
    }
  });

  it('requires a model alias', () => {
    expect(parseForm({ model_alias: '' }).success).toBe(false);
  });

  it('requires at least one candidate', () => {
    expect(
      savePolicyFormSchema.safeParse({ capability: 'chat', candidates: [] }).success,
    ).toBe(false);
  });

  it('rejects an unknown node status', () => {
    expect(
      parseForm({ require: { node_status: ['sleeping'], model_state: [], min_free_memory_gb: '' } })
        .success,
    ).toBe(false);
  });
});

describe('routingPolicySchema', () => {
  it('parses a backend response with a null and a numeric memory floor', () => {
    const parsed = routingPolicySchema.parse({
      capability: 'chat',
      candidates: [
        {
          model_alias: 'qwen-coder',
          priority: 100,
          require: { node_status: ['online'], model_state: ['loaded'], min_free_memory_gb: null },
        },
        {
          model_alias: 'fallback',
          priority: 10,
          require: { node_status: [], model_state: [], min_free_memory_gb: 8 },
        },
      ],
    });
    expect(parsed.candidates).toHaveLength(2);
    expect(parsed.candidates[0].require.min_free_memory_gb).toBeNull();
    expect(parsed.candidates[1].require.min_free_memory_gb).toBe(8);
  });

  it('rejects a candidate with an unknown model state', () => {
    expect(
      routingPolicySchema.safeParse({
        capability: 'chat',
        candidates: [
          {
            model_alias: 'x',
            priority: 1,
            require: { node_status: [], model_state: ['melted'], min_free_memory_gb: null },
          },
        ],
      }).success,
    ).toBe(false);
  });
});
