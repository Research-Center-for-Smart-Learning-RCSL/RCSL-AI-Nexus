import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { elementToMarkdown } from '@/lib/markdown-export';
import {
  REDUCED_MOTION_QUERY,
  stubMatchMedia,
} from '@/test-support/match-media';
import { API_ERROR_CATALOGUE } from './api-reference-error-catalogue';
import { ApiReference } from './api-reference';
import {
  API_REFERENCE_SECTION_CATALOGUE,
  apiReferenceHeadingId,
  apiReferenceSectionTitleText,
} from './api-reference-section-catalogue';

const mocks = vi.hoisted(() => ({
  useGatewayInfo: vi.fn(),
  useAssistantSurface: vi.fn(),
}));

vi.mock('@/features/gateway/hooks/use-gateway', () => ({
  useGatewayInfo: mocks.useGatewayInfo,
}));

vi.mock('@/features/assistant/context', () => ({
  useAssistantSurface: mocks.useAssistantSurface,
}));

let observerCallback: IntersectionObserverCallback;
let observerRoot: Element | Document | null | undefined;
let observerThreshold: number | readonly number[] | undefined;
const observe = vi.fn();
const disconnect = vi.fn();
const scrollTo = vi.fn();
let animationFrameCallback: FrameRequestCallback | undefined;

class IntersectionObserverStub {
  readonly root: Element | Document | null;
  readonly rootMargin = '0px';
  readonly thresholds = [0];

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    observerCallback = callback;
    observerRoot = options?.root;
    observerThreshold = options?.threshold;
    this.root = options?.root ?? null;
  }

  observe = observe;
  unobserve = vi.fn();
  disconnect = disconnect;
  takeRecords = () => [];
}

function renderReference() {
  return render(
    <main id="main-content">
      <ApiReference />
    </main>,
  );
}

function rect(top: number, bottom = top + 24): DOMRect {
  return {
    x: 0,
    y: top,
    top,
    bottom,
    left: 0,
    right: 1000,
    width: 1000,
    height: bottom - top,
    toJSON: () => ({}),
  };
}

function setScrollspyPositions(positions: Partial<Record<string, number>>) {
  const main = document.getElementById('main-content');
  if (!main) throw new Error('Shell main was not rendered.');
  main.getBoundingClientRect = () => rect(0, 600);

  API_REFERENCE_SECTION_CATALOGUE.forEach((section, index) => {
    const heading = document.getElementById(apiReferenceHeadingId(section.id));
    if (!heading) throw new Error(`Missing heading for ${section.id}.`);
    const top = positions[section.id] ?? 1000 + index * 100;
    heading.getBoundingClientRect = () => rect(top);
  });
}

