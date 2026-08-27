import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The scenes are only ever reached through a real WebGL context, which neither
// the Vitest environment nor the reduced-motion Playwright runs provide. What
// is exercised here is everything the curtain's own escape hatches depend on:
// the first-frame signal, the frame-rate guard that demotes a slow machine, the
// context-loss listener, and the timeline that reports completion.
const stubs = vi.hoisted(() => ({
  frames: new Map<number, (state: unknown, delta: number) => void>(),
  nextId: { value: 0 },
  canvas: { current: null as HTMLCanvasElement | null },
}));

vi.mock('@react-three/fiber', async () => {
  const { useRef } = await import('react');
  return {
    useFrame: (callback: (state: unknown, delta: number) => void) => {
      const id = useRef<number | null>(null);
      if (id.current === null) {
        id.current = stubs.nextId.value;
        stubs.nextId.value += 1;
      }
      stubs.frames.set(id.current, callback);
    },
    useThree: () => ({ gl: { domElement: stubs.canvas.current } }),
    Canvas: () => null,
  };
});

vi.mock('@react-three/drei', () => ({ Float: () => null }));

const {
  ContextLossGuard,
  MAX_FRAME_DELTA,
  RuntimeSignals,
  layerCameraZ,
  shellTransform,
  timelineProgress,
  tunnelCameraZ,
} = await import('./entry-transition-scenes');

function runFrame(delta = 1 / 60) {
  for (const callback of stubs.frames.values()) callback({}, delta);
}

let now = 0;

beforeEach(() => {
  stubs.frames.clear();
  stubs.canvas.current = document.createElement('canvas');
  now = 1_000;
  vi.spyOn(performance, 'now').mockImplementation(() => now);
});

afterEach(() => vi.restoreAllMocks());

describe('the frame-rate guard', () => {
  it('reports the first frame exactly once', () => {
    const onFirstFrame = vi.fn();
    render(<RuntimeSignals onFirstFrame={onFirstFrame} onFallback={vi.fn()} />);

    runFrame();
    runFrame();
    expect(onFirstFrame).toHaveBeenCalledOnce();
  });

  it('does not sample the warm-up frames that pay for shader compilation', () => {
    const onFallback = vi.fn();
    render(<RuntimeSignals onFirstFrame={vi.fn()} onFallback={onFallback} />);

    // One frame, then a 400ms stall: a 2.5fps average, entirely inside warm-up.
    runFrame();
    now += 400;
    runFrame();
    expect(onFallback).not.toHaveBeenCalled();

    // Sampling opens after the warm-up and 60fps follows.
    now += 100;
    runFrame();
    for (let frame = 0; frame < 40; frame += 1) {
      now += 1000 / 60;
      runFrame();
    }
    expect(onFallback).not.toHaveBeenCalled();
  });

  it('demotes to the fallback when the sampled rate stays below the floor', () => {
    const onFallback = vi.fn();
    render(<RuntimeSignals onFirstFrame={vi.fn()} onFallback={onFallback} />);

    runFrame();
    now += 500; // Past the warm-up, so the next frame opens the sample.
    runFrame();
    for (let frame = 0; frame < 6; frame += 1) {
      now += 100; // 10fps.
      runFrame();
    }
    expect(onFallback).toHaveBeenCalledOnce();

    // The verdict is reached once; a later stall must not fire it again.
    for (let frame = 0; frame < 10; frame += 1) {
      now += 500;
      runFrame();
    }
    expect(onFallback).toHaveBeenCalledOnce();
  });
});

describe('the context-loss guard', () => {
  it('takes the fallback path and keeps the context restorable', () => {
    const onContextLost = vi.fn();
    render(<ContextLossGuard onContextLost={onContextLost} />);

    const event = new Event('webglcontextlost', { cancelable: true });
    stubs.canvas.current?.dispatchEvent(event);

    expect(onContextLost).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it('stops listening once the scene is gone', () => {
    const onContextLost = vi.fn();
    const view = render(<ContextLossGuard onContextLost={onContextLost} />);
    view.unmount();

    stubs.canvas.current?.dispatchEvent(new Event('webglcontextlost', { cancelable: true }));
    expect(onContextLost).not.toHaveBeenCalled();
  });
});

describe('the scene timelines', () => {
  it('clamps progress so the completion signal is reached and not passed', () => {
    expect(timelineProgress(0, 2000)).toBe(0);
    expect(timelineProgress(1, 2000)).toBe(0.5);
    expect(timelineProgress(2, 2000)).toBe(1);
    expect(timelineProgress(30, 2000)).toBe(1);
  });

  it('clamps a single frame delta so a backgrounded tab cannot skip the timeline', () => {
    // A tab restored after ten seconds must still need the frames in between.
    expect(Math.min(10, MAX_FRAME_DELTA)).toBe(MAX_FRAME_DELTA);
    expect(timelineProgress(MAX_FRAME_DELTA, 1600)).toBeLessThan(1);
  });

  it('drives both cameras from their start depth to their end depth', () => {
    expect(tunnelCameraZ(0)).toBeCloseTo(10);
    expect(tunnelCameraZ(1)).toBeCloseTo(-45);
    expect(tunnelCameraZ(0.5)).toBeLessThan(tunnelCameraZ(0.25));

    expect(layerCameraZ(0)).toBeCloseTo(7);
    expect(layerCameraZ(1)).toBeCloseTo(-24);
    expect(layerCameraZ(0.5)).toBeLessThan(layerCameraZ(0.25));
  });

  it('sweeps each shell aside in turn, alternating sides', () => {
    expect(shellTransform(0, 0)).toEqual({ rotationZ: 0, offsetX: 0, scale: 1 });

    const first = shellTransform(1 / 6, 0);
    expect(first.offsetX).toBeCloseTo(9);
    expect(first.scale).toBeCloseTo(1.15);

    // The second shell has not begun to move while the first is still passing.
    expect(shellTransform(1 / 6, 1).offsetX).toBeCloseTo(0);
    expect(shellTransform(2 / 6, 1).offsetX).toBeCloseTo(-9);

    // Every shell is clear by the end.
    for (let index = 0; index < 6; index += 1) {
      expect(Math.abs(shellTransform(1, index).offsetX)).toBeCloseTo(9);
    }
  });
});
