import { describe, expect, it } from 'vitest';

import { wrapTooltip } from '@/lib/wrap-tooltip';

const MESSAGE =
  'This input is 125,340 tokens against a limit of 122,880, counting tool definitions and every replayed turn. Retrying it unchanged cannot succeed and waiting does not clear it: send less — start a new conversation, continue from a summary of this one, or stop reading large files into it.';

describe('wrapTooltip', () => {
  it('breaks the refusal message that provoked this', () => {
    // 287 characters, rendered by every browser as one line wider than the
    // window, clipped at the screen edge with the end of the sentence off it.
    const wrapped = wrapTooltip(MESSAGE);

    expect(wrapped).toBeDefined();
    const lines = wrapped!.split('\n');
    expect(lines.length).toBeGreaterThan(3);
    for (const line of lines) expect(line.length).toBeLessThanOrEqual(72);
  });

  it('keeps every word, in order', () => {
    // A tooltip that wrapped by dropping something would be worse than the
    // long line it replaced.
    expect(wrapTooltip(MESSAGE)!.split(/\s+/)).toEqual(MESSAGE.split(/\s+/));
  });

  it('breaks a single token wider than the whole tooltip', () => {
    // A path, a base64 blob, a uuid list: the case where wrapping on spaces
    // achieves nothing at all.
    const wrapped = wrapTooltip(`prefix ${'x'.repeat(200)}`, 40)!;

    for (const line of wrapped.split('\n')) expect(line.length).toBeLessThanOrEqual(40);
    expect(wrapped.replace(/\n/g, '')).toContain('x'.repeat(40));
  });

  it('leaves an existing newline as a hard break', () => {
    // A caller that joined two facts with one meant them on separate lines.
    expect(wrapTooltip('req_abc\nkey 979e40')).toBe('req_abc\nkey 979e40');
  });

  it('omits the attribute rather than opening an empty tooltip', () => {
    // React drops a `title` that is `undefined`; `title=""` is a hover that
    // opens on nothing, which reads as broken.
    expect(wrapTooltip('')).toBeUndefined();
    expect(wrapTooltip(null)).toBeUndefined();
    expect(wrapTooltip(undefined)).toBeUndefined();
  });

  it('leaves something already short alone', () => {
    expect(wrapTooltip('POST /v1/chat/completions')).toBe('POST /v1/chat/completions');
  });
});
