'use client';

import dynamic from 'next/dynamic';
import { Component, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useTheme } from 'next-themes';

import { useIsomorphicLayoutEffect, useMediaQuery } from '@/lib/use-media-query';
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

// Cached: support cannot change within a page lifetime, and the probe is a
// real, blocking context creation. Uncached, a landing -> login -> app pass
// paid for it three times, the login one landing exactly on the first frame
// the opaque cover was waiting for.
let webglProbe: boolean | null = null;

export function supportsWebGL(): boolean {
  if (webglProbe !== null) return webglProbe;
  if (typeof document === 'undefined' || typeof window === 'undefined') return false;
  if (!window.WebGLRenderingContext && !window.WebGL2RenderingContext) {
    webglProbe = false;
    return false;
  }

  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    const supported = Boolean(context);
    const loseContext = context?.getExtension('WEBGL_lose_context');
    loseContext?.loseContext();
    webglProbe = supported;
    return supported;
  } catch {
    webglProbe = false;
    return false;
  }
}

/** Tests redefine the WebGL globals between cases; production never needs this. */
export function resetWebGLProbeForTests() {
  webglProbe = null;
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
    // Through fallBack(), not setMode alone: fallBack also lifts the cover,
    // and without that the CSS fallback played invisibly behind it.
    if (supportsWebGL()) setMode('webgl');
    else fallBack();
  }, [fallBack]);

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

/**
 * The opaque layer both curtains show before their mount decision has landed.
 * It shares `nexus-entry-curtain` so the reduced-motion CSS removes it before
 * any JavaScript runs, and its own class carries a CSS-only timeout fade: if
 * hydration never comes — script blocked, bundle failed — no watchdog exists,
 * and this must not be the layer that bricks the page.
 */
function EntryPrecover({ kind }: { kind: EntrySceneKind }) {
  return (
    <div
      data-testid={`entry-precover-${kind}`}
      aria-hidden="true"
      className="nexus-entry-curtain nexus-entry-precover fixed inset-0 z-[100] bg-background"
    />
  );
}

export function LoginEntryTransition({ bypass }: { bypass: boolean }) {
  const [phase, setPhase] = useState<'undecided' | 'playing' | 'done'>('undecided');

  // A layout effect with a synchronous matchMedia read: the whole login page
  // renders client-side in one pass, and deciding before that pass paints is
  // what stops the form from showing for a frame and then being covered.
  // Deciding exactly once is what keeps an OS reduced-motion toggle, flipped
  // while the form is already in use, from replaying the curtain over it.
  useIsomorphicLayoutEffect(() => {
    if (phase !== 'undecided') return;
    let alreadyPlayed = false;
    try {
      const key = 'nexus.entry.login.v1';
      alreadyPlayed = Boolean(window.sessionStorage.getItem(key));
      // Any arrival at the login screen is the tab's one entrance — a bounced
      // `next=...` visit and a reduced-motion visit included. Marking only the
      // played case meant signing out after a bounced sign-in replayed the
      // full curtain for someone who had just clicked Sign out.
      window.sessionStorage.setItem(key, 'played');
    } catch {
      // Storage is only the frequency gate. A blocked store must not break the
      // entrance, and playing once is the safer degradation than a blank page.
    }
    const reduce =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setPhase(bypass || reduce || alreadyPlayed ? 'done' : 'playing');
  }, [bypass, phase]);

  if (phase === 'done') return null;
  if (phase === 'undecided') return bypass ? null : <EntryPrecover kind="tunnel" />;
  return (
    <EntryCurtain
      kind="tunnel"
      durationMs={2000}
      skippable
      onComplete={() => setPhase('done')}
    />
  );
}

export function AppEntryTransition({
  sessionSettled,
}: {
  sessionSettled: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const [complete, setComplete] = useState(false);

  if (complete || reducedMotion === true) return null;

  // Null means undecided, which is exactly the server render and the pass that
  // hydrates it: the precover puts an opaque layer in the SSR HTML itself, so
  // the shell cannot paint uncovered and then have the curtain slam over it.
  // The reduced-motion CSS strips the precover without JavaScript, and the
  // media-query hook resolves in a layout effect, before the next paint.
  if (reducedMotion === null) return <EntryPrecover kind="layers" />;

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

/**
 * Fills the landing page's visual panel, not the viewport. Mounting inside the
 * panel is what keeps the scene aligned with the card it decorates at every
 * viewport — as a full-page layer its world-space offset only lined up with the
 * panel at one aspect ratio, and elsewhere the geometry poked out from behind
 * the card as stray diagonals. The panel is display:none below `lg`, which also
 * spares phone batteries a permanent render loop for an effect that would sit
 * behind the hero text there.
 */
export function LandingThreeBackdrop() {
  const { resolvedTheme } = useTheme();
  const reducedMotion = useReducedMotion();
  // The panel is display:none below `lg`, which hides but does not unmount:
  // without this gate a phone still paid for a WebGL context and render loop
  // behind a panel it never shows. 64rem is Tailwind's `lg`.
  const panelShown = useMediaQuery('(min-width: 64rem)');
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

  if (reducedMotion !== false || panelShown !== true || !available || !resolvedTheme) {
    return null;
  }

  return (
    // The clip radius matches the panel's outer border. The shadow lives on a
    // sibling, so clipping here cannot cut it off.
    <div
      ref={setContainer}
      data-testid="landing-backdrop"
      className="pointer-events-none absolute inset-0 overflow-hidden rounded-[2.5rem] opacity-80"
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
