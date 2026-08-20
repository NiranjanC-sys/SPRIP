"""TOTP second factor: enrolment, verification, recovery codes, secret encryption.

RFC 6238 time-based codes, verified through ``pyotp`` with a one-step window. The window is
the interesting decision: zero steps rejects a user whose phone clock is eleven seconds slow,
which is common and looks like a broken feature; a wider window multiplies the number of codes
valid at any moment, and each additional step is a linear increase in an online guessing
attack's success rate against a six-digit space. One step - ±30 seconds - is the standard
compromise and is what every authenticator app is tested against.

The shared secret is encrypted at rest rather than stored in the clear. It is a bearer
credential: anyone holding it can generate valid codes forever, so a database disclosure that
exposed it would silently defeat MFA for every enrolled user with no way to detect the misuse.
Encryption is AES-GCM under a key derived from the application secret, so rotating that secret
forces re-enrolment - which is the correct, if inconvenient, consequence.

Replay is prevented by recording the last accepted time step. Without it, a code observed over
the user's shoulder or captured from a phishing page stays valid for up to ninety seconds, and
ninety seconds is plenty.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Final
from urllib.parse import quote

import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from speaker_roi_api.security.tokens import hash_token
from speaker_roi_core.config import get_settings
from speaker_roi_core.errors import MfaInvalidError, ValidationError
from speaker_roi_core.logging import get_logger

log = get_logger(__name__)

#: ±1 time step. See the module docstring - this number is a security parameter, not a
#: usability knob, and raising it should require the same review as changing a password rule.
#: Distinguishes the two ways a code can be refused. Both are :class:`MfaInvalidError` and
#: both tell the user the same thing, because "already used" versus "wrong" is not a
#: distinction worth handing to whoever is holding the code. The caller reads the reason to
#: record the right enumerated failure, which is where the distinction is actually useful.
REASON_REPLAY: Final = "REPLAY"
REASON_INVALID: Final = "INVALID"

VALID_WINDOW: Final = 1

#: 30 seconds, the interval every authenticator app assumes. Not configurable: a server that
#: used 60 would produce codes no standard app can generate, and the failure looks like a
#: user's phone being wrong.
STEP_SECONDS: Final = 30

_NONCE_BYTES: Final = 12
_KEY_INFO: Final = b"speaker-roi/mfa-secret/v1"


def _data_key() -> bytes:
    """Derive the MFA encryption key from the application secret.

    HKDF-style domain separation via a fixed ``info`` string, so this key cannot be
    substituted for the session-hashing key or the PII-hashing key even though all three come
    from the same configured secret. Using the secret directly for three purposes means a
    weakness in one becomes a weakness in all of them.
    """
    secret = get_settings().auth.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, _KEY_INFO, hashlib.sha256).digest()


def new_secret() -> str:
    """A fresh base32 TOTP secret, 160 bits as RFC 4226 §4 recommends."""
    return pyotp.random_base32(length=32)


def encrypt_secret(secret: str) -> bytes:
    """AES-GCM, nonce prepended. Authenticated, so a tampered ciphertext fails to decrypt.

    Authentication matters more here than confidentiality alone would suggest: an attacker
    with write access to the column but not read access could otherwise substitute a secret
    they know and take over the account, leaving the user's authenticator silently wrong.
    """
    nonce = _random_nonce()
    return nonce + AESGCM(_data_key()).encrypt(nonce, secret.encode("ascii"), None)


def _random_nonce() -> bytes:
    import secrets

    return secrets.token_bytes(_NONCE_BYTES)


def decrypt_secret(blob: bytes) -> str:
    """Recover a stored secret, or raise if the key has rotated or the row was tampered with.

    The failure is deliberately not caught here. A user whose secret cannot be decrypted must
    not be silently treated as un-enrolled - that would turn a key-rotation mistake into MFA
    being quietly off for everyone.
    """
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(_data_key()).decrypt(nonce, ciphertext, None).decode("ascii")


def provisioning_uri(secret: str, *, account: str) -> str:
    """The ``otpauth://`` URI the enrolment QR code encodes.

    Returned exactly once, in the response to the enrolment request, and never persisted or
    logged - it contains the secret in the query string, so a URI that reaches a log is a
    permanently compromised second factor.
    """
    issuer = get_settings().auth.mfa_issuer
    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    return totp.provisioning_uri(name=quote(account), issuer_name=issuer)


def current_step(at: float | None = None) -> int:
    """The RFC 6238 counter value, used for replay detection."""
    return int((at if at is not None else time.time()) // STEP_SECONDS)


def verify_code(
    secret: str,
    code: str,
    *,
    last_accepted_step: int | None = None,
) -> int:
    """Verify a TOTP code and return the step it matched, or raise.

    ``last_accepted_step`` is the replay guard. A code from a step at or before the last one
    accepted for this user is refused even though it is arithmetically valid, which closes the
    up-to-90-second replay window that a shoulder-surfed or phished code otherwise has.

    Returns the matched step so the caller can persist it. Callers that discard the return
    value have silently disabled replay protection, which is why this returns a value at all
    rather than a bool.
    """
    cleaned = code.strip().replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != 6:
        raise ValidationError("the verification code must be six digits")

    totp = pyotp.TOTP(secret, interval=STEP_SECONDS)
    now = time.time()
    for offset in range(-VALID_WINDOW, VALID_WINDOW + 1):
        candidate_time = now + offset * STEP_SECONDS
        if not totp.verify(cleaned, for_time=candidate_time, valid_window=0):
            continue
        step = current_step(candidate_time)
        if last_accepted_step is not None and step <= last_accepted_step:
            log.warning("auth.mfa_code_replayed", step=step, last=last_accepted_step)
            raise MfaInvalidError(
                "that verification code has already been used",
                context={"reason": REASON_REPLAY},
            )
        return step

    raise MfaInvalidError("the verification code is not valid", context={"reason": REASON_INVALID})


def consume_recovery_code(
    code: str, stored: list[dict[str, str]] | None
) -> tuple[bool, list[dict[str, str]]]:
    """Spend a single-use recovery code, returning whether it matched and the updated list.

    The whole list is returned rather than mutated in place so the caller writes it back in
    one statement inside the same transaction as the login. A mutation whose persistence is a
    separate step is a code that can be used twice if the second step fails.

    Marking used rather than deleting: a support conversation about "I used my last recovery
    code in March" needs the record, and the hash of a spent code discloses nothing.
    """
    if not stored:
        return False, []
    presented = hash_token(code.strip().replace(" ", ""))
    updated = [dict(entry) for entry in stored]
    for entry in updated:
        if entry.get("used_at"):
            continue
        if hmac.compare_digest(entry.get("hash", ""), presented):
            entry["used_at"] = _now_iso()
            return True, updated
    return False, updated


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def unused_recovery_code_count(stored: list[dict[str, str]] | None) -> int:
    """How many recovery codes remain, so the UI can prompt for regeneration near zero."""
    return sum(1 for entry in stored or () if not entry.get("used_at"))


def secret_fingerprint(secret: str) -> str:
    """A short, non-reversible identifier for a secret, safe to log.

    Needed for exactly one diagnosis: distinguishing "the user enrolled twice and is using
    the older authenticator entry" from "the code is wrong". Eight hex characters is enough
    to compare two secrets and far too few to attack one.
    """
    return base64.b16encode(hashlib.sha256(secret.encode("ascii")).digest()[:4]).decode("ascii")


__all__ = [
    "STEP_SECONDS",
    "VALID_WINDOW",
    "consume_recovery_code",
    "current_step",
    "decrypt_secret",
    "encrypt_secret",
    "new_secret",
    "provisioning_uri",
    "secret_fingerprint",
    "unused_recovery_code_count",
    "verify_code",
]
