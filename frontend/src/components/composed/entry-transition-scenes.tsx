'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Float } from '@react-three/drei';
import * as THREE from 'three';

import type { EntrySceneKind } from './entry-transition';

type PaletteName = 'light' | 'dark';

const PALETTES = {
  dark: { background: '#090d16', line: '#67e8f9', glow: '#dffcff', wash: '#f8fafc' },
  light: { background: '#f7f9ff', line: '#1e40af', glow: '#60a5fa', wash: '#ffffff' },
} satisfies Record<PaletteName, Record<string, string>>;

const SHELL_COUNT = 6;

/**
 * A backgrounded tab delivers one enormous delta on return. Clamping it keeps
 * the timeline from jumping straight to its end, and to the completion callback
 * the curtain is waiting on, in a single frame.
 */
export const MAX_FRAME_DELTA = 0.1;

export function timelineProgress(elapsedSeconds: number, durationMs: number): number {
  return Math.min(elapsedSeconds / (durationMs / 1000), 1);
}

export function tunnelCameraZ(progress: number): number {
  return THREE.MathUtils.lerp(10, -45, 1 - Math.pow(1 - progress, 3));
}

export function layerCameraZ(progress: number): number {
  return THREE.MathUtils.lerp(7, -24, progress * progress * (3 - 2 * progress));
}

export function shellTransform(progress: number, index: number) {
  const passed = Math.max(0, Math.min(1, progress * SHELL_COUNT - index));
  const direction = index % 2 ? -1 : 1;
  return {
    rotationZ: passed * direction * 0.8,
    offsetX: passed * direction * 9,
    scale: 1 + passed * 0.15,
  };
}

// The opening frames pay for shader compilation and buffer upload, which is
// exactly when the frame rate is worst. Measuring across that window is what
// makes a capable machine look slow, so it is skipped before sampling starts.
const WARM_UP_MS = 450;
const SAMPLE_MS = 500;
const MIN_FPS = 24;

export function ContextLossGuard({ onContextLost }: { onContextLost: () => void }) {
  const { gl } = useThree();

  useEffect(() => {
    const canvas = gl.domElement;
    // Without preventDefault the context can never be restored by the browser.
    // Either way this layer steps aside rather than sitting there blank.
    const lost = (event: Event) => {
      event.preventDefault();
      onContextLost();
    };
    canvas.addEventListener('webglcontextlost', lost);
    return () => canvas.removeEventListener('webglcontextlost', lost);
  }, [gl, onContextLost]);

  return null;
}

export function RuntimeSignals({
  onFirstFrame,
  onFallback,
}: {
  onFirstFrame: () => void;
  onFallback: () => void;
}) {
  const first = useRef(false);
  const frames = useRef(0);
  const firstFrameAt = useRef(0);
  const sampleStart = useRef(0);
  const measured = useRef(false);

  useFrame(() => {
    const now = performance.now();

    if (!first.current) {
      first.current = true;
      firstFrameAt.current = now;
      onFirstFrame();
    }

    if (measured.current) return;
    if (now - firstFrameAt.current < WARM_UP_MS) return;
    if (sampleStart.current === 0) {
      sampleStart.current = now;
      return;
    }

    frames.current += 1;
    const elapsed = now - sampleStart.current;
    if (elapsed < SAMPLE_MS) return;
    measured.current = true;
    if ((frames.current * 1000) / elapsed < MIN_FPS) onFallback();
  });

  return null;
}

