export function fence(code: string): string {
  // A snippet containing a fence needs a longer one, which is rare and cheap
  // to handle correctly.
  const longest = [...code.matchAll(/`{3,}/g)].reduce(
    (max, match) => Math.max(max, match[0].length),
    2,
  );
  const bar = '`'.repeat(longest + 1);
  return `${bar}\n${code.replace(/\s+$/, '')}\n${bar}`;
}