beforeEach(() => {
  mocks.useGatewayInfo.mockReturnValue({
    data: {
      base_url: 'https://gateway.example',
      capabilities: ['chat'],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  mocks.useAssistantSurface.mockClear();
  observe.mockClear();
  disconnect.mockClear();
  scrollTo.mockClear();
  animationFrameCallback = undefined;
  observerRoot = undefined;
  observerThreshold = undefined;
  window.history.replaceState({}, '', '/api-docs');
  stubMatchMedia();
  vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    configurable: true,
    value: scrollTo,
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    function () {
      if (this.id === 'main-content') return rect(0, 600);
      const index = API_REFERENCE_SECTION_CATALOGUE.findIndex(
        (section) => apiReferenceHeadingId(section.id) === this.id,
      );
      return index >= 0 ? rect(100 + index * 400) : rect(0);
    },
  );
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
    animationFrameCallback = callback;
    return 1;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('API Reference section catalogue', () => {
  it('resolves every entry to exactly one labelled heading', () => {
    renderReference();

    for (const section of API_REFERENCE_SECTION_CATALOGUE) {
      const region = document.getElementById(section.id);
      const headingId = apiReferenceHeadingId(section.id);
      expect(region).toHaveAttribute('aria-labelledby', headingId);
      expect(document.querySelectorAll(`#${headingId}`)).toHaveLength(1);
      expect(
        within(region as HTMLElement).getByRole('heading', {
          level: 2,
          name: apiReferenceSectionTitleText(section),
        }),
      ).toHaveAttribute('id', headingId);
    }
    expect(screen.getByRole('heading', { name: 'Endpoint' })).toHaveClass(
      'focus:outline-2',
      'focus:outline-solid',
      'focus:outline-ring',
    );
  });

  it('renders sections in catalogue order', () => {
    const { container } = renderReference();
    const rendered = Array.from(
      container.querySelectorAll<HTMLElement>('[data-api-reference-section]'),
    );

    expect(rendered.map((section) => section.id)).toEqual(
      API_REFERENCE_SECTION_CATALOGUE.map((section) => section.id),
    );
    expect(rendered.map((section) => section.dataset.apiReferenceSection)).toEqual(
      API_REFERENCE_SECTION_CATALOGUE.map((section) => section.renderKey),
    );
  });

  it('shares active state between desktop and mobile navigation', () => {
    renderReference();
    const navigation = screen.getByRole('navigation', {
      name: 'API Reference sections',
    });
    const jump = screen.getByRole('combobox', { name: 'Jump to section' });

    expect(navigation).toHaveAttribute('data-md-skip');
    const compactNavigation = jump.closest('[data-md-skip]');
    expect(compactNavigation).toHaveClass('@4xl:hidden');
    expect(navigation).toHaveClass('hidden', '@4xl:block');
    expect(navigation.parentElement).toHaveClass('@4xl:grid');
    expect(navigation.parentElement?.parentElement).toHaveClass('@container');
    expect(
      within(navigation).getByRole('link', { name: 'Endpoint' }),
    ).toHaveAttribute('aria-current', 'location');
    expect(jump).toHaveValue('endpoint');

    setScrollspyPositions({ endpoint: -300, capabilities: 120 });
    act(() => observerCallback([], {} as IntersectionObserver));

    expect(
      within(navigation).getByRole('link', {
        name: 'model names a capability, not a model',
      }),
    ).toHaveAttribute('aria-current', 'location');
    expect(jump).toHaveValue('capabilities');
  });
});

describe('API Reference section navigation', () => {
  it('explicitly jumps within the shell main and preserves the route', async () => {
    const user = userEvent.setup();
    renderReference();
    const main = document.getElementById('main-content');
    const history = vi.spyOn(window.history, 'replaceState');

    const errorsLink = screen.getByRole('link', { name: 'Errors' });
    errorsLink.focus();
    await user.keyboard('{Enter}');

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'smooth' }),
    );
    expect(scrollTo.mock.contexts.at(-1)).toBe(main);
    expect(window.location.pathname).toBe('/api-docs');
    expect(window.location.hash).toBe('#errors');
    expect(history).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Errors' })).toHaveFocus();
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'errors',
    );
  });

  it('loads a direct hash inside the shell main without smooth scrolling', () => {
    window.history.replaceState({}, '', '/api-docs#errors');
    renderReference();
    act(() => animationFrameCallback?.(0));

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'auto' }),
    );
    expect(scrollTo.mock.contexts.at(-1)).toBe(
      document.getElementById('main-content'),
    );
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'errors',
    );
  });

  it('ignores a malformed non-catalogue hash without breaking the reference', () => {
    window.history.replaceState({}, '', '/api-docs#%');

    expect(() => renderReference()).not.toThrow();
    expect(screen.getByRole('heading', { name: 'Endpoint' })).toBeInTheDocument();
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('uses observed headings and the preceding section fallback without history or scrolling', () => {
    renderReference();
    expect(observerRoot).toBe(document.getElementById('main-content'));
    expect(observerThreshold).toEqual([0, 1]);
    const history = vi.spyOn(window.history, 'replaceState');
    scrollTo.mockClear();

    setScrollspyPositions({
      endpoint: -900,
      capabilities: -500,
      request: -40,
      'tool-calling': 800,
    });
    act(() => observerCallback([], {} as IntersectionObserver));
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'request',
    );

    setScrollspyPositions({
      endpoint: -1100,
      capabilities: -700,
      request: -300,
      'tool-calling': 180,
    });
    act(() => observerCallback([], {} as IntersectionObserver));
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'tool-calling',
    );
    expect(history).not.toHaveBeenCalled();
    expect(scrollTo).not.toHaveBeenCalled();
  });

  it('updates when an upward-scrolling heading becomes fully visible at the reading line', () => {
    renderReference();

    setScrollspyPositions({ request: -20, 'tool-calling': 220 });
    act(() => observerCallback([], {} as IntersectionObserver));
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'tool-calling',
    );

    setScrollspyPositions({ request: 16.25, 'tool-calling': 260 });
    act(() => observerCallback([], {} as IntersectionObserver));
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'request',
    );
  });

  it('keeps a sub-pixel-aligned jump target active instead of advancing', () => {
    renderReference();

    setScrollspyPositions({
      endpoint: -2000,
      capabilities: -1600,
      request: -1200,
      'tool-calling': -800,
      'wire-protocols': -400,
      grounding: -200,
      'model-limitations': -100,
      response: -50,
      timeouts: 15.5,
      errors: 320,
    });
    act(() => observerCallback([], {} as IntersectionObserver));

    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'timeouts',
    );
  });

  it('uses immediate scrolling for explicit jumps when reduced motion is requested', async () => {
    stubMatchMedia({ [REDUCED_MOTION_QUERY]: true });
    const user = userEvent.setup();
    renderReference();

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Jump to section' }),
      'limits',
    );

    expect(scrollTo).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: 'auto' }),
    );
    expect(screen.getByRole('heading', { name: 'Limits' })).toHaveFocus();
  });

  it('keeps explicit section jumps usable without IntersectionObserver', async () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    const user = userEvent.setup();
    renderReference();

    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Jump to section' }),
      'errors',
    );

    expect(scrollTo.mock.contexts.at(-1)).toBe(
      document.getElementById('main-content'),
    );
    expect(screen.getByRole('heading', { name: 'Errors' })).toHaveFocus();
  });

  it('leaves modified desktop anchor activation to the browser', () => {
    renderReference();
    const history = vi.spyOn(window.history, 'replaceState');

    fireEvent.click(screen.getByRole('link', { name: 'Errors' }), {
      ctrlKey: true,
    });

    expect(scrollTo).not.toHaveBeenCalled();
    expect(history).not.toHaveBeenCalled();
  });
});

