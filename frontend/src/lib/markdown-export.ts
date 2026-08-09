/**
 * Turns a rendered section of this application into Markdown.
 *
 * **Derived from the DOM rather than written alongside it, and that is the
 * whole design.** The obvious implementation is a second copy of each page as
 * a Markdown template, which is a source of truth nobody re-reads: this
 * repository has spent entire days on documents that were accurate when
 * written and silently stopped being so — a client setting removed six months
 * earlier, a proxy timeout corrected in one file and not another, a page
 * asserting a limit nobody had tried. A Markdown export generated from a
 * parallel string would join that list within a release.
 *
 * Reading the rendered output instead makes drift structurally impossible.
 * What the operator copies is what the operator was looking at, including the
 * values these pages interpolate live from the deployment — the gateway's own
 * base URL and capability list arrive in the export because they were already
 * on the screen, not because anything here knows about them.
 *
 * The vocabulary handled below is not general HTML. It is exactly the elements
 * these pages use, which is knowable because we author all of them: headings,
 * paragraphs, lists, definition lists, tables, preformatted blocks and inline
 * emphasis. An element with no case here contributes its text, which degrades
 * to something readable rather than to nothing.
 *
 * Anything that is interface rather than content — a copy button, the export
 * control itself — carries `data-md-skip` and is dropped.
 */

const SKIP_ATTRIBUTE = 'data-md-skip';

/** Characters that would otherwise start a Markdown construct mid-sentence. */
function escapeInline(text: string): string {
  return text.replace(/([\\`*_[\]<>])/g, '\\$1');
}

function collapse(text: string): string {
  return text.replace(/\s+/g, ' ');
}

function isSkipped(node: Node): boolean {
  return node.nodeType === 1 && (node as Element).hasAttribute(SKIP_ATTRIBUTE);
}

/**
 * Inline content: everything that belongs on one line of Markdown.
 *
 * `code` wins over the emphasis inside it. A backtick span is literal by
 * definition, so emitting `**` within one would put two visible asterisks into
 * a snippet somebody is about to paste into a terminal.
 */
function inline(node: Node): string {
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

function inlineOf(element: Element): string {
  return Array.from(element.childNodes).map(inline).join('').trim();
}

function fence(code: string): string {
  // A snippet containing a fence needs a longer one, which is rare and cheap
  // to handle correctly.
  const longest = [...code.matchAll(/`{3,}/g)].reduce(
    (max, match) => Math.max(max, match[0].length),
    2,
  );
  const bar = '`'.repeat(longest + 1);
  return `${bar}\n${code.replace(/\s+$/, '')}\n${bar}`;
}

function tableToMarkdown(table: Element): string {
  const rows = Array.from(table.querySelectorAll('tr'));
  if (rows.length === 0) return '';

  const cellsOf = (row: Element) =>
    Array.from(row.querySelectorAll('th, td')).map(
      (cell) =>
        // A pipe inside a cell would end the column early.
        inlineOf(cell).replace(/\|/g, '\\|').replace(/\n/g, ' ') || ' ',
    );

  const header = cellsOf(rows[0]);
  const body = rows.slice(1).map(cellsOf);
  const width = Math.max(header.length, ...body.map((r) => r.length), 1);
  const pad = (cells: string[]) =>
    `| ${Array.from({ length: width }, (_, i) => cells[i] ?? ' ').join(' | ')} |`;

  return [pad(header), `|${' --- |'.repeat(width)}`, ...body.map(pad)].join(
    '\n',
  );
}

function listToMarkdown(
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
      const nested = Array.from(item.children).filter(
        (child) => child.tagName === 'UL' || child.tagName === 'OL',
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

/**
 * Block content, in document order.
 *
 * Recursion happens through the containers this application actually nests —
 * `section`, `div` — so a wrapper introduced for layout does not hide the
 * content inside it from the export.
 */
function blocks(node: Node): string[] {
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
    case 'DD': {
      // Only reached through the `DL` case above, where a `dd` holding its own
      // paragraphs needs them separated rather than run together.
      const inner = Array.from(element.children).flatMap(blocks);
      return inner.length ? inner : [inlineOf(element)].filter(Boolean);
    }
    default: {
      const nested = Array.from(element.childNodes).flatMap(blocks);
      if (nested.length) return nested;
      // A container with no block children still holds text worth keeping.
      const text = inlineOf(element);
      return text ? [text] : [];
    }
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

  return (
    [...head, body].filter(Boolean).join('\n\n').replace(/\n{3,}/g, '\n\n') +
    '\n'
  );
}
