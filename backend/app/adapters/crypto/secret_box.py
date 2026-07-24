"""Encryption at rest for TOTP secrets.

A TOTP secret is a bearer credential: anyone holding it can mint valid codes
forever, and unlike a password it is never rotated by ordinary use. A database
dump that leaks the `users` table would otherwise defeat the second factor
entirely while leaving argon2 to protect the first, which is the wrong way
round. See docs/architecture/security.md section 5.3.

Fernet rather than raw AES-GCM: it carries its own versioning, IV handling and
authentication tag, and none of those are decisions worth re-taking here.

The key is derived from `TOTP_ENCRYPTION_KEY` with HKDF rather than used
directly, because Fernet requires exactly 32 bytes of url-safe base64 and the
configured value is a free-form string. **HKDF expands key material; it does
not stretch a passphrase.** The configured value must therefore be generated
randomly (`openssl rand -base64 32`), not chosen by a person. `config.py`
refuses the shipped placeholder in production, which catches the worst case
but not a weak hand-written one.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HKDF_INFO = b"rcsl-ai-nexus/totp-secret/v1"
"""Domain separation. Should another value ever be encrypted with the same
configured key, it derives a different subkey, so a ciphertext cannot be moved
between the two contexts."""


class SecretDecryptionError(Exception):
    """Raised when a stored ciphertext does not decrypt under the current key.

    Deliberately not a `DomainError`: this is never the caller's fault and must
    not be mapped to a 4xx. It means the key changed or the row was tampered
    with, and it should surface as a 500 and an operator alert.
    """


class FernetSecretBox:
    def __init__(self, key_material: str) -> None:
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=HKDF_INFO,
        ).derive(key_material.encode())
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise SecretDecryptionError("TOTP secret did not decrypt") from exc