describe('API Reference preservation', () => {
  it('exports the complete contract without navigation chrome', () => {
    const { container } = renderReference();
    const content = container.querySelector<HTMLElement>(
      '[data-api-reference-content]',
    );
    if (!content) throw new Error('API Reference export root was not rendered.');

    const markdown = elementToMarkdown(content);
    for (const section of API_REFERENCE_SECTION_CATALOGUE) {
      const title = apiReferenceSectionTitleText(section);
      const markdownTitle =
        section.id === 'capabilities'
          ? '## `model` names a capability, not a model'
          : `## ${title}`;
      expect(markdown).toContain(markdownTitle);
    }
    for (const error of API_ERROR_CATALOGUE) {
      const escapedCode = error.code.replaceAll('_', '\\_');
      expect(markdown.split(`| ${error.status} | ${escapedCode} |`)).toHaveLength(
        2,
      );
    }
    expect(API_ERROR_CATALOGUE).toHaveLength(17);
    expect(markdown).not.toContain('On this page');
    expect(markdown).not.toContain('Jump to section');
  });

  it('keeps navigation and static documentation usable when gateway information fails', () => {
    mocks.useGatewayInfo.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error('Gateway unavailable'),
      refetch: vi.fn(),
    });

    renderReference();

    expect(
      screen.getByText(/live endpoint and capability list could not be loaded/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: 'API Reference sections' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Jump to section' })).toHaveValue(
      'endpoint',
    );
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(
      API_REFERENCE_SECTION_CATALOGUE.length,
    );
    expect(screen.getByText('https://<gateway>/v1')).toBeInTheDocument();
    expect(screen.getByRole('searchbox', { name: 'Search errors' })).toBeEnabled();
  });
});
