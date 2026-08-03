import type { ReactNode } from 'react';

/**
 * Why a disabled control is disabled, in a place that actually reaches someone.
 *
 * `title` on the disabled element itself does not work here and cannot be made
 * to. `buttonVariants` carries `disabled:pointer-events-none`, so the element is
 * never hit-tested and no browser shows its tooltip; Base UI also sets the
 * native `disabled` attribute, so it is not focusable and anything hung off it
 * with `aria-describedby` is never announced either. A first attempt at
 * explaining these buttons did exactly that and rendered nothing at all.
 *
 * The wrapper is not disabled, so it receives the hover and shows the tooltip,
 * and the visually hidden copy puts the same sentence into the row's text for
 * anyone reading rather than pointing.
 */
export function DisabledReason({
  reason,
  children,
}: {
  /** Omitted when the control is enabled, which renders nothing extra. */
  reason?: string;
  children: ReactNode;
}) {
  if (!reason) return <>{children}</>;

  return (
    <span title={reason} className="inline-flex items-center">
      {children}
      <span className="sr-only">{reason}</span>
    </span>
  );
}
