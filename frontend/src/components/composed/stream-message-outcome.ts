import { formatElapsed } from './reasoning-block';

/**
 * What to say when a generation ended with no answer to show.
 *
 * `length` is the platform stopping the generation itself, and it has two
 * causes the response cannot distinguish: the output token ceiling, and the
 * 900-second wall-clock deadline on a single generation
 * (`generation_deadline_seconds`), which cuts the stream with the same
 * `finish_reason`. Either is reachable with zero answer tokens produced on a
 * thinking model — measured at 16,384 tokens and eleven minutes of pure
 * deliberation. Naming only one of them would send a reader who hit the other
 * off to raise a limit that was never reached. Without this the reader gets an
 * empty bubble that looks identical to a malfunction, and the elapsed time
 * disappears with the live message that was carrying it.
 *
 * Returns null when there is nothing to explain, so an ordinary empty turn
 * stays quiet.
 */
export function describeEmptyOutcome(
  finishReason: string | null,
  elapsedMs: number | null,
): string | null {
  if (finishReason !== 'length') return null;
  const took = elapsedMs === null ? '' : ` after ${formatElapsed(elapsedMs)}`;
  return `Stopped at the token ceiling or the platform's 15-minute deadline for one generation${took} — the response does not say which: the model was still reasoning and never started an answer. Asking again with Thinking off gets a direct reply.`;
}
