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
