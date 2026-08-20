"""Password hashing, verification and policy.

Argon2id, with the parameters in configuration rather than in code so they can be raised on
better hardware without a code change. The encoded hash carries its own algorithm, salt and
cost parameters, which is what makes the upgrade path a rehash on next successful login rather
than a migration nobody dares to run.

Two things here are about timing rather than cryptography, and both are easy to lose in a
refactor. :func:`verify` is called even when the user does not exist, against a fixed dummy
hash, because "no such account" returning in 2ms and "wrong password" returning in 90ms is a
user-enumeration oracle that no amount of identical response bodies conceals. And the policy
check is a *list* of failures rather than the first one, because a form that reveals one rule
at a time trains users into weaker passwords by making them guess.
"""

from __future__ import annotations

import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from speaker_roi_core.config import get_settings
from speaker_roi_core.errors import FieldError, ValidationError
from speaker_roi_core.logging import get_logger

log = get_logger(__name__)

#: A real Argon2id hash of a value no one can present, used to spend the same work on an
#: unknown account as on a known one. Generated once at import with the configured
#: parameters, so it stays comparable when the cost settings change.
_DUMMY_PASSWORD = "not-a-password-and-never-will-be"  # noqa: S105 - the point is that it isn't

#: The most common passwords, normalised. A full breach corpus belongs in a service, not in a
#: Python module; this short list exists to catch the handful that dominate real attacks even
#: when the length rule is satisfied by padding.
_FORBIDDEN_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "password",
        "passw0rd",
        "qwerty",
        "letmein",
        "welcome",
        "admin123",
        "changeme",
        "iloveyou",
        "speakerroi",
    }
)

_hasher: PasswordHasher | None = None
_dummy_hash: str | None = None


def _get_hasher() -> PasswordHasher:
    """Build the hasher once, from settings.

    Cached at module scope rather than rebuilt per call: constructing a ``PasswordHasher`` is
    cheap, but a per-call construction is also a per-call opportunity for the parameters to
    diverge between the hash path and the verify path, which produces hashes that cannot be
    verified by the same process that wrote them.
    """
    global _hasher, _dummy_hash
    if _hasher is None:
        auth = get_settings().auth
        _hasher = PasswordHasher(
            time_cost=auth.argon2_time_cost,
            memory_cost=auth.argon2_memory_cost_kib,
            parallelism=auth.argon2_parallelism,
            hash_len=32,
            salt_len=16,
        )
        _dummy_hash = _hasher.hash(_DUMMY_PASSWORD)
    return _hasher


def reset_hasher_for_tests() -> None:
    """Drop the cached hasher so a test can lower the cost parameters and have it take."""
    global _hasher, _dummy_hash
    _hasher = None
    _dummy_hash = None


def normalise(password: str) -> str:
    """NFKC-normalise, so a password typed on a different keyboard still verifies.

    Unicode has several byte sequences for the same visible character, and an IME or a macOS
    keyboard may produce a different one than the Windows machine the password was set on.
    Without normalisation that is an account lockout with no diagnosable cause. Whitespace is
    *not* stripped: a leading space is a legitimate character, and silently removing it means
    a password that works here and fails in any other client.
    """
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    return _get_hasher().hash(normalise(password))


def verify(password: str, encoded_hash: str | None) -> bool:
    """Check a password, spending the same work whether or not the account exists.

    ``encoded_hash=None`` is the unknown-user and OIDC-only cases. Both verify against the
    dummy hash and return ``False``, so the caller cannot distinguish them by timing.
    """
    hasher = _get_hasher()
    candidate = encoded_hash or _dummy_hash
    assert candidate is not None  # set by _get_hasher
    try:
        hasher.verify(candidate, normalise(password))
    except (VerifyMismatchError, VerificationError):
        return False
    except InvalidHashError:
        # A stored value that is not a valid Argon2 hash. Corruption, a truncating column
        # change, or a hash written by different software. Refuse the login and say so
        # loudly - treating it as a mismatch would hide a real data problem behind a
        # support ticket about a forgotten password.
        log.error("auth.password_hash_unreadable")
        return False
    return encoded_hash is not None


def needs_rehash(encoded_hash: str) -> bool:
    """Whether a stored hash was made with weaker parameters than are configured now.

    Called after a *successful* verification, which is the only moment the plaintext is
    available to rehash with. Ignoring this means the cost parameters only ever apply to
    accounts created after the change.
    """
    try:
        return _get_hasher().check_needs_rehash(encoded_hash)
    except InvalidHashError:
        return True


def policy_failures(
    password: str, *, email: str | None = None, display_name: str | None
) -> list[str]:
    """Every way this password violates policy, as messages fit to show a user.

    Length comes from configuration; the rest are fixed. Composition rules (one upper, one
    digit, one symbol) are deliberately absent - they measurably push users toward
    ``Password1!`` while a length floor pushes them toward passphrases, and NIST SP 800-63B
    has recommended against them since 2017.
    """
    settings = get_settings().auth
    candidate = normalise(password)
    folded = candidate.casefold()
    failures: list[str] = []

    if len(candidate) < settings.password_min_length:
        failures.append(f"must be at least {settings.password_min_length} characters")
    if len(candidate) > 256:
        # An upper bound only because Argon2 hashes the whole input and a megabyte-long
        # password is a cheap way to make every login attempt expensive.
        failures.append("must be at most 256 characters")
    if candidate != candidate.strip() and not candidate.strip():
        failures.append("cannot be only whitespace")
    if any(bad in folded for bad in _FORBIDDEN_SUBSTRINGS):
        failures.append("contains a commonly guessed word")

    for label, value in (("email address", email), ("name", display_name)):
        if not value:
            continue
        # Local part only for the email: "a.patel@example.com" as a password should fail,
        # and so should "a.patel", but the shared domain must not fail every password at
        # the company.
        stem = value.split("@")[0].casefold()
        if len(stem) >= 4 and stem in folded:
            failures.append(f"cannot contain your {label}")

    if len(set(folded)) < 5:
        failures.append("uses too few distinct characters")
    return failures


def assert_policy(
    password: str, *, email: str | None = None, display_name: str | None = None
) -> None:
    """Raise a field-scoped :class:`ValidationError` listing every violated rule."""
    failures = policy_failures(password, email=email, display_name=display_name)
    if failures:
        raise ValidationError(
            "the password does not meet the policy",
            field_errors=[
                FieldError(("body", "password"), message, code="password_policy")
                for message in failures
            ],
        )


__all__ = [
    "assert_policy",
    "hash_password",
    "needs_rehash",
    "normalise",
    "policy_failures",
    "reset_hasher_for_tests",
    "verify",
]
