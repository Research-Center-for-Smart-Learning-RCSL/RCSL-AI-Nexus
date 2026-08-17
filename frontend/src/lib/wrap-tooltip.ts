/**
 * Break a native `title` into lines the browser will actually show.
 *
 * **A `title` does not wrap on its own.** Every tooltip on this platform is the
 * native one — no library, no portal, nothing to style — and a browser renders
 * it as a single line however long the string is. That is fine for the values
 * these started out carrying, a request id or a path, and wrong for the ones
 * they carry now: the stored `context_too_long` message is 287 characters, and
 * the audit log's `detail` is every key and value of an entry joined together.
 * What the reader gets is a strip of text wider than the window, clipped by the
 * screen edge, with the end of the sentence somewhere off it.
 *
 * A `title` *does* honour newlines, in every browser this deployment is reached
 * from, so wrapping is the whole fix. Nothing here styles anything.
 *
 * **Returns `undefined` for nothing, rather than an empty string.** React omits
 * the attribute entirely for `undefined`, and a `title=""` is a tooltip that
 * opens empty — which reads as a broken hover rather than as no hover.
 */

const DEFAULT_WIDTH = 72;

export function wrapTooltip(
  text: string | null | undefined,
  width: number = DEFAULT_WIDTH,
): string | undefined {
  if (!text) return undefined;
  const lines: string[] = [];

  // Existing newlines are hard breaks: a caller that already joined two facts
  // with one meant them on separate lines, and re-flowing them would run the
  // two together.
  for (const paragraph of text.split('\n')) {
    let line = '';
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      // A token longer than the whole width — a path, a base64 blob, a uuid
      // list — is broken rather than left to set the tooltip's width by
      // itself, which is the case this function exists for.
      let rest = word;
      while (rest.length > width) {
        if (line) {
          lines.push(line);
          line = '';
        }
        lines.push(rest.slice(0, width));
        rest = rest.slice(width);
      }
      if (!line) {
        line = rest;
      } else if (line.length + 1 + rest.length <= width) {
        line += ` ${rest}`;
      } else {
        lines.push(line);
        line = rest;
      }
    }
    lines.push(line);
  }

  return lines.join('\n');
}
