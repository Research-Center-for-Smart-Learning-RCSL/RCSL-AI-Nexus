import { blocks } from './markdown-export/block';

export function elementToMarkdown(
  root: HTMLElement,
  options: { title?: string; sourceUrl?: string; generatedAt?: Date } = {},
): string {
  const body = Array.from(root.childNodes)
    .flatMap(blocks)
    .map((block) => block.trim())
    .filter(Boolean)
    .join('\n\n');

  const head: string[] = [];
  if (options.title) head.push(`# ${options.title}`);
  if (options.sourceUrl) {
    const stamp = (options.generatedAt ?? new Date())
      .toISOString()
      .slice(0, 10);
    head.push(`Exported from ${options.sourceUrl} on ${stamp}.`);
  }

  // Joined, not tidied. A trailing `replace(/\n{3,}/g, ...)` over the whole
  // document also rewrote the inside of fenced blocks, so a snippet containing
  // two blank lines came out altered — against this module's one hard promise,
  // that a code block reaches the reader exactly as it was on screen. Blocks
  // are trimmed individually above, which is what the collapse was for.
  return [...head, body].filter(Boolean).join('\n\n') + '\n';
}
