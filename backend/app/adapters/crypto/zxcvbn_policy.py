"""Password strength, estimated rather than legislated.

Minimum length 12, zxcvbn score at least 3, and **no composition rules**. The
omission is the decision: requiring a digit and a symbol pushes people toward
`Password1!`, which satisfies every rule and is guessed instantly, while a
long passphrase that satisfies none is far stronger. See
docs/architecture/security.md section 5.3.

The two constants below must stay equal to `PASSWORD_MIN_LENGTH` and
`PASSWORD_MIN_SCORE` in frontend/src/features/auth/password-schema.ts. Both
sides implement zxcvbn 4.4.2 (this one through its Python port), so the scores
agree; if they ever diverge the failure is a form that accepts a password the
API then refuses, with an error the user has no way to act on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from zxcvbn import zxcvbn

from app.domain.exceptions import WeakPasswordError

_SEPARATORS = re.compile(r"[@._\-+\s]+")

MIN_USER_INPUT_LENGTH = 3
"""Fragments shorter than this match too much to be informative."""

MIN_LENGTH = 12
MIN_SCORE = 3
"""zxcvbn scores 0-4. 3 is "safely unguessable": survives an offline attack at
1e10 guesses per second."""

MAX_SCORED_LENGTH = 128
"""zxcvbn's matching is superlinear in length. Anything past this is already
far beyond the threshold, so it is length-checked and accepted rather than
handed to the estimator, which is otherwise a CPU sink on an unauthenticated
endpoint."""


class ZxcvbnPasswordPolicy:
    def assert_acceptable(self, password: str, *, user_inputs: Sequence[str] = ()) -> None:
        if len(password) < MIN_LENGTH:
            raise WeakPasswordError(f"Use at least {MIN_LENGTH} characters.")

        if len(password) > MAX_SCORED_LENGTH:
            return

        result = zxcvbn(password, user_inputs=_expand(user_inputs))
        if int(result["score"]) >= MIN_SCORE:
            return

        raise WeakPasswordError(_reason(result))


def _expand(user_inputs: Iterable[str]) -> list[str]:
    """Split each input into its parts as well as keeping it whole.

    zxcvbn matches `user_inputs` as whole dictionary entries, so passing only
    `jocelyn.tanaka@example.org` does not catch `jocelyn.tanaka2026`: the
    password contains the memorable part of the address and not the address.
    That is the form people actually choose, so the parts have to be offered
    too.

    **The local part is kept whole, punctuation included, and that is the
    entry that does the work.** Offering only `jocelyn` and `tanaka` leaves the
    dot between them unmatched, and zxcvbn charges a brute-force segment for
    it, which pushes `jocelyn.tanaka2026` from a score of 1 back up to 4.
    """
    expanded: list[str] = []
    for value in user_inputs:
        candidate = value.strip().lower()
        if not candidate:
            continue

        expanded.append(candidate)
        if "@" in candidate:
            expanded.append(candidate.split("@", 1)[0])

        expanded.extend(_SEPARATORS.split(candidate))
        # Run together as well, since `jocelyntanaka` is as likely a choice.
        expanded.append(_SEPARATORS.sub("", candidate))

    return sorted({v for v in expanded if len(v) >= MIN_USER_INPUT_LENGTH})


def _reason(result: dict[str, Any]) -> str:
    """Prefer the estimator's own words.

    Unlike every other message in this flow, guidance here helps a legitimate
    user and tells an attacker nothing they could not learn by trying.
    """
    feedback = result.get("feedback") or {}
    warning = (feedback.get("warning") or "").strip()
    suggestions = [s.strip() for s in (feedback.get("suggestions") or []) if s.strip()]

    parts = [p for p in (warning, *suggestions) if p]
    if not parts:
        return "Too easy to guess. Longer, or less predictable."
    return " ".join(parts)
