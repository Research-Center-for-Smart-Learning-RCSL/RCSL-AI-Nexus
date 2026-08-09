/**
 * The Markdown export, tested on the markup the two exporting pages use.
 *
 * The risk is not that a heading loses its hashes. It is that content silently
 * fails to appear: an element with no case falls through to its text, so a
 * structure this file does not cover degrades quietly rather than failing, and
 * a snippet dropped from an integration guide is the kind of defect that is
 * discovered by somebody who followed the file and got a broken client.
 *
 * So the assertions are mostly presence and boundaries, not formatting.
 */

import { describe, expect, it } from 'vitest';

import { elementToMarkdown } from '@/lib/markdown-export';

function render(html: string): string {
  const root = document.createElement('div');
  root.innerHTML = html;
  return elementToMarkdown(root);
}

describe('elementToMarkdown', () => {
  it('keeps a code block whole and fenced', () => {
    const config = 'model = "code"\nwire_api = "responses"';
    const markdown = render(`<pre>${config}</pre>`);

    expect(markdown).toContain('```');
    expect(markdown).toContain('model = "code"');
    expect(markdown).toContain('wire_api = "responses"');
    // The newline inside the snippet has to survive: a config file collapsed
    // onto one line is the failure this format exists to prevent.
    expect(markdown).toMatch(/model = "code"\nwire_api = "responses"/);
  });

  it('drops interface chrome marked data-md-skip', () => {
    const markdown = render(
      '<div><pre>npm install -g @openai/codex</pre>' +
        '<button data-md-skip>Copy config.toml</button></div>',
    );

    expect(markdown).toContain('npm install -g @openai/codex');
    expect(markdown).not.toContain('Copy config.toml');
  });

  it('finds content nested inside layout wrappers', () => {
    // Both pages wrap sections in divs for spacing. A serializer that only
    // looked at direct children would export almost nothing.
    const markdown = render(
      '<section><div><div><p>Deeply nested but still content.</p></div></div></section>',
    );

    expect(markdown).toContain('Deeply nested but still content.');
  });

  it('renders a definition list as terms and descriptions', () => {
    const markdown = render(
      '<dl><dt>401</dt><dd>Wrong, expired or revoked key.</dd>' +
        '<dt>429</dt><dd>The per-minute limit.</dd></dl>',
    );

    expect(markdown).toContain('**401** — Wrong, expired or revoked key.');
    expect(markdown).toContain('**429** — The per-minute limit.');
  });

  it('renders a table with a header separator', () => {
    const markdown = render(
      '<table><thead><tr><th>Code</th><th>Meaning</th></tr></thead>' +
        '<tbody><tr><td>503</td><td>No model</td></tr></tbody></table>',
    );

    expect(markdown).toContain('| Code | Meaning |');
    expect(markdown).toContain('| --- | --- |');
    expect(markdown).toContain('| 503 | No model |');
  });

  it('does not emphasise inside a code span', () => {
    // `**` inside backticks would be pasted literally into a terminal.
    const markdown = render('<p><code>wire_api = "responses"</code></p>');

    expect(markdown).toContain('`wire_api = "responses"`');
    expect(markdown).not.toContain('**');
  });

  it('escapes text that would otherwise be read as markup', () => {
    const markdown = render('<p>Use https://&lt;gateway&gt;/v1 as the base.</p>');

    expect(markdown).toContain('\\<gateway\\>');
  });

  it('keeps link text when the target is relative', () => {
    // A relative href resolves nowhere once the file has left the browser.
    const markdown = render('<p><a href="/api-docs">the API reference</a></p>');

    expect(markdown).toContain('the API reference');
    expect(markdown).not.toContain('](/api-docs)');
  });

  it('keeps absolute links as links', () => {
    const markdown = render('<p><a href="https://example.test/x">docs</a></p>');

    expect(markdown).toContain('[docs](https://example.test/x)');
  });

  it('carries interpolated live values through unchanged', () => {
    // The reason the export is taken from the DOM at all: the base URL and the
    // capability are this deployment's, and they are already on the screen.
    const markdown = render(
      '<p>Base URL <code>https://llmapi.example.test/v1</code>, capability ' +
        '<code>code</code>.</p>',
    );

    expect(markdown).toContain('`https://llmapi.example.test/v1`');
    expect(markdown).toContain('`code`');
  });

  it('numbers an ordered list and bullets an unordered one', () => {
    expect(render('<ol><li>First</li><li>Second</li></ol>')).toContain(
      '1. First',
    );
    expect(render('<ol><li>First</li><li>Second</li></ol>')).toContain(
      '2. Second',
    );
    expect(render('<ul><li>Alpha</li></ul>')).toContain('- Alpha');
  });

  it('prepends the title and the origin the reader used', () => {
    const root = document.createElement('div');
    root.innerHTML = '<p>Body.</p>';

    const markdown = elementToMarkdown(root, {
      title: 'Connect an agent',
      sourceUrl: 'https://llm.example.test/agent-setup',
      generatedAt: new Date('2026-08-09T10:00:00Z'),
    });

    expect(markdown.startsWith('# Connect an agent')).toBe(true);
    // Which deployment produced the file: its figures are that deployment's,
    // and a copy read against another would be wrong invisibly.
    expect(markdown).toContain('https://llm.example.test/agent-setup');
    expect(markdown).toContain('2026-08-09');
  });

  it('ends with exactly one trailing newline and no blank-line runs', () => {
    const markdown = render(
      '<section><p>One.</p></section><section><p>Two.</p></section>',
    );

    expect(markdown.endsWith('One.\n\nTwo.\n')).toBe(true);
    expect(markdown).not.toMatch(/\n{3,}/);
  });
});
