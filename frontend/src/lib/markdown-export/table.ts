import { inlineOf } from './inline';

export function tableToMarkdown(table: Element): string {
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
