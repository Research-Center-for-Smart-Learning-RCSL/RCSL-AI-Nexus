import { cn } from '@/lib/utils';

/**
 * Busy indicator.
 *
 * The animation is defined in globals.css as `.nexus-spinner` and draws itself
 * with `currentColor`, so colour is set here by a normal text utility rather
 * than by the component knowing anything about the palette.
 *
 * `aria-label` rather than a visually hidden string, because the surrounding
 * copy usually already says what is loading and a second announcement is
 * noise. Callers that need different wording pass their own.
 *
 * `label={null}` marks the spinner decorative, for the case where visible copy
 * beside it already says the same thing — announcing both reads the message
 * twice.
 */
export function Spinner({
  className,
  label = 'Loading',
}: {
  className?: string;
  label?: string | null;
}) {
  return (
    <span
      role={label === null ? undefined : 'status'}
      aria-hidden={label === null ? true : undefined}
      aria-label={label ?? undefined}
      // The shadows extend well beyond the element box, so it needs room
      // around it or it will overlap whatever sits next to it.
      className={cn('nexus-spinner mx-8 my-8 inline-block text-primary', className)}
    />
  );
}