function GlowBar({
  position,
  scale,
  color,
}: {
  position: [number, number, number];
  scale: [number, number, number];
  color: string;
}) {
  return (
    <group position={position}>
      <mesh scale={scale}>
        <boxGeometry />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
      <mesh scale={scale.map((value) => value * 1.12) as [number, number, number]}>
        <boxGeometry />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.14}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

function Tunnel({
  theme,
  durationMs,
  onComplete,
}: {
  theme: PaletteName;
  durationMs: number;
  onComplete: () => void;
}) {
  const elapsed = useRef(0);
  const done = useRef(false);
  const rings = useMemo(() => Array.from({ length: 13 }, (_, index) => 4 - index * 4), []);
  const palette = PALETTES[theme];

  useFrame(({ camera }, delta) => {
    elapsed.current += Math.min(delta, MAX_FRAME_DELTA);
    const progress = timelineProgress(elapsed.current, durationMs);
    camera.position.z = tunnelCameraZ(progress);
    camera.rotation.z = Math.sin(progress * Math.PI * 2) * 0.025;
    if (progress === 1 && !done.current) {
      done.current = true;
      onComplete();
    }
  });

  return (
    <>
      {rings.map((z, index) => (
        <group key={z} position={[0, 0, z]} rotation={[0, 0, index % 2 ? 0.035 : -0.035]}>
          <GlowBar position={[0, 3.2, 0]} scale={[5.4, 0.055, 0.055]} color={palette.line} />
          <GlowBar position={[0, -3.2, 0]} scale={[5.4, 0.055, 0.055]} color={palette.line} />
          <GlowBar position={[5.35, 0, 0]} scale={[0.055, 3.2, 0.055]} color={palette.line} />
          <GlowBar position={[-5.35, 0, 0]} scale={[0.055, 3.2, 0.055]} color={palette.line} />
        </group>
      ))}
      <mesh position={[0, 0, -48]}>
        <sphereGeometry args={[2.6, 24, 24]} />
        <meshBasicMaterial color={palette.wash} toneMapped={false} />
      </mesh>
      <fog attach="fog" args={[palette.background, 8, 32]} />
    </>
  );
}

function LayerDive({
  theme,
  durationMs,
  onComplete,
}: {
  theme: PaletteName;
  durationMs: number;
  onComplete: () => void;
}) {
  const elapsed = useRef(0);
  const done = useRef(false);
  const shells = useMemo(
    () => Array.from({ length: SHELL_COUNT }, (_, index) => -index * 4),
    [],
  );
  const groups = useRef<Array<THREE.Group | null>>([]);
  const palette = PALETTES[theme];

  useFrame(({ camera }, delta) => {
    elapsed.current += Math.min(delta, MAX_FRAME_DELTA);
    const progress = timelineProgress(elapsed.current, durationMs);
    camera.position.z = layerCameraZ(progress);
    groups.current.forEach((group, index) => {
      if (!group) return;
      const { rotationZ, offsetX, scale } = shellTransform(progress, index);
      group.rotation.z = rotationZ;
      group.position.x = offsetX;
      group.scale.setScalar(scale);
    });
    if (progress === 1 && !done.current) {
      done.current = true;
      onComplete();
    }
  });

  return (
    <>
      {shells.map((z, index) => (
        <group key={z} ref={(node) => { groups.current[index] = node; }} position={[0, 0, z]}>
          <mesh>
            <boxGeometry args={[11, 7, 0.16]} />
            <meshBasicMaterial
              color={palette.line}
              transparent
              opacity={theme === 'dark' ? 0.12 : 0.08}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
            />
          </mesh>
          {Array.from({ length: 7 }, (_, line) => (
            <GlowBar key={`h-${line}`} position={[0, -3 + line, 0.11]} scale={[5.3, 0.012, 0.012]} color={palette.glow} />
          ))}
          {Array.from({ length: 11 }, (_, line) => (
            <GlowBar key={`v-${line}`} position={[-5 + line, 0, 0.11]} scale={[0.012, 3.3, 0.012]} color={palette.glow} />
          ))}
        </group>
      ))}
      <fog attach="fog" args={[palette.background, 7, 30]} />
    </>
  );
}

export function EntryScene({
  kind,
  theme,
  durationMs,
  onFirstFrame,
  onTimelineComplete,
  onFallback,
}: {
  kind: EntrySceneKind;
  theme: PaletteName;
  durationMs: number;
  onFirstFrame: () => void;
  onTimelineComplete: () => void;
  onFallback: () => void;
}) {
  const palette = PALETTES[theme];
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, kind === 'tunnel' ? 10 : 7], fov: 58 }}
      gl={{ antialias: false, alpha: false, powerPreference: 'high-performance' }}
      fallback={null}
    >
      <color attach="background" args={[palette.background]} />
      <ContextLossGuard onContextLost={onFallback} />
      <RuntimeSignals onFirstFrame={onFirstFrame} onFallback={onFallback} />
      {kind === 'tunnel' ? (
        <Tunnel theme={theme} durationMs={durationMs} onComplete={onTimelineComplete} />
      ) : (
        <LayerDive theme={theme} durationMs={durationMs} onComplete={onTimelineComplete} />
      )}
    </Canvas>
  );
}

function LandingGeometry({ theme }: { theme: PaletteName }) {
  const group = useRef<THREE.Group>(null);
  const palette = PALETTES[theme];
  useFrame(({ clock }) => {
    if (!group.current) return;
    group.current.rotation.z = clock.elapsedTime * 0.035;
    group.current.rotation.x = Math.sin(clock.elapsedTime * 0.2) * 0.08;
  });

  return (
    <Float speed={0.7} rotationIntensity={0.12} floatIntensity={0.25}>
      <group ref={group} position={[3.2, 0.2, 0]} rotation={[0.8, 0.1, 0.15]}>
        {Array.from({ length: 7 }, (_, index) => {
          const size = 2.2 + index * 0.75;
          return (
            <group key={size} position={[0, 0, -index * 0.45]}>
              <GlowBar position={[0, size * 0.62, 0]} scale={[size, 0.018, 0.018]} color={palette.line} />
              <GlowBar position={[0, -size * 0.62, 0]} scale={[size, 0.018, 0.018]} color={palette.line} />
              <GlowBar position={[size, 0, 0]} scale={[0.018, size * 0.62, 0.018]} color={palette.line} />
              <GlowBar position={[-size, 0, 0]} scale={[0.018, size * 0.62, 0.018]} color={palette.line} />
            </group>
          );
        })}
      </group>
    </Float>
  );
}

export function LandingScene({
  theme,
  animating,
  onContextLost,
}: {
  theme: PaletteName;
  animating: boolean;
  onContextLost: () => void;
}) {
  return (
    <Canvas
      dpr={[1, 1.35]}
      frameloop={animating ? 'always' : 'never'}
      camera={{ position: [0, 0, 12], fov: 52 }}
      gl={{ antialias: false, alpha: true, powerPreference: 'high-performance' }}
      fallback={null}
    >
      <ContextLossGuard onContextLost={onContextLost} />
      <LandingGeometry theme={theme} />
    </Canvas>
  );
}
