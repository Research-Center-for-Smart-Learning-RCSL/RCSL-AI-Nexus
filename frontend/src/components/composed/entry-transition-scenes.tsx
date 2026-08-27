'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Float, RoundedBox } from '@react-three/drei';
import * as THREE from 'three';

import type { EntrySceneKind } from './entry-transition';

type PaletteName = 'light' | 'dark';

// `wash` is the tunnel's destination orb. In dark it is near-white against the
// void; in light a white orb vanished into the white page, so the destination
// is the brand blue there instead.
const PALETTES = {
  dark: { background: '#090d16', line: '#67e8f9', glow: '#dffcff', wash: '#f8fafc' },
  light: { background: '#f7f9ff', line: '#1e40af', glow: '#60a5fa', wash: '#3b82f6' },
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
  const linear = Math.max(0, Math.min(1, progress * SHELL_COUNT - index));
  // Smoothstep: each shell starts and ends its sweep without a jolt, instead
  // of snapping into linear motion the frame the camera reaches it.
  const passed = linear * linear * (3 - 2 * linear);
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
      <mesh scale={scale} geometry={UNIT_BOX} material={glowMaterial(color, 'solid')} dispose={null} />
      <mesh
        scale={scale.map((value) => value * 1.12) as [number, number, number]}
        geometry={UNIT_BOX}
        material={glowMaterial(color, 'halo')}
        dispose={null}
      />
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
      {/* Elliptical rings rather than four bars: the bars met at corners that
          read as broken joints when a ring passed close to the camera, and a
          continuous curve has no joints to break. The alternating twist keeps
          the depth readable. */}
      {rings.map((z, index) => (
        <group
          key={z}
          position={[0, 0, z]}
          rotation={[0, 0, index % 2 ? 0.06 : -0.06]}
          scale={[1.66, 1, 1]}
        >
          <GlowRing radius={3.35} tube={0.05} color={palette.line} />
        </group>
      ))}
      <mesh position={[0, 0, -48]}>
        <sphereGeometry args={[2.6, 24, 24]} />
        {/* fog={false}: this is the light at the end of the tunnel, and letting
            the fog dim it left a grey ball where the destination should read as
            bright from the first frame. */}
        <meshBasicMaterial color={palette.wash} toneMapped={false} fog={false} />
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
          {/* Rounded like every card in the interface it opens onto; a sharp
              slab read as a pane of glass from a different product. */}
          <RoundedBox args={[11, 7, 0.16]} radius={0.55} smoothness={4}>
            <meshBasicMaterial
              color={palette.line}
              transparent
              opacity={theme === 'dark' ? 0.12 : 0.08}
              blending={THREE.AdditiveBlending}
              depthWrite={false}
            />
          </RoundedBox>
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

// Module-level, never disposed (`dispose={null}` on every consumer): the bars
// and rings differ only by transform and colour, and per-element geometries
// and materials made the scenes construct hundreds of identical objects during
// exactly the warm-up window the frame-rate guard measures around.
const UNIT_BOX = new THREE.BoxGeometry();

const torusCache = new Map<string, THREE.TorusGeometry>();
function sharedTorus(radius: number, tube: number): THREE.TorusGeometry {
  const key = `${radius}|${tube}`;
  let geometry = torusCache.get(key);
  if (!geometry) {
    geometry = new THREE.TorusGeometry(radius, tube, 12, 96);
    torusCache.set(key, geometry);
  }
  return geometry;
}

const materialCache = new Map<string, THREE.MeshBasicMaterial>();
function glowMaterial(color: string, variant: 'solid' | 'halo'): THREE.MeshBasicMaterial {
  const key = `${color}|${variant}`;
  let material = materialCache.get(key);
  if (!material) {
    material =
      variant === 'solid'
        ? new THREE.MeshBasicMaterial({ color, toneMapped: false })
        : new THREE.MeshBasicMaterial({
            color,
            transparent: true,
            opacity: 0.15,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
            toneMapped: false,
          });
    materialCache.set(key, material);
  }
  return material;
}

function GlowRing({
  radius,
  color,
  tube = 0.02,
}: {
  radius: number;
  color: string;
  tube?: number;
}) {
  return (
    <>
      <mesh geometry={sharedTorus(radius, tube)} material={glowMaterial(color, 'solid')} dispose={null} />
      <mesh geometry={sharedTorus(radius, tube * 2.5)} material={glowMaterial(color, 'halo')} dispose={null} />
    </>
  );
}

/**
 * Writes depth only, no colour, over the footprint of the landing panel's CSS
 * icon card (12rem square, rotated 6deg clockwise, centred). The canvas sits
 * above that card in the DOM, so this mask is what hands occlusion back to the
 * 3D scene: an orbit's rear arc is swallowed here while its front arc draws
 * over the icons, which is what makes the rings read as wrapping the card
 * rather than sliding beneath it. Sized from the render height because the
 * camera shows a fixed world height regardless of panel pixel size.
 */
function CardDepthMask() {
  const { camera, size } = useThree();
  const worldHeight =
    2 * camera.position.z * Math.tan(((camera as THREE.PerspectiveCamera).fov * Math.PI) / 360);
  // The card is sized in rem (size-48 = 12rem), so a reader-enlarged root font
  // moves its pixel edge; a hard-coded 192px left the mask ~20% small at a
  // 20px root and let rear arcs draw over the card's outer band.
  const rootFontPx =
    typeof document === 'undefined'
      ? 16
      : Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const side = ((12 * rootFontPx) / size.height) * worldHeight;
  return (
    <mesh rotation={[0, 0, -0.105]} scale={[side, side, 1]} renderOrder={-1}>
      <boxGeometry args={[1, 1, 0.9]} />
      <meshBasicMaterial colorWrite={false} />
    </mesh>
  );
}

// Tilts near edge-on read as orbits; speeds and phases are mutually irrational
// enough that the composition never visibly repeats.
const ORBITS = [
  { radius: 2.9, tilt: [1.45, 0.0], speed: 0.31, phase: 0 },
  { radius: 3.7, tilt: [1.15, 0.35], speed: -0.24, phase: 2.1 },
  { radius: 4.5, tilt: [1.5, -0.3], speed: 0.19, phase: 4.2 },
  { radius: 5.3, tilt: [0.95, 0.6], speed: -0.16, phase: 1.3 },
  { radius: 6.1, tilt: [1.3, -0.55], speed: 0.13, phase: 3.4 },
] as const;

function LandingGeometry({ theme }: { theme: PaletteName }) {
  const group = useRef<THREE.Group>(null);
  const rings = useRef<Array<THREE.Group | null>>([]);
  const palette = PALETTES[theme];

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    group.current?.rotation.set(0, 0, t * 0.02);
    rings.current.forEach((ring, index) => {
      if (!ring) return;
      const { tilt, speed, phase } = ORBITS[index];
      ring.rotation.x = tilt[0] + Math.sin(t * speed + phase) * 0.14;
      ring.rotation.y = tilt[1] + Math.cos(t * speed * 0.8 + phase) * 0.12;
    });
  });

  return (
    <Float speed={0.7} rotationIntensity={0.1} floatIntensity={0.2}>
      {/* Centered: the canvas fills the landing panel, so these orbit the icon
          card the panel carries. Rings rather than frames — continuous curves
          around the card's rounded corners, where rectangles of straight bars
          read as stray sticks whenever the rotation caught them edge-on. */}
      <group ref={group}>
        {ORBITS.map((orbit, index) => (
          <group key={orbit.radius} ref={(node) => { rings.current[index] = node; }}>
            <GlowRing radius={orbit.radius} color={palette.line} />
          </group>
        ))}
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
      // Antialiased, unlike the curtains: these lines are a third the width of
      // the tunnel's, and without MSAA they alias into broken dashes. The
      // canvas is one panel, not a viewport, so the cost stays small.
      gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
      fallback={null}
    >
      <ContextLossGuard onContextLost={onContextLost} />
      <CardDepthMask />
      <LandingGeometry theme={theme} />
    </Canvas>
  );
}
