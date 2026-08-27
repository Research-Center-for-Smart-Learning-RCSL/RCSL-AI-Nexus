'use client';

import dynamic from 'next/dynamic';
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTheme } from 'next-themes';

import { useReducedMotion } from '@/lib/use-reduced-motion';

export type EntrySceneKind = 'tunnel' | 'layers';

const DynamicEntryScene = dynamic(
  () => import('./entry-transition-scenes').then((module) => module.EntryScene),
  { ssr: false, loading: () => null },
);

const DynamicLandingScene = dynamic(
  () => import('./entry-transition-scenes').then((module) => module.LandingScene),
  { ssr: false, loading: () => null },
);

type BoundaryProps = { children: ReactNode; onError: () => void };

class SceneBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function supportsWebGL(): boolean {
  if (typeof document === 'undefined' || typeof window === 'undefined') return false;
  if (!window.WebGLRenderingContext && !window.WebGL2RenderingContext) return false;

  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    const supported = Boolean(context);
    const loseContext = context?.getExtension('WEBGL_lose_context');
    loseContext?.loseContext();
    return supported;
  } catch {
    return false;
  }
}

export function EntryCurtain({
  kind,
  durationMs,
  canFinish = true,
  skippable = false,
  onComplete,
}: {
  kind: EntrySceneKind;
  durationMs: number;
  canFinish?: boolean;
  skippable?: boolean;
  onComplete: () => void;
}) {
  const { resolvedTheme } = useTheme();
  const [mode, setMode] = useState<'checking' | 'webgl' | 'fallback'>('checking');
  const [firstFrame, setFirstFrame] = useState(false);
  const [timelineDone, setTimelineDone] = useState(false);
  const [exiting, setExiting] = useState(false);
  const finished = useRef(false);

  // Every caller passes an inline closure, so `onComplete` changes identity on
  // each render of the parent. Reading it through a ref keeps `finish` stable,
  // which is what stops the watchdog and exit timers below from being torn down
  // and restarted from zero by re-renders they have nothing to do with.
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    onCompleteRef.current();
  }, []);

  const fallBack = useCallback(() => {
    setMode('fallback');
    setFirstFrame(true);
    setTimelineDone(false);
  }, []);

  useEffect(() => {
    setMode(supportsWebGL() ? 'webgl' : 'fallback');
  }, []);

  useEffect(() => {
    if (mode !== 'fallback') return;
    // The exit fade is part of the fallback's total ~400ms budget.
    const timer = window.setTimeout(() => setTimelineDone(true), 180);
    return () => window.clearTimeout(timer);
  }, [mode]);

  useEffect(() => {
    if (!timelineDone || !canFinish || finished.current) return;
    setExiting(true);
    const timer = window.setTimeout(finish, 220);
    return () => window.clearTimeout(timer);
  }, [canFinish, finish, timelineDone]);

  // Shader compilation, a lost context, or a missed callback must never leave
  // an opaque fixed layer over the application.
  useEffect(() => {
    const watchdog = window.setTimeout(finish, Math.max(durationMs + 1800, 3200));
    return () => window.clearTimeout(watchdog);
  }, [durationMs, finish]);

  // Any key, not a designated one. The cover is opaque, so anything typed
  // underneath it is typed blind; dismissing on the first keystroke is also
  // what keeps keyboard and screen-reader users from being held behind the
  // cover, since nothing beneath it is inert while it is mounted.
  useEffect(() => {
    if (!skippable) return;
    const skip = () => finish();
    window.addEventListener('keydown', skip);
    return () => window.removeEventListener('keydown', skip);
  }, [finish, skippable]);

  return (
    <div
      data-testid={`entry-curtain-${kind}`}
      className={`nexus-entry-curtain fixed inset-0 z-[100] overflow-hidden ${exiting ? 'nexus-curtain-exit' : ''}`}
      onPointerDown={skippable ? finish : undefined}
    >
      <div className="absolute inset-0 bg-background" aria-hidden="true">
        {mode === 'webgl' && resolvedTheme ? (
          <SceneBoundary onError={fallBack}>
            <DynamicEntryScene
              kind={kind}
              theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
              durationMs={durationMs}
              onFirstFrame={() => setFirstFrame(true)}
              onTimelineComplete={() => setTimelineDone(true)}
              onFallback={fallBack}
            />
          </SceneBoundary>
        ) : null}
        {mode === 'fallback' ? (
          <div className="nexus-curtain-fallback absolute inset-0 flex items-center justify-center bg-background">
            <div className="size-40 rounded-[2rem] border border-primary/30 bg-card/70 shadow-2xl shadow-primary/20" />
          </div>
        ) : null}
        <div
          data-testid="entry-curtain-cover"
          className={`absolute inset-0 z-10 bg-background transition-opacity duration-150 ${firstFrame ? 'pointer-events-none opacity-0' : 'opacity-100'}`}
        />
      </div>

      {skippable ? (
        <button
          type="button"
          className="absolute right-5 bottom-5 z-20 rounded-full border border-white/20 bg-black/35 px-4 py-2 text-sm font-medium text-white shadow-lg backdrop-blur hover:bg-black/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
          onClick={finish}
        >
          Skip animation
        </button>
      ) : null}
    </div>
  );
}

export function LoginEntryTransition({ bypass }: { bypass: boolean }) {
  const reducedMotion = useReducedMotion();
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (reducedMotion === null) return;
    if (bypass || reducedMotion) {
      setPlaying(false);
      return;
    }

    try {
      const key = 'nexus.entry.login.v1';
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, 'played');
    } catch {
      // Storage is only the frequency gate. A blocked store must not break the
      // entrance, and playing once is the safer degradation than a blank page.
    }
    setPlaying(true);
  }, [bypass, reducedMotion]);

  return playing ? (
    <EntryCurtain
      kind="tunnel"
      durationMs={2000}
      skippable
      onComplete={() => setPlaying(false)}
    />
  ) : null;
}

export function AppEntryTransition({
  sessionSettled,
}: {
  sessionSettled: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const [complete, setComplete] = useState(false);

  if (reducedMotion !== false || complete) return null;

  return (
    <EntryCurtain
      kind="layers"
      durationMs={1600}
      canFinish={sessionSettled}
      skippable
      onComplete={() => setComplete(true)}
    />
  );
}

export function LandingThreeBackdrop() {
  const { resolvedTheme } = useTheme();
  const reducedMotion = useReducedMotion();
  const [available, setAvailable] = useState(false);
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [onScreen, setOnScreen] = useState(true);

  useEffect(() => setAvailable(supportsWebGL()), []);

  // Unlike the curtains this backdrop animates for as long as the page is open,
  // so scrolling it out of view has to stop the render loop. A hidden tab needs
  // no handling here: requestAnimationFrame already stops on its own.
  useEffect(() => {
    if (!container || typeof IntersectionObserver !== 'function') return;
    const observer = new IntersectionObserver(
      ([entry]) => setOnScreen(entry.isIntersecting),
      { threshold: 0 },
    );
    observer.observe(container);
    return () => observer.disconnect();
  }, [container]);

  if (reducedMotion !== false || !available || !resolvedTheme) return null;

  return (
    <div
      ref={setContainer}
      className="pointer-events-none absolute inset-0 opacity-70"
      aria-hidden="true"
    >
      <SceneBoundary onError={() => setAvailable(false)}>
        <DynamicLandingScene
          theme={resolvedTheme === 'dark' ? 'dark' : 'light'}
          animating={onScreen}
          onContextLost={() => setAvailable(false)}
        />
      </SceneBoundary>
    </div>
  );
}
