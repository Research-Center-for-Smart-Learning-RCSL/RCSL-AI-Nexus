import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  PANEL_BREAKPOINT_QUERY,
  REDUCED_MOTION_QUERY,
  stubMatchMedia,
} from '@/test-support/match-media';

// The scene itself needs a GPU; what is under test is the gate in front of it.
vi.mock('./entry-transition-scenes', () => ({
  EntryScene: () => null,
  LandingScene: () => null,
}));

vi.mock('next-themes', () => ({
  useTheme: () => ({ resolvedTheme: 'dark' }),
}));

const { LandingThreeBackdrop, resetWebGLProbeForTests } = await import('./entry-transition');

function mockWebGL(supported: boolean) {
  Object.defineProperty(window, 'WebGLRenderingContext', {
    configurable: true,
    value: class WebGLRenderingContext {},
  });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    supported ? ({ getExtension: () => null } as unknown as WebGLRenderingContext) : null,
  );
}

beforeEach(() => resetWebGLProbeForTests());

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(window, 'WebGLRenderingContext');
});

// This is the state no single-boolean matchMedia stub could express: the
// backdrop mounts only with reduced motion OFF and the panel breakpoint MET.
describe('the landing backdrop gate', () => {
  it('mounts when motion is allowed, the panel is shown, and WebGL exists', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false, [PANEL_BREAKPOINT_QUERY]: true });
    mockWebGL(true);

    render(<LandingThreeBackdrop />);
    expect(screen.getByTestId('landing-backdrop')).toBeInTheDocument();
  });

  it('stays unmounted below the panel breakpoint, where display:none would still run it', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false, [PANEL_BREAKPOINT_QUERY]: false });
    mockWebGL(true);

    render(<LandingThreeBackdrop />);
    expect(screen.queryByTestId('landing-backdrop')).toBeNull();
  });

  it('stays unmounted under reduced motion even with the panel shown', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true, [PANEL_BREAKPOINT_QUERY]: true });
    mockWebGL(true);

    render(<LandingThreeBackdrop />);
    expect(screen.queryByTestId('landing-backdrop')).toBeNull();
  });

  it('stays unmounted without WebGL', () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: false, [PANEL_BREAKPOINT_QUERY]: true });
    mockWebGL(false);

    render(<LandingThreeBackdrop />);
    expect(screen.queryByTestId('landing-backdrop')).toBeNull();
  });
});
