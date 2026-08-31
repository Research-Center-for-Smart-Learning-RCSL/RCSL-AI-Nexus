'use client';

import {
  useLayoutEffect,
  useRef,
  type ComponentProps,
  type KeyboardEvent,
} from 'react';

import { cn } from '@/lib/utils';

type ComposerTextareaProps = ComponentProps<'textarea'>;

/**
 * A compact message field that grows with its content to a bounded height,
 * then scrolls internally. Enter keeps the single-line composer's send behaviour;
 * Shift+Enter adds a line without making touch layouts depend on a tall field.
 */
export function ComposerTextarea({
  className,
  onKeyDown,
  value,
  ...props
}: ComposerTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    textarea.style.height = 'auto';
    const height = Math.min(Math.max(textarea.scrollHeight, 32), 128);
    textarea.style.height = `${height}px`;
    textarea.style.overflowY = textarea.scrollHeight > 128 ? 'auto' : 'hidden';
  }, [value]);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    onKeyDown?.(event);
    if (
      event.defaultPrevented ||
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing
    ) {
      return;
    }

    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  return (
    <textarea
      ref={textareaRef}
      rows={1}
      data-slot="composer-textarea"
      value={value}
      onKeyDown={handleKeyDown}
      className={cn(
        'min-h-8 max-h-32 w-full min-w-0 resize-none rounded-lg border border-input bg-transparent px-2.5 py-1 text-base leading-6 outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 md:text-sm dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40',
        className,
      )}
      {...props}
    />
  );
}
