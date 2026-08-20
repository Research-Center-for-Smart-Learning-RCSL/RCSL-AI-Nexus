const SKIP_ATTRIBUTE = 'data-md-skip';

/** Characters that would otherwise start a Markdown construct mid-sentence. */
export function escapeInline(text: string): string {
  return text.replace(/([\\`*_[\]<>])/g, '\\$1');
}

export function collapse(text: string): string {
  return text.replace(/\s+/g, ' ');
}

export function isSkipped(node: Node): boolean {
  return node.nodeType === 1 && (node as Element).hasAttribute(SKIP_ATTRIBUTE);
}

/**
 * Inline content: everything that belongs on one line of Markdown.
 *
 * `code` wins over the emphasis inside it. A backtick span is literal by
 * definition, so emitting `**` within one would put two visible asterisks into
 * a snippet somebody is about to paste into a terminal.
 */
export function inline(node: Node): string {
  if (node.nodeType === 3)
    return escapeInline(collapse(node.textContent ?? ''));
  if (node.nodeType !== 1) return '';
  if (isSkipped(node)) return '';

  const element = node as Element;
  const children = Array.from(element.childNodes).map(inline).join('');

  switch (element.tagName) {
    case 'CODE': // Escaped text is wrong inside a code span, so the raw text is taken.
    // A snippet containing a backtick is fenced with two.
    {
      const raw = collapse(element.textContent ?? '');
      const fence = raw.includes('`') ? '``' : '`';
      const pad = raw.startsWith('`') || raw.endsWith('`') ? ' ' : '';
      return `${fence}${pad}${raw}${pad}${fence}`;
    }
    case 'STRONG':
    case 'B':
      return children.trim() ? `**${children.trim()}**` : '';
    case 'EM':
    case 'I':
      return children.trim() ? `*${children.trim()}*` : '';
    case 'A': {
      const href = element.getAttribute('href');
      const text = children.trim();
      if (!text) return '';
      // A relative href is meaningless once the file leaves the browser, so
      // the link text is kept and the target dropped rather than written as a
      // path that resolves nowhere.
      return href && /^https?:/i.test(href) ? `[${text}](${href})` : text;
    }
    case 'BR':
      return '\n';
    default:
      return children;
  }
}

export function inlineOf(element: Element): string {
  return Array.from(element.childNodes).map(inline).join('').trim();
}
