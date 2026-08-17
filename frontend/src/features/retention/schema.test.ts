import { describe, expect, it } from 'vitest';

import {
  datasetDescription,
  datasetLabel,
  retentionPolicyListSchema,
} from '@/features/retention/schema';

const POLICY = {
  dataset: 'audit_log',
  days: 360,
  updated_at: null,
  updated_by: null,
  minimum_days: 30,
  maximum_days: null,
};

describe('retentionPolicySchema', () => {
  it('renders a dataset this build has never heard of', () => {
    /**
     * The defect this file exists for. `refusals` was added on the server and
     * the frontend had a closed enum of three, so **every** policy failed to
     * parse behind the one unrecognised value and the screen showed nothing —
     * under a docstring claiming a fourth dataset would appear without a
     * frontend change. The bounds now ride on the response, so there is
     * nothing left for the two sides to disagree about.
     */
    const page = retentionPolicyListSchema.parse([
      POLICY,
      { ...POLICY, dataset: 'something_added_next_year', minimum_days: 7, maximum_days: 180 },
    ]);

    expect(page).toHaveLength(2);
    expect(page[1].maximum_days).toBe(180);
  });

  it('falls back to the table name rather than to nothing', () => {
    expect(datasetLabel('something_added_next_year')).toBe('something added next year');
    expect(datasetDescription('something_added_next_year')).toContain('server enforces');
  });

  it('names the four datasets that exist today', () => {
    expect(datasetLabel('refusals')).toBe('Refusals');
    expect(datasetDescription('refusals')).toContain('ceiling as well as a floor');
  });

  it('keeps a ceiling nullable, because two datasets have none', () => {
    // `audit_log` and `usage_records` may be kept as long as an administrator
    // likes; the danger there is forgetting too soon.
    expect(retentionPolicyListSchema.parse([POLICY])[0].maximum_days).toBeNull();
  });
});
