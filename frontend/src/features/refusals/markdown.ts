import { FIGURE_LABELS, remedyFor, type Refusal } from '@/features/refusals/schema';

/**
 * One refusal, or a page of them, as Markdown somebody can paste.
 *
 * **Built from the rows rather than from the rendered DOM, unlike
 * `lib/markdown-export.ts`, and the difference is what is being copied.** That
 * exporter exists for two pages of authored prose, where a parallel Markdown
 * template would be a second copy of the same sentences and would drift from
 * them — this repository has lost days to documents that were true when
 * written. A refusal is not prose. It is a row of data whose only authored
 * sentence is the message, and that sentence is stored verbatim, so there is no
 * second source of truth to drift from.
 *
 * What the DOM would add is presentation nobody wants in a paste: a request id
 * truncated to fit a column, an em dash standing in for a null, a relative
 * timestamp that stops meaning anything the moment it leaves the screen.
 *
 * The figures are walked rather than named, for the same reason the schema
 * declines to model them: the set differs per code and four more errors are
 * specified to carry one. A figure added next month appears in the paste
 * without anyone editing this file.
 */

const KNOWN_FIGURE_ORDER = [
  'estimated',
  'limit',
  'basis',
  'retry_after_seconds',
  'maximum_days',
  'required_gb',
  'available_gb',
  'capability',
  'available',
  'reason',
];

/** `composition` is a sentence, not a cell; it gets its own line below. */
const COMPOSITION = 'composition';

function cell(value: unknown): string {
  if (Array.isArray(value)) return value.map((v) => `\`${String(v)}\``).join(', ');
  if (value === null || value === undefined) return '—';
  // A pipe would end the cell it is in and shift every column after it.
  return String(value).replace(/\|/g, '\\|');
}

function figureRows(figures: Record<string, unknown>): [string, unknown][] {
  const keys = Object.keys(figures).filter((k) => k !== COMPOSITION);
  const known = KNOWN_FIGURE_ORDER.filter((k) => keys.includes(k));
  const rest = keys.filter((k) => !KNOWN_FIGURE_ORDER.includes(k)).sort();
  return [...known, ...rest].map((key) => [FIGURE_LABELS[key] ?? key, figures[key]]);
}

export function refusalToMarkdown(
  refusal: Refusal,
  { heading = '##', account }: { heading?: string; account?: string } = {},
): string {
  const rows: [string, unknown][] = [
    ['when', refusal.at],
    // Who, when the paste may be about somebody else. Their own name in their
    // own paste is noise, but a page an administrator copied is unreadable
    // without it.
    // The resolved name where the screen has one, and always the id: a paste
    // is read by somebody who was not looking at the screen, and quoted in an
    // investigation that needs the handle.
    ['account', account ? `${account} (${refusal.actor_id})` : refusal.actor_id],
    ['where', `\`${refusal.method} ${refusal.path}\` on ${refusal.surface}`],
    ['request id', refusal.request_id ? `\`${refusal.request_id}\`` : '—'],
  ];
  if (refusal.api_key_id) rows.push(['api key', `\`${refusal.api_key_id}\``]);
  rows.push(...figureRows(refusal.figures));

  const lines = [
    `${heading} ${refusal.status} \`${refusal.code}\``,
    '',
    // The message as a quotation, because that is what it is: the sentence the
    // platform gave the caller, reproduced rather than paraphrased.
    ...refusal.message.split('\n').map((line) => `> ${line}`),
    '',
    '| | |',
    '|---|---|',
    ...rows.map(([label, value]) => `| ${label} | ${cell(value)} |`),
  ];

  const composition = refusal.figures[COMPOSITION];
  if (typeof composition === 'string' && composition) {
    lines.push('', `**Where it went:** ${composition}`);
  }
  const remedy = remedyFor(refusal.code);
  if (remedy) lines.push('', `**What to try:** ${remedy}`);
  return lines.join('\n');
}

export function refusalsToMarkdown(
  refusals: Refusal[],
  context: {
    total: number;
    scopedToSelf: boolean;
    /**
     * Whether these are rows somebody ticked rather than the page as it stood.
     *
     * The two are different claims and the subtitle has to make the difference
     * plain. A whole page is a window on the matches — what was left out is
     * the rest of the window, and the reader can tell how much by the numbers.
     * A hand-picked set is a *choice*: three refusals out of fifty that
     * somebody selected for a reason, and nothing in the numbers says which
     * fifty-seven were passed over or why. Pasted into a ticket unlabelled it
     * is the more misleading of the two, so it is the one that says so.
     */
    picked?: boolean;
    filter?: string;
    sourceUrl?: string;
    accountOf?: (refusal: Refusal) => string;
  },
): string {
  // **The subtitle is not decoration.** A page of three refusals out of
  // fifty-seven, pasted with no note, reads as the whole of what happened —
  // and this screen narrows by default for anyone without `refusal:read_all`.
  // Saying what was left out is the difference between evidence and a
  // misleading excerpt.
  const shown = refusals.length;
  const scope = context.scopedToSelf ? 'your own account and its API keys' : 'all accounts';
  const filtered = context.filter ? `, filtered by ${context.filter}` : '';
  const count = context.picked
    ? `${shown} hand-picked out of ${context.total} matching`
    : `${shown} of ${context.total} shown`;
  const lines = ['# Refusals', '', `${count}, from ${scope}${filtered}.`];
  if (context.sourceUrl) lines.push('', `Copied from ${context.sourceUrl}`);
  for (const refusal of refusals) {
    lines.push('', '---', '', refusalToMarkdown(refusal, { account: context.accountOf?.(refusal) }));
  }
  return lines.join('\n');
}
