'use client';

/**
 * The control for the palette globals.css already defines.
 *
 * `.dark` carried a fully worked-out ramp — measured contrast on both the
 * primary and the chart series — reachable only by changing the operating
 * system. Someone on a light desktop who wants a dark console, or the reverse,
 * had no way to ask for it.
 *
 * Three states rather than two: `system` is the default and dropping it would
 * mean anyone who touched the control once could never get back to following
 * the OS. Cycling in the order light -> dark -> system keeps it one button.
 */

import { useEffect, useState } from 'react';
import { useTheme } from 'next-themes';
import { MonitorIcon, MoonIcon, SunIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';

const ORDER = ['light', 'dark', 'system'] as const;
type Choice = (typeof ORDER)[number];

const NEXT: Record<Choice, Choice> = {
  light: 'dark',
  dark: 'system',
  system: 'light',
};

const LABEL: Record<Choice, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'System',
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // The server cannot know the stored choice, so rendering the real icon on the
  // first pass would mismatch whatever `next-themes` applies on the client.
  // A fixed placeholder until mount keeps the markup stable and the layout from
  // shifting once it arrives.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const current: Choice = ORDER.includes(theme as Choice)
    ? (theme as Choice)
    : 'system';
  const next = NEXT[current];

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => setTheme(next)}
      // Says the current state and what pressing it does. A button whose label
      // is only its destination reads as a claim about the present.
      aria-label={
        mounted
          ? `Theme: ${LABEL[current]}. Switch to ${LABEL[next].toLowerCase()}.`
          : 'Theme'
      }
      title={mounted ? `Theme: ${LABEL[current]}` : undefined}
    >
      {!mounted ? (
        <MonitorIcon />
      ) : current === 'light' ? (
        <SunIcon />
      ) : current === 'dark' ? (
        <MoonIcon />
      ) : (
        <MonitorIcon />
      )}
    </Button>
  );
}
