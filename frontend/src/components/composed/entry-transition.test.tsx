import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { REDUCED_MOTION_QUERY, stubMatchMedia } from '@/test-support/match-media';
import {
  AppEntryTransition,
  EntryCurtain,
  LoginEntryTransition,
  resetWebGLProbeForTests,
} from './entry-transition';

function setReducedMotion(matches: boolean) {
  stubMatchMedia({ [REDUCED_MOTION_QUERY]: matches });
}

beforeEach(() => {
  vi.useFakeTimers();
  window.sessionStorage.clear();
  resetWebGLProbeForTests();
  setReducedMotion(false);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  Reflect.deleteProperty(window, 'WebGLRenderingContext');
});

describe('the shared curtain controller', () => {
  it('finishes through the short CSS fallback when WebGL is unavailable', () => {
    const complete = vi.fn();
    render(<EntryCurtain kind="tunnel" durationMs={2000} onComplete={complete} />);

    expect(screen.getByTestId('entry-curtain-tunnel')).toBeInTheDocument();
    // The cover must lift, or the fallback animation plays invisibly under an
    // opaque layer — which is exactly what it did until 2026-08-27.
    expect(screen.getByTestId('entry-curtain-cover').className).toContain('opacity-0');
    act(() => vi.advanceTimersByTime(180));
    expect(complete).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(220));
    expect(complete).toHaveBeenCalledOnce();
  });

  it('holds a completed timeline until the session has settled', () => {
    const complete = vi.fn();
    const view = render(
      <EntryCurtain
        kind="layers"
        durationMs={1600}
        canFinish={false}
        onComplete={complete}
      />,
    );

    act(() => vi.advanceTimersByTime(1200));
    expect(complete).not.toHaveBeenCalled();

    view.rerender(
      <EntryCurtain
        kind="layers"
        durationMs={1600}
        canFinish
        onComplete={complete}
      />,
    );
    act(() => vi.advanceTimersByTime(220));
    expect(complete).toHaveBeenCalledOnce();
  });

  it('skips the application curtain immediately by key or pointer', () => {
    const byKey = vi.fn();
    const first = render(
      <EntryCurtain kind="layers" durationMs={1600} skippable onComplete={byKey} />,
    );
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(byKey).toHaveBeenCalledOnce();
    first.unmount();

    const byPointer = vi.fn();
    render(
      <EntryCurtain kind="layers" durationMs={1600} skippable onComplete={byPointer} />,
    );
    fireEvent.pointerDown(screen.getByTestId('entry-curtain-layers'));
    expect(byPointer).toHaveBeenCalledOnce();
  });

  it('uses the watchdog when no rendering path reports completion', () => {
    const complete = vi.fn();
    Object.defineProperty(window, 'WebGLRenderingContext', {
      configurable: true,
      value: class WebGLRenderingContext {},
    });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      getExtension: () => null,
    } as unknown as WebGLRenderingContext);

    render(<EntryCurtain kind="tunnel" durationMs={2000} onComplete={complete} />);
    act(() => vi.advanceTimersByTime(3799));
    expect(complete).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(complete).toHaveBeenCalledOnce();
  });

  it('keeps the watchdog running across re-renders of the shell around it', () => {
    // Every caller passes an inline onComplete, so the callback's identity
    // changes whenever the shell re-renders. When that identity reached the
    // watchdog's dependencies the timer restarted from zero each time, and a
    // shell re-rendering faster than the timeout — with a session that never
    // settles, which is the case the watchdog exists for — left the opaque
    // cover on screen indefinitely.
    let rerenderShell: () => void = () => {};

    function Shell() {
      const [tick, setTick] = useState(0);
      rerenderShell = () => setTick((value) => value + 1);
      return (
        <div data-tick={tick}>
          <AppEntryTransition sessionSettled={false} />
        </div>
      );
    }

    const view = render(<Shell />);
    expect(screen.getByTestId('entry-curtain-layers')).toBeInTheDocument();

    // Ten seconds, re-rendering every 200ms, against a 3400ms watchdog.
    for (let step = 0; step < 50; step += 1) {
      act(() => {
        rerenderShell();
        vi.advanceTimersByTime(200);
      });
    }

    expect(view.container.querySelector('.nexus-entry-curtain')).toBeNull();
  });
});

describe('where each curtain is allowed to play', () => {
  it('plays the login curtain once per tab session', () => {
    const first = render(<LoginEntryTransition bypass={false} />);
    expect(screen.getByTestId('entry-curtain-tunnel')).toBeInTheDocument();
    first.unmount();

    render(<LoginEntryTransition bypass={false} />);
    expect(screen.queryByTestId('entry-curtain-tunnel')).toBeNull();
  });

  it('lets a keystroke dismiss the login curtain, which covers a focused field', () => {
    render(<LoginEntryTransition bypass={false} />);
    expect(screen.getByTestId('entry-curtain-tunnel')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'a' });
    act(() => vi.advanceTimersByTime(0));
    expect(screen.queryByTestId('entry-curtain-tunnel')).toBeNull();
  });

  it('never plays the login curtain for a bounced next URL', () => {
    render(<LoginEntryTransition bypass />);
    expect(screen.queryByTestId('entry-curtain-tunnel')).toBeNull();
  });

  it('counts a bounced visit toward the once-per-tab gate', () => {
    // Without this, sign in through a bounce and then Sign out: the return to
    // a plain /login found the gate unwritten and replayed the full curtain.
    const bounced = render(<LoginEntryTransition bypass />);
    bounced.unmount();

    render(<LoginEntryTransition bypass={false} />);
    expect(screen.queryByTestId('entry-curtain-tunnel')).toBeNull();
  });

  it('mounts neither curtain when reduced motion is requested', () => {
    setReducedMotion(true);
    const view = render(
      <>
        <LoginEntryTransition bypass={false} />
        <AppEntryTransition sessionSettled />
      </>,
    );

    expect(view.container.querySelector('.nexus-entry-curtain')).toBeNull();
  });

  it('mounts the application curtain independently of session loading', () => {
    render(<AppEntryTransition sessionSettled={false} />);
    expect(screen.getByTestId('entry-curtain-layers')).toBeInTheDocument();
  });
});
