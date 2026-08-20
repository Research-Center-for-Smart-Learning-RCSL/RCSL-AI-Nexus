import { inlineOf, isSkipped } from './inline';

export function listToMarkdown(
  list: Element,
  ordered: boolean,
  depth: number,
): string {
  const indent = '  '.repeat(depth);
  return Array.from(list.children)
    .filter((child) => child.tagName === 'LI' && !isSkipped(child))
    .map((item, index) => {
      const marker = ordered ? `${index + 1}.` : '-';
      // Nested lists are rendered as their own blocks and re-indented, so a
      // list inside a list keeps its structure instead of flattening.
      // Every descendant list this item owns, not only its direct children:
      // the clone below strips *all* of them, so re-emitting only direct
      // children silently deleted any list wrapped in a `div`. A list whose
      // nearest ancestor list is also inside this item belongs to a deeper
      // level and is reached by recursion instead.
      const nested = Array.from(item.querySelectorAll('ul, ol')).filter(
        (list) => {
          const parentList = list.parentElement?.closest('ul, ol') ?? null;
          return parentList === null || !item.contains(parentList);
        },
      );
      const own = inlineOf(
        (() => {
          const clone = item.cloneNode(true) as Element;
          clone.querySelectorAll('ul, ol').forEach((n) => n.remove());
          return clone;
        })(),
      );
      const sub = nested
        .map((child) =>
          listToMarkdown(child, child.tagName === 'OL', depth + 1),
        )
        .filter(Boolean)
        .join('\n');
      return [`${indent}${marker} ${own}`.trimEnd(), sub]
        .filter(Boolean)
        .join('\n');
    })
    .filter(Boolean)
    .join('\n');
}
