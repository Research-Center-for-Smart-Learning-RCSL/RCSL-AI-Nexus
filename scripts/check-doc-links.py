#!/usr/bin/env python3
"""Two invariants about links in this repository's markdown.

Both of these broke on 2026-08-30, when five oversized documents were split into
directories and every relative link had to move one level deeper.

1. **A relative link must resolve.** The obvious one, and the one a split is
   most likely to break.

2. **A path-shaped label must equal its target.** Markdown lets the two disagree
   silently, and the depth rewrite changed targets while leaving labels alone:
   seven links rendered as `../ARCHITECTURE.md` while pointing at
   `../../ARCHITECTURE.md`. Every one of them resolved, so check 1 was clean and
   the pages still lied to anyone reading or copying the displayed path. A label
   that is not path-shaped -- prose, a title, a bare filename, or the
   docs-root-relative `runbooks/restore.md` form this repository uses on
   purpose -- is not this check's business and is left alone.

What this deliberately does not check: heading anchors. Deriving GitHub's anchor
slugs for the CJK headings in `runbooks/` would produce failures nobody can act
on, and a gate that cries wolf is a gate somebody turns off. There is exactly
one anchored link in the repository today; if that file is ever split, its
anchor has to be checked by hand.

Runs on every tracked `.md` file, from the repository root, with the standard
library alone -- no network, no dependencies, nothing to install in CI.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r'\[([^\]]*)\]\(([^)\s]+?)(#[^)]*)?\)')
SKIP = ("http://", "https://", "mailto:", "tel:")
INLINE_CODE = re.compile(r'`[^`]*`')
FENCE = re.compile(r'^\s*(```|~~~)')


def prose_lines(text: str):
    """Yield (lineno, line) with code removed, because code is not links.

    A regex in a code block is the shape that fooled the first run of this
    check: `SEGMENT = r"[a-z0-9]([a-z0-9._-]*[a-z0-9])?"` is a bracket followed
    by a parenthesis, which is all a markdown link is. Fenced blocks are skipped
    whole and inline spans are blanked, so a documented command containing a
    link-shaped string cannot fail the build.
    """
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        yield lineno, INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line)


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [Path(p) for p in out.split("\0") if p]


def main() -> int:
    unresolved: list[str] = []
    mislabelled: list[str] = []
    links = 0

    for path in tracked_markdown():
        for lineno, line in prose_lines(path.read_text(encoding="utf-8")):
            for label, target, _anchor in LINK.findall(line):
                if target.startswith(SKIP) or not target:
                    continue
                links += 1
                if not (path.parent / target).resolve().exists():
                    unresolved.append(f"{path}:{lineno}: [{label}]({target}) does not resolve")
                # Only a label that looks like a path makes a claim about one.
                if label.startswith(("./", "../", "/")) and label != target:
                    mislabelled.append(
                        f"{path}:{lineno}: shows {label!r} but links to {target!r}"
                    )

    for problem in unresolved + mislabelled:
        print(f"  {problem}", file=sys.stderr)

    total = len(unresolved) + len(mislabelled)
    if total:
        print(
            f"\n{total} problem(s) in {links} relative links: "
            f"{len(unresolved)} unresolved, {len(mislabelled)} mislabelled.",
            file=sys.stderr,
        )
        return 1
    print(f"{links} relative links across {len(tracked_markdown())} files: all resolve, none mislabelled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
