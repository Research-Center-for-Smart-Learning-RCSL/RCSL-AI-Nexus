import { describe, expect, it } from 'vitest';

import {
  createStreamStore,
  formatElapsed,
  reasoningTail,
} from '@/components/composed/stream-message';

describe('formatElapsed', () => {
  it('reads in seconds under a minute and in minutes above', () => {
    expect(formatElapsed(0)).toBe('0s');
    expect(formatElapsed(14_400)).toBe('14s');
    expect(formatElapsed(60_000)).toBe('1m 0s');
    expect(formatElapsed(134_000)).toBe('2m 14s');
  });

  it('never renders a negative clock', () => {
    // Clocks can step backwards; a counter reading "-3s" looks like a bug in
    // the very place it is meant to reassure.
    expect(formatElapsed(-5000)).toBe('0s');
  });
});

describe('reasoningTail', () => {
  it('takes the last non-empty line, which is where the model currently is', () => {
    expect(reasoningTail('first step\nsecond step\n')).toBe('second step');
  });

  it('truncates so the summary stays one line high', () => {
    // The block sitting still is what stops a four-minute deliberation from
    // pushing the page down as it grows.
    const long = 'x'.repeat(200);
    expect(reasoningTail(long, 70)).toHaveLength(70);
  });

  it('is empty for empty or whitespace-only reasoning', () => {
    expect(reasoningTail('')).toBe('');
    expect(reasoningTail('\n  \n')).toBe('');
  });
});

describe('the stream store', () => {
  it('reports streaming from begin(), before any token arrives', () => {
    // The defect this fixes: status only left `idle` on the first delta, so the
    // placeholder that requires `streaming` was unreachable during the only
    // interval it existed for, and the bubble rendered empty for the whole wait.
    const store = createStreamStore();
    expect(store.getSnapshot().status).toBe('idle');
    expect(store.getSnapshot().startedAt).toBeNull();

    store.begin();

    expect(store.getSnapshot().status).toBe('streaming');
    expect(store.getSnapshot().startedAt).not.toBeNull();
  });

  it('keeps the start time across reasoning, answer and completion', () => {
    // The clock measures the wait from the request, so a later delta must not
    // restart it — that would hide exactly the interval it was added to show.
    const store = createStreamStore();
    store.begin();
    const startedAt = store.getSnapshot().startedAt;

    store.appendReasoning('thinking');
    store.append('answer');
    store.finish();

    expect(store.getSnapshot().startedAt).toBe(startedAt);
    expect(store.getSnapshot().reasoning).toBe('thinking');
    expect(store.getSnapshot().text).toBe('answer');
    expect(store.getSnapshot().status).toBe('done');
  });

  it('keeps reasoning and answer apart under a terminal error', () => {
    const store = createStreamStore();
    store.begin();
    store.appendReasoning('deliberating');
    store.fail('upstream died');

    const snapshot = store.getSnapshot();
    expect(snapshot.reasoning).toBe('deliberating');
    expect(snapshot.text).toBe('');
    expect(snapshot.error).toBe('upstream died');
  });
});
