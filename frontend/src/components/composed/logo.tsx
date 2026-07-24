import Image from 'next/image';

import { cn } from '@/lib/utils';

/**
 * The RCSL mark.
 *
 * Derived from `frontend/brand/RCSL-source.png`, which is kept outside
 * `public/` so it is not served: the supplied file has an opaque cream field
 * baked in, which shows as a rectangle on every surface and as a glaring block
 * in dark mode. `public/logo.png` is the same artwork with that field keyed
 * out by luminance, which preserves the anti-aliased edges that a threshold
 * would have left jagged.
 *
 * The mark is an interlocking monogram, so it stops being legible below about
 * 48px: at 24px the woven strokes merge into a blob. Do not reach for a
 * smaller size than the ones offered here. The square favicon derived from it
 * is a blur at 16px, which is true of most detailed marks and is accepted.
 *
 * Dark mode inverts to near-white rather than shipping a second asset. The
 * navy measures far too little contrast against the app's dark surface to be
 * used as-is.
 */
const ASPECT = 899 / 649;

export function Logo({
  height = 40,
  className,
}: {
  /** Rendered height in pixels. Below 48 the monogram stops resolving. */
  height?: number;
  className?: string;
}) {
  return (
    <Image
      src="/logo.png"
      alt="RCSL"
      width={Math.round(height * ASPECT)}
      height={height}
      priority
      className={cn('dark:brightness-0 dark:invert', className)}
    />
  );
}
