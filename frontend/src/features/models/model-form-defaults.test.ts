import { describe, expect, it } from 'vitest';

import { defaultsFor } from '@/features/models/components/model-form-dialog';
import { modelReferenceSchema, resourceProfileSchema } from '@/features/models/schema';

describe('the register form offers no resource profile', () => {
  it('leaves memory and context blank rather than inventing them', () => {
    // They were 8 and 8192 until 2026-09-07. Both feed guardrails that fail
    // quietly and late: `memory_gb` is what the budget checks on a first load,
    // before any observation exists, and 8192 is the figure that put the
    // per-model truncation guard at 4096 and served `assist` from a cut prompt.
    const profile = defaultsFor().resource_profile;

    expect(profile.memory_gb).toBeUndefined();
    expect(profile.context_length).toBeUndefined();
  });

  it('blank cannot be submitted, which is what makes blank safe', () => {
    // The whole argument for removing the defaults is that an empty field asks
    // and a plausible wrong one does not. That only holds while the schema
    // refuses the empty value.
    expect(resourceProfileSchema.safeParse({}).success).toBe(false);
    expect(
      resourceProfileSchema.safeParse({ memory_gb: 0, context_length: 0 }).success,
    ).toBe(false);
  });

  it('an existing model still opens on its own figures', () => {
    const profile = defaultsFor({
      id: 'm1',
      alias: 'a',
      ref: 'r',
      runtime: 'ollama',
      node_id: 'n1',
      state: 'loaded',
      capabilities: ['chat'],
      resource_profile: { memory_gb: 41, context_length: 262144 },
      observed_state: null,
      observed_memory_gb: null,
      observed_at: null,
    }).resource_profile;

    expect(profile).toEqual({ memory_gb: 41, context_length: 262144 });
  });
});

describe('what the host declares for a reference', () => {
  it('carries the figure when the weights are readable', () => {
    const parsed = modelReferenceSchema.parse({
      ref: 'gemma4:31b-it-q8_0',
      declared_context_length: 262144,
    });
    expect(parsed.declared_context_length).toBe(262144);
  });

  it('carries null when they are not, so the form suggests nothing', () => {
    // Not pulled, a different runtime, a missing mount. A guess is what this
    // endpoint exists to replace.
    const parsed = modelReferenceSchema.parse({
      ref: 'absent:latest',
      declared_context_length: null,
    });
    expect(parsed.declared_context_length).toBeNull();
  });
});
