"""TOTP verification and token generation.

`PyotpTotp.verify` exists because `pyotp.TOTP.verify` returns a boolean, and
replay prevention needs the accepted counter. These tests pin that it returns
the right one, which is what the conditional UPDATE upstream depends on.
"""

from __future__ import annotations

import time

import pyotp
import pytest

from app.adapters.crypto.pyotp_totp import STEP_SECONDS, PyotpTotp
from app.adapters.crypto.secret_box import FernetSecretBox, SecretDecryptionError
from app.domain.exceptions import InvalidTotpError
from app.domain.services.token_service import TokenService

SECRET = "JBSWY3DPEHPK3PXP"  # noqa: S105  (a test fixture)


def test_a_current_code_returns_its_counter() -> None:
    totp = PyotpTotp()
    expected = int(time.time()) // STEP_SECONDS

    assert totp.verify(SECRET, pyotp.TOTP(SECRET).now(), None) == expected


def test_one_step_of_clock_skew_is_accepted() -> None:
    totp = PyotpTotp()
    now = int(time.time())
    previous = pyotp.TOTP(SECRET).at(now - STEP_SECONDS)

    assert totp.verify(SECRET, previous, None) == (now // STEP_SECONDS) - 1


def test_two_steps_of_skew_are_not() -> None:
    totp = PyotpTotp()
    stale = pyotp.TOTP(SECRET).at(int(time.time()) - 3 * STEP_SECONDS)

    with pytest.raises(InvalidTotpError):
        totp.verify(SECRET, stale, None)


def test_a_counter_at_or_below_the_stored_one_is_refused() -> None:
    totp = PyotpTotp()
    current = int(time.time()) // STEP_SECONDS

    with pytest.raises(InvalidTotpError):
        totp.verify(SECRET, pyotp.TOTP(SECRET).now(), current)


def test_malformed_codes_are_rejected_without_hmac_work() -> None:
    totp = PyotpTotp()

    for candidate in ("", "12345", "abcdef", "1234567890"):
        with pytest.raises(InvalidTotpError):
            totp.verify(SECRET, candidate, None)


def test_a_code_typed_with_a_space_still_works() -> None:
    totp = PyotpTotp()
    current = pyotp.TOTP(SECRET).now()

    assert totp.verify(SECRET, f"{current[:3]} {current[3:]}", None) is not None


# --- secret box ----------------------------------------------------------


def test_a_secret_survives_a_round_trip() -> None:
    box = FernetSecretBox("a-test-key")
    assert box.decrypt(box.encrypt(SECRET)) == SECRET


def test_ciphertexts_differ_for_the_same_plaintext() -> None:
    """Fernet includes a random IV. Identical secrets producing identical
    ciphertext would let anyone with a database dump find shared values."""
    box = FernetSecretBox("a-test-key")
    assert box.encrypt(SECRET) != box.encrypt(SECRET)


def test_a_different_key_cannot_decrypt() -> None:
    ciphertext = FernetSecretBox("one-key").encrypt(SECRET)

    with pytest.raises(SecretDecryptionError):
        FernetSecretBox("another-key").decrypt(ciphertext)


# --- tokens --------------------------------------------------------------


def test_issued_tokens_are_unique_and_only_stored_hashed() -> None:
    tokens = TokenService()
    first, second = tokens.issue_token(), tokens.issue_token()

    assert first.plaintext != second.plaintext
    assert first.hashed != first.plaintext
    assert tokens.hash_token(first.plaintext) == first.hashed


def test_recovery_codes_avoid_ambiguous_characters() -> None:
    """These are transcribed by hand. `l` against `1` and `O` against `0` is
    where a recovery attempt turns into a support request."""
    codes = TokenService().issue_recovery_codes()

    assert len(codes) == 10
    for code in codes:
        assert not set(code.plaintext) & set("ilo01")


def test_recovery_code_hashing_ignores_case_and_separators() -> None:
    tokens = TokenService()
    code = tokens.issue_recovery_codes(count=1)[0]

    assert tokens.hash_recovery_code(code.plaintext.upper().replace("-", "")) == code.hashed
