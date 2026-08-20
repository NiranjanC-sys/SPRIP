"""Opaque tokens, their hashes, and the JWTs issued to machines.

Two token families, for two different callers, and the split is the whole design.

**Browsers get an opaque random token in a cookie.** The server stores only its SHA-256, so a
database disclosure yields no usable sessions, and every request reads the session row - which
is what makes revocation immediate. plan.md §15 requires that disabling a user, revoking a
membership or reacting to an incident ends access *now*; a self-contained token cannot deliver
that until it expires, and "we shortened the expiry to five minutes" replaces the problem with
a refresh endpoint that has the same problem.

**Machines get a short-lived JWT.** A CI job or an ETL process has no cookie jar and no human
to re-authenticate, and its credential rotation is handled by rotating the client secret. Here
the trade is acceptable because the audience is small, enumerable, and does not include a
browser that could leak the token to a third-party script.

SHA-256 is the right hash for both token families and Argon2 is not. These are 256-bit random
values, so there is no dictionary to attack and nothing for a slow hash to protect against -
while a slow hash on the *session lookup* path would be paid on every single request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt

from speaker_roi_core.config import get_settings
from speaker_roi_core.errors import NotAuthenticatedError
from speaker_roi_core.logging import get_logger

log = get_logger(__name__)

#: 32 bytes, URL-safe base64 without padding. 256 bits of entropy: far past anything
#: brute-forceable, and short enough to sit in a cookie without approaching the 4KB limit
#: alongside the rest of a request's headers.
_TOKEN_BYTES: Final = 32

#: Issued JWTs are for machines only, and are deliberately short-lived. A service account that
#: needs a longer window should re-mint, which gives revocation a bounded blast radius.
_JWT_TTL_SECONDS: Final = 900

_ALGORITHM: Final = "HS256"

#: Distinguishes the two token kinds inside a JWT so a token minted for one purpose cannot be
#: presented for the other. Without it, a download-authorization token would be accepted as a
#: service-account credential by any endpoint that only checked the signature.
CLAIM_KIND: Final = "kind"

KIND_SERVICE: Final = "service"
KIND_DOWNLOAD: Final = "download"


def new_token() -> str:
    """A fresh opaque token, for a session, an invitation or a password reset."""
    return base64.urlsafe_b64encode(secrets.token_bytes(_TOKEN_BYTES)).decode("ascii").rstrip("=")


def hash_token(token: str) -> str:
    """The value stored in the database. Hex SHA-256, matching the ``Sha256`` column type."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(presented: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token against a stored hash.

    ``==`` on the hashes would leak, through timing, how many leading hex characters an
    attacker got right - which turns a 256-bit search into 64 independent 16-way searches.
    """
    return hmac.compare_digest(hash_token(presented), stored_hash)


def hash_pii(value: str | None) -> str | None:
    """Hash an IP address or user agent for storage.

    Both are personal data under GDPR and India's DPDP Act, and the only operation the system
    performs on them is equality - "is this the same client as last time" for anomaly
    detection. Keyed with the application secret so the hashes are not comparable across
    deployments and a leaked table cannot be reversed with a rainbow table over IPv4, which
    is only four billion entries.
    """
    if not value:
        return None
    key = get_settings().auth.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, value.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# JWT, for machine callers and signed download URLs
# ---------------------------------------------------------------------------


def _secret() -> str:
    return get_settings().auth.secret_key.get_secret_value()


def issue_service_token(
    *,
    api_key_id: uuid.UUID,
    tenant_id: uuid.UUID,
    permissions: frozenset[str],
    ttl_seconds: int = _JWT_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Mint a bearer token for a service account.

    The permissions are baked in rather than resolved per request, which is the one place
    this diverges from the browser path and the reason the TTL is 15 minutes rather than 12
    hours: a permission removed from the underlying API key takes effect when the token
    expires, and 15 minutes is a window an operator can live with during an incident.
    """
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(api_key_id),
        "tid": str(tenant_id),
        "perms": sorted(permissions),
        CLAIM_KIND: KIND_SERVICE,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM), expires


def issue_download_token(
    *,
    object_key: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    ttl_seconds: int = 300,
) -> str:
    """Authorize one download of one object, for five minutes.

    The object store's own presigned URL is what actually fetches the bytes; this token is
    the *authorization* step in front of it, so the audit trail records who was permitted to
    download what before any URL exists. Binding the key, the tenant and the user together
    means a token cannot be replayed against a different object or by a different account.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "key": object_key,
        CLAIM_KIND: KIND_DOWNLOAD,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str, *, expect_kind: str) -> dict[str, Any]:
    """Verify and decode a JWT, or raise :class:`NotAuthenticatedError`.

    ``algorithms`` is an explicit allowlist of one. Accepting the token's own ``alg`` header
    is how the ``alg: none`` and RS256-to-HS256 confusion attacks work, and passing the
    library a list it must match is the only reliable defence.

    The failure message never distinguishes expired from malformed from wrong-kind. The
    caller cannot act differently on any of them, and an oracle that separates "this
    signature is valid but the token is for something else" from "this signature is invalid"
    is a gift to anyone probing the token format.
    """
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            _secret(),
            algorithms=[_ALGORITHM],
            options={"require": ["exp", "iat", CLAIM_KIND]},
        )
    except jwt.PyJWTError as exc:
        log.info("auth.token_rejected", reason=type(exc).__name__)
        raise NotAuthenticatedError("the credential is not valid") from exc

    if claims.get(CLAIM_KIND) != expect_kind:
        log.warning(
            "auth.token_wrong_kind", presented=str(claims.get(CLAIM_KIND)), expected=expect_kind
        )
        raise NotAuthenticatedError("the credential is not valid")
    return claims


def new_recovery_codes(count: int = 10) -> tuple[list[str], list[dict[str, str]]]:
    """Generate MFA recovery codes: the plaintext to show once, and the hashes to store.

    Returned as a pair rather than stored by this function, because the plaintext must reach
    the response and *nothing else* - not a log line, not the returned model, not a retry of
    the same request. Making the caller hold both halves for one statement each keeps the
    window in which the plaintext exists visible in one screen of code.
    """
    plaintext = [
        f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
        for _ in range(count)
    ]
    stored = [{"hash": hash_token(code), "used_at": ""} for code in plaintext]
    return plaintext, stored


__all__ = [
    "CLAIM_KIND",
    "KIND_DOWNLOAD",
    "KIND_SERVICE",
    "decode_token",
    "hash_pii",
    "hash_token",
    "issue_download_token",
    "issue_service_token",
    "new_recovery_codes",
    "new_token",
    "tokens_equal",
]
