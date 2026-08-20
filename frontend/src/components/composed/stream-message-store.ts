export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export type StreamSnapshot = {
  /** Everything received so far, concatenated. */
  text: string;
  /**
   * A thinking model's deliberation, accumulated separately from `text`. Kept
   * apart all the way to the render so it can never be mistaken for the answer.
   */
  reasoning: string;
  status: StreamStatus;
  /**
   * When the request was issued, not when the first token arrived. The gap
   * between the two is exactly the interval this component used to render as
   * an empty box, so it is the one the elapsed counter has to measure.
   */
  startedAt: number | null;
  /**
   * The terminal frame's reason, once one arrived. `length` means the platform
   * cut the generation at its ceiling, which for a thinking model can happen
   * with no answer produced at all — the case this exists to make visible.
   */
  finishReason: string | null;
  /** Set when a terminal error frame arrived mid-stream. */
  error: string | null;
};

export type StreamStore = {
  subscribe: (onChange: () => void) => () => void;
  getSnapshot: () => StreamSnapshot;
};

export type MutableStreamStore = StreamStore & {
  /**
   * Marks the request as in flight, before any byte has arrived.
   *
   * Without this the status stayed `idle` until the first delta, so the
   * placeholder — which requires `streaming` — was unreachable during the only
   * interval it existed for, and the bubble rendered empty for the whole wait.
   */
  begin: () => void;
  append: (delta: string) => void;
  appendReasoning: (delta: string) => void;
  fail: (message: string) => void;
  finish: (finishReason?: string | null) => void;
  reset: () => void;
};

const EMPTY: StreamSnapshot = {
  text: '',
  reasoning: '',
  status: 'idle',
  startedAt: null,
  finishReason: null,
  error: null,
};

/**
 * A minimal external store. Deliberately not React state: the producer is the
 * stream reader, which lives outside the render cycle and would otherwise
 * schedule a state update per token.
 */
export function createStreamStore(initial = ''): MutableStreamStore {
  let snapshot: StreamSnapshot = initial
    ? {
        text: initial,
        reasoning: '',
        status: 'idle',
        startedAt: null,
        finishReason: null,
        error: null,
      }
    : EMPTY;
  const listeners = new Set<() => void>();

  function emit(next: StreamSnapshot) {
    snapshot = next;
    for (const listener of listeners) listener();
  }

  return {
    subscribe(onChange) {
      listeners.add(onChange);
      return () => listeners.delete(onChange);
    },
    getSnapshot: () => snapshot,
    begin() {
      emit({ ...EMPTY, status: 'streaming', startedAt: Date.now() });
    },
    append(delta) {
      if (!delta) return;
      emit({ ...snapshot, text: snapshot.text + delta, status: 'streaming', error: null });
    },
    appendReasoning(delta) {
      if (!delta) return;
      // Sets `streaming` exactly as `append` does. For a thinking model this is
      // the only signal there is for as long as it deliberates, and a status
      // that stayed `idle` through it would render as a stalled request.
      emit({
        ...snapshot,
        reasoning: snapshot.reasoning + delta,
        status: 'streaming',
        error: null,
      });
    },
    fail(message) {
      // Keeps whatever was produced. Truncated output with a visible reason is
      // strictly better than a blank bubble.
      emit({ ...snapshot, status: 'error', error: message });
    },
    finish(finishReason = null) {
      if (snapshot.status === 'error') return;
      emit({ ...snapshot, status: 'done', finishReason, error: null });
    },
    reset() {
      emit(EMPTY);
    },
  };
}

/** Server snapshot: streaming never happens during SSR. */
export function serverSnapshot(): StreamSnapshot {
  return {
    text: '',
    reasoning: '',
    status: 'idle',
    startedAt: null,
    finishReason: null,
    error: null,
  };
}
