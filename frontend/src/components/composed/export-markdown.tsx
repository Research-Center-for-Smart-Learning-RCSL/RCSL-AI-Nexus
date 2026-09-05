'use client';

/**
 * Copy or download the page you are looking at, as Markdown.
 *
 * For the two pages an integrator is sent to. Both are read by somebody who is
 * about to go and do the work somewhere else — in a terminal, in a ticket, in a
 * message to a colleague who cannot reach this deployment at all — and until
 * now the only way to take them was to select the rendered text, which loses
 * every code block's boundaries.
 *
 * The Markdown is generated from the rendered DOM at the moment the button is
 * pressed, so it carries the live values these pages interpolate and cannot
 * disagree with what is on screen. See `lib/markdown-export.ts` for why that
 * matters more here than the slightly tidier output a hand-written copy would
 * have given.
 */

import { type RefObject } from 'react';
import { DownloadIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { CopySuccessIcon } from '@/components/composed/copy-success-icon';
import { elementToMarkdown } from '@/lib/markdown-export';
import { useCopyToClipboard } from '@/lib/use-copy-to-clipboard';

export function ExportMarkdown({
  contentRef,
  title,
  filename,
}: {
  /** The subtree to export. Anything inside it marked `data-md-skip` is left out. */
  contentRef: RefObject<HTMLElement | null>;
  title: string;
  /** Without the extension. */
  filename: string;
}) {
  const { copied, copy: writeToClipboard } = useCopyToClipboard();

  function build(): string | null {
    const root = contentRef.current;
    if (!root) return null;
    return elementToMarkdown(root, {
      title,
      // `href` rather than a hardcoded path: this application is served from
      // two entrances with different origins, and the export should name the
      // one the reader actually used.
      sourceUrl:
        typeof window === 'undefined' ? undefined : window.location.href,
    });
  }

  async function copy() {
    const markdown = build();
    // Failure is not surfaced here: the download button beside this one writes
    // the same bytes to a file and needs no permission.
    if (markdown) await writeToClipboard(markdown);
  }

  function download() {
    const markdown = build();
    if (!markdown) return;
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${filename}.md`;
    anchor.click();
    // Released on the next tick rather than immediately: revoking synchronously
    // has been observed to cancel the download in some browsers before it
    // starts.
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  return (
    <div className='flex flex-wrap items-center gap-2' data-md-skip>
      <Button variant='outline' size='sm' type='button' onClick={copy}>
        <CopySuccessIcon copied={copied} className="size-3.5" />
        {copied ? 'Copied' : 'Copy as Markdown'}
      </Button>
      <Button variant='outline' size='sm' type='button' onClick={download}>
        <DownloadIcon />
        Download .md
      </Button>
    </div>
  );
}
