import { fence } from './code';
import { inline, inlineOf, isSkipped } from './inline';
import { listToMarkdown } from './list';
import { tableToMarkdown } from './table';

const BLOCK_TAGS = new Set([
  'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'P', 'PRE', 'UL', 'OL', 'TABLE', 'DL', 'DD', 'DT',
  'DIV', 'SECTION', 'ARTICLE', 'ASIDE', 'MAIN', 'HEADER', 'FOOTER',
  'FIGURE', 'BLOCKQUOTE', 'FORM', 'FIELDSET', 'HR', 'NAV',
]);
/** Everything else is inline, which is the right default for markup we author. */

/**
 * A container holding prose *and* elements, in document order.
 *
 * Runs of inline nodes become one paragraph; a block-level child is emitted as
 * its own block. **Walking `children` instead — which is what this did until
 * 2026-08-09 — discards every text node**, because `children` is elements only.
 * A definition like "Delete the `model` and `model_provider` lines from
 * `~/.codex/config.toml`." exported as three fragments with all the prose
 * between them missing, and the code spans stripped of their backticks: each
 * `code` element was reached as a *container* rather than as inline content, so
 * the `CODE` case never ran and its text was backslash-escaped instead.
 *
 * The module's own comment claimed an unhandled structure degrades "to
 * something readable rather than to nothing". It did not; it degraded to
 * something worse than nothing, which is a fragment that looks like a complete
 * instruction. The two pages carrying an export button hold 37 definition
 * descriptions and nearly all of them mix prose with `code`.
 */
function mixedContent(element: Element): string[] {
  const out: string[] = [];
  let run: Node[] = [];

  function flush(): void {
    if (run.length === 0) return;
    const text = run.map(inline).join('').trim();
    run = [];
    if (text) out.push(text);
  }

  for (const child of Array.from(element.childNodes)) {
    if (child.nodeType === 1 && BLOCK_TAGS.has((child as Element).tagName)) {
      flush();
      out.push(...blocks(child));
    } else {
      run.push(child);
    }
  }
  flush();
  return out;
}

/**
 * Block content, in document order.
 *
 * Recursion happens through the containers this application actually nests —
 * `section`, `div` — so a wrapper introduced for layout does not hide the
 * content inside it from the export.
 */
export function blocks(node: Node): string[] {
  if (node.nodeType !== 1 || isSkipped(node)) return [];
  const element = node as Element;

  switch (element.tagName) {
    case 'H1':
    case 'H2':
    case 'H3':
    case 'H4':
    case 'H5':
    case 'H6': {
      const text = inlineOf(element);
      const level = Number(element.tagName[1]);
      return text ? [`${'#'.repeat(level)} ${text}`] : [];
    }
    case 'P': {
      const text = inlineOf(element);
      return text ? [text] : [];
    }
    case 'PRE': {
      const code = element.textContent ?? '';
      return code.trim() ? [fence(code)] : [];
    }
    case 'UL':
    case 'OL': {
      const list = listToMarkdown(element, element.tagName === 'OL', 0);
      return list ? [list] : [];
    }
    case 'TABLE': {
      const table = tableToMarkdown(element);
      return table ? [table] : [];
    }
    case 'DL': {
      // Markdown has no definition list. These pages use `dl` as a two-column
      // reference — a term and an explanation — so each pair becomes a bullet
      // with the term in bold, which reads correctly everywhere and survives
      // a `dd` that contains several paragraphs.
      const out: string[] = [];
      let term = '';
      for (const child of Array.from(element.children)) {
        if (isSkipped(child)) continue;
        if (child.tagName === 'DT') term = inlineOf(child);
        if (child.tagName === 'DD') {
          const body = blocks(child).length ? blocks(child) : [inlineOf(child)];
          const [first, ...rest] = body.filter(Boolean);
          out.push(
            [
              `- **${term}** — ${first ?? ''}`.trimEnd(),
              ...rest.map((line) => `\n  ${line.split('\n').join('\n  ')}`),
            ].join(''),
          );
        }
      }
      return out.length ? [out.join('\n')] : [];
    }
    case 'DD':
      return mixedContent(element);
    default:
      return mixedContent(element);
  }
}

/**
 * The document a reader gets, with a provenance line they can act on.
 *
 * The heading and source URL are prepended rather than assumed to be in the
 * markup, because the page title lives in the route and the export is taken
 * from the content below it. `origin` is included so a file that has travelled
 * says which deployment produced it — the figures in these pages are that
 * deployment's own, and a copy read against a different one would be wrong in
 * ways nothing on the page would reveal.
 */
