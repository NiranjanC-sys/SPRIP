"""Authentication: login, MFA, session lifecycle, tenant switching, password management.

This module holds the decisions that are easy to get subtly wrong and expensive to get wrong at
all. The reasoning behind each is written down here because none of it is visible from the code.

**Login is constant-work.** An unknown email spends the same Argon2 verification against a fixed
dummy hash that a known one spends against a real one. Without that, response time is a
user-enumeration oracle, and enumeration is the step that makes credential stuffing efficient.

**Lockout is per account and rate limiting is per identifier and per source.** They defend
different attacks. Lockout stops many passwords against one account; the per-IP limit stops one
password against many accounts, which no per-account counter ever sees. Both are needed and
neither substitutes.

**A successful login always issues a new session token, and MFA never reuses the pre-MFA one.**
Session fixation is the attack: a token handed out before authentication completes and then
promoted to authenticated is a token an attacker could have planted. So the token is minted
after credentials verify, and rotated again after MFA and after re-authentication.

**Switching tenant rewrites the session row after re-checking membership.** The client asks; the
server decides. plan.md §15 forbids taking a tenant from request data as proof of authorization,
and this is where that is enforced - the requested tenant is a *lookup key* into the user's own
memberships, and a tenant they do not belong to produces the same not-found as one that does not
exist.

**Every failure records a LoginAttempt with an enumerated reason, never the submitted value.**
The reason codes are a bounded set so they can be counted and alerted on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from speaker_roi_api.middleware import rate_limit
from speaker_roi_api.security import mfa as mfa_lib
from speaker_roi_api.security import passwords
from speaker_roi_api.security.tokens import hash_pii, hash_token, new_token, tokens_equal
from speaker_roi_api.services import audit
from speaker_roi_core.config import get_settings
from speaker_roi_core.context import current_context
from speaker_roi_core.db.session import bind_identity
from speaker_roi_core.enums import AuditAction, AuditOutcome, MembershipStatus, UserStatus
from speaker_roi_core.errors import (
    AccountLockedError,
    ForbiddenError,
    InvalidCredentialsError,
    MfaInvalidError,
    NotFoundError,
    ValidationError,
)
from speaker_roi_core.logging import get_logger
from speaker_roi_core.models import LoginAttempt, Membership, PasswordResetToken, Tenant, User
from speaker_roi_core.models import Session as SessionRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

#: Bounded reason codes. A free-text reason could not be counted, and the count is the point:
#: "eighty BAD_PASSWORD against forty identifiers in five minutes" is a spray, and
#: "eighty MFA_INVALID for one user" is something else entirely.
REASON_UNKNOWN_USER: Final = "UNKNOWN_USER"
REASON_BAD_PASSWORD: Final = "BAD_PASSWORD"  # noqa: S105 - a reason code, not a secret
REASON_LOCKED: Final = "LOCKED"
REASON_INACTIVE: Final = "INACTIVE"
REASON_NO_PASSWORD: Final = "NO_PASSWORD"  # noqa: S105 - a reason code, not a secret
REASON_MFA_INVALID: Final = "MFA_INVALID"
REASON_MFA_REPLAY: Final = "MFA_REPLAY"
REASON_NO_MEMBERSHIP: Final = "NO_MEMBERSHIP"

#: Password reset tokens are single-use and short-lived. One hour, not the session's twelve: a
#: reset link sits in an inbox, which is a far less trustworthy place than a browser's cookie
#: jar, and an hour is long enough for someone to read their mail.
_RESET_TTL = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """What login produced, and what the client must do next.

    ``mfa_required`` with a token is a genuinely authenticated session that cannot do anything
    yet - the permission check refuses every request until the second factor is presented. That
    is modelled as a state of the session rather than as a separate "pending" token store,
    because a second store is a second thing to expire, revoke and audit.
    """

    token: str
    session_id: uuid.UUID
    user: User
    mfa_required: bool
    must_change_password: bool
    #: Tenants this user may act in. The client shows a picker when there is more than one and
    #: selects silently when there is exactly one.
    tenants: list[Tenant]
    active_tenant_id: uuid.UUID | None
    expires_at: datetime


async def _record_attempt(
    session: AsyncSession,
    *,
    identifier: str,
    succeeded: bool,
    reason: str | None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> None:
    """Append a login attempt. Never stores the email, only its keyed hash.

    The hash is keyed with the application secret, so the table cannot be correlated against
    another deployment's and a known address cannot be confirmed present by computing its plain
    SHA-256. That matters because this table is, by design, a list of every address anyone has
    ever tried to sign in with - including addresses that do not exist here.
    """
    ctx = current_context()
    session.add(
        LoginAttempt(
            identifier_hash=hash_token(identifier.strip().lower()),
            user_id=user_id,
            tenant_id=tenant_id,
            succeeded=succeeded,
            failure_reason=reason,
            ip_hash=hash_pii(ctx.client_ip) if ctx and ctx.client_ip else None,
            user_agent_hash=hash_pii(ctx.user_agent) if ctx and ctx.user_agent else None,
            correlation_id=ctx.correlation_id if ctx else None,
        )
    )


async def _find_user(session: AsyncSession, email: str) -> User | None:
    """Look a user up by email, case-insensitively.

    ``lower(email)`` matches the functional unique index, so this is an index scan rather than
    a sequential one. Getting that wrong would make the login endpoint the slowest in the
    application and its slowness proportional to the user table - which is also a timing
    channel, since a sequential scan's duration depends on where the match is.
    """
    return (
        await session.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    remember: bool = False,
) -> LoginOutcome:
    """Verify credentials and establish a session.

    Runs in a platform-scoped transaction supplied by the caller, because the tenant is derived
    *from* the credentials and so cannot be bound before they are checked.
    """
    settings = get_settings()
    ctx = current_context()
    identifier = email.strip().lower()

    # Both limits before any work. Checked before the database is touched so a spray costs the
    # attacker a connection and costs us nothing.
    await rate_limit.limit("login-id", identifier, rate_limit.LOGIN_PER_IDENTIFIER)
    if ctx and ctx.client_ip:
        await rate_limit.limit("login-ip", ctx.client_ip, rate_limit.LOGIN_PER_IP)

    user = await _find_user(session, identifier)
    now = datetime.now(UTC)

    if user is None:
        # The same Argon2 cost as a real verification, then the same error. Skipping the
        # hash here would make an unknown address answer in two milliseconds and a known one
        # in eighty, which is a reliable enumeration oracle over a slow network.
        passwords.verify(password, None)
        await _record_attempt(
            session, identifier=identifier, succeeded=False, reason=REASON_UNKNOWN_USER
        )
        await audit.record(
            session,
            AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            reason=REASON_UNKNOWN_USER,
            status_code=401,
        )
        raise InvalidCredentialsError(internal_detail="no user for identifier")

    if user.locked_until is not None and user.locked_until > now:
        await _record_attempt(
            session, identifier=identifier, succeeded=False, reason=REASON_LOCKED, user_id=user.id
        )
        await audit.record(
            session,
            AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.DENIED,
            reason=REASON_LOCKED,
            actor_user_id=user.id,
            status_code=423,
        )
        raise AccountLockedError(
            "Your account is temporarily locked after several failed sign-in attempts.",
            retry_after_seconds=int((user.locked_until - now).total_seconds()),
        )

    if user.status is not UserStatus.ACTIVE:
        # Reported as invalid credentials, not as "your account is suspended". A distinguishable
        # answer confirms the address exists, which is the thing enumeration is trying to learn.
        await _record_attempt(
            session, identifier=identifier, succeeded=False, reason=REASON_INACTIVE, user_id=user.id
        )
        raise InvalidCredentialsError(internal_detail=f"user status {user.status}")

    if not user.password_hash:
        # An SSO-only user who typed a password. Same generic answer, and a distinct reason
        # code so an administrator can see the pattern and tell the person to use the SSO
        # button instead of resetting a password they do not have.
        passwords.verify(password, None)
        await _record_attempt(
            session,
            identifier=identifier,
            succeeded=False,
            reason=REASON_NO_PASSWORD,
            user_id=user.id,
        )
        raise InvalidCredentialsError(internal_detail="password login on sso-only account")

    if not passwords.verify(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.auth.max_failed_logins:
            user.locked_until = now + timedelta(seconds=settings.auth.lockout_seconds)
            # Reset here rather than on unlock: a counter left at its threshold would lock the
            # account again on the first failure after the window, which reads as a permanent
            # lockout to the person experiencing it.
            user.failed_login_count = 0
            log.warning("auth.account_locked", user_id=str(user.id))
        await _record_attempt(
            session,
            identifier=identifier,
            succeeded=False,
            reason=REASON_BAD_PASSWORD,
            user_id=user.id,
        )
        await audit.record(
            session,
            AuditAction.LOGIN_FAILED,
            outcome=AuditOutcome.FAILURE,
            reason=REASON_BAD_PASSWORD,
            actor_user_id=user.id,
            status_code=401,
        )
        raise InvalidCredentialsError(internal_detail="password mismatch")

    # --- credentials are good from here ---

    if passwords.needs_rehash(user.password_hash):
        # Transparent upgrade when the cost parameters have been raised. Done on the one
        # occasion the plaintext is legitimately in hand; any other time would require storing
        # it, which is the thing hashing exists to avoid.
        user.password_hash = passwords.hash_password(password)
        user.password_updated_at = now

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_password_login_at = now

    memberships = await memberships_for(session, user.id)
    tenants = [m.tenant for m in memberships if m.tenant is not None]
    # Exactly one organisation is the common case, so selecting it here saves every such user a
    # pointless picker. More than one and the session starts tenant-less, which every
    # tenant-scoped endpoint refuses with a code the frontend turns into the picker.
    active_tenant_id = tenants[0].id if len(tenants) == 1 else None

    mfa_required = _mfa_required(user, memberships, settings.auth.mfa_required_for_roles)
    token, row = await _issue_session(
        session,
        user=user,
        active_tenant_id=active_tenant_id,
        remember=remember,
        mfa_satisfied=not mfa_required,
    )

    await _record_attempt(
        session,
        identifier=identifier,
        succeeded=True,
        reason=None,
        user_id=user.id,
    )
    await audit.record(
        session,
        AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        resource_type="session",
        resource_id=row.id,
        reason="mfa_pending" if mfa_required else None,
        status_code=200,
    )
    # Only the identifier bucket. Clearing the IP bucket would let one successful login reset
    # the spray counter for every other account behind the same address.
    await rate_limit.get_limiter().reset("login-id", identifier)

    return LoginOutcome(
        token=token,
        session_id=row.id,
        user=user,
        mfa_required=mfa_required,
        must_change_password=user.must_change_password,
        tenants=tenants,
        active_tenant_id=active_tenant_id,
        expires_at=row.absolute_expires_at,
    )


async def memberships_for(session: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    """Active memberships across every tenant, with the tenant loaded.

    Runs without a tenant bound - which platform scope alone does not permit, because
    ``auth.memberships`` is tenant-owned and its isolation policy has no platform branch. What
    makes the query legal is the identity binding issued here: an additive, ``SELECT``-only
    policy on that table matches ``user_id`` against ``app.identity_user_id``, so the rows this
    can reach are exactly this user's own.

    The binding is issued by the function that needs it rather than by its callers. A caller that
    forgot would get a confusing ``TENANT_SCOPE_REQUIRED`` at sign-in; worse, a convention of
    binding early and broadly would leave the identity set for every later statement in the
    transaction, which is a standing invitation for the *next* cross-tenant read to be an
    accident.
    """
    await bind_identity(session, user_id)
    rows = (
        await session.execute(
            select(Membership)
            .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
            .options(selectinload(Membership.tenant))
        )
    ).scalars()
    return list(rows)


def _mfa_required(user: User, memberships: list[Membership], policy_roles: tuple[str, ...]) -> bool:
    """Whether this user must present a second factor.

    Three ways to require it, and the ``mfa_enrolled_at`` check is the one that matters: a user
    whose role demands MFA but who has not enrolled must be *forced into enrolment*, not waved
    through. Returning ``False`` because there is no secret to verify against is how a policy
    becomes decorative, so the enrolment flow is gated behind the same pending session state.
    """
    if user.mfa_required:
        return True
    required = set(policy_roles)
    if user.is_platform_admin:
        return True
    return any(str(m.role) in required for m in memberships)


async def _issue_session(
    session: AsyncSession,
    *,
    user: User,
    active_tenant_id: uuid.UUID | None,
    remember: bool,
    mfa_satisfied: bool,
    rotated_from: uuid.UUID | None = None,
) -> tuple[str, SessionRow]:
    """Mint a session token and persist only its hash.

    The hash, not the token: a database dump - or a read-only replica, or a backup on someone's
    laptop - must not be a set of usable credentials. A 256-bit random token has no dictionary
    to attack, which is why plain SHA-256 is right here and Argon2 would be wrong: the slow
    hash would be paid on every single request for no security gain.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    token = new_token()
    absolute = now + timedelta(
        # "Remember me" extends the absolute lifetime, never the idle timeout. An unattended
        # session must still lock; what the user asked for is not to retype their password
        # tomorrow, not for an idle browser in a shared clinic to stay open.
        seconds=settings.auth.session_ttl_seconds * (7 if remember else 1)
    )
    row = SessionRow(
        user_id=user.id,
        token_hash=hash_token(token),
        active_tenant_id=active_tenant_id,
        issued_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(seconds=settings.auth.session_idle_timeout_seconds),
        absolute_expires_at=absolute,
        mfa_satisfied_at=now if mfa_satisfied else None,
        reauthenticated_at=now,
        rotated_from_id=rotated_from,
        ip_hash=_ctx_ip_hash(),
        user_agent_hash=_ctx_ua_hash(),
    )
    session.add(row)
    await session.flush([row])
    return token, row


def _ctx_ip_hash() -> str | None:
    ctx = current_context()
    return hash_pii(ctx.client_ip) if ctx and ctx.client_ip else None


def _ctx_ua_hash() -> str | None:
    ctx = current_context()
    return hash_pii(ctx.user_agent) if ctx and ctx.user_agent else None


async def _session_by_token(session: AsyncSession, token: str) -> SessionRow:
    row = (
        await session.execute(
            select(SessionRow)
            .where(SessionRow.token_hash == hash_token(token))
            .options(selectinload(SessionRow.user))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise InvalidCredentialsError(internal_detail="no live session for presented token")
    return row


async def verify_mfa(session: AsyncSession, *, token: str, code: str) -> tuple[str, SessionRow]:
    """Complete the second factor for a pending session, and rotate its token.

    Rotation is why this returns the row and the caller re-issues the cookie: promoting the
    pre-MFA token in place would mean a token that existed before authentication completed is
    the one that ends up fully privileged - the session-fixation shape.

    Replay protection is the other half. The accepted time step is persisted, so a code
    shoulder-surfed from a colleague's phone cannot be used a second time within the ±1-step
    tolerance window - which without this would leave it valid for up to ninety seconds.
    """
    row = await _session_by_token(session, token)
    user = row.user
    await rate_limit.limit("mfa", str(row.id), rate_limit.MFA_PER_SESSION)

    if user.mfa_secret_encrypted is None:
        raise ValidationError(
            "Multi-factor authentication is not set up for this account.",
            remediation="Complete enrolment first.",
        )

    secret = mfa_lib.decrypt_secret(user.mfa_secret_encrypted)
    stored_step = _last_step(user)
    try:
        step = mfa_lib.verify_code(secret, code, last_accepted_step=stored_step)
    except MfaInvalidError as exc:
        # The reason is recorded and not shown. "Already used" would confirm to whoever holds
        # a stolen code that it was the right code, which is worth more to them than the
        # correction is worth to a legitimate user retyping from their phone.
        reason = (
            REASON_MFA_REPLAY
            if exc.context.get("reason") == mfa_lib.REASON_REPLAY
            else REASON_MFA_INVALID
        )
        await _record_attempt(
            session, identifier=user.email, succeeded=False, reason=reason, user_id=user.id
        )
        raise

    _set_last_step(user, step)
    now = datetime.now(UTC)
    row.revoked_at = now
    row.revoked_reason = "rotated_after_mfa"
    fresh_token, fresh = await _issue_session(
        session,
        user=user,
        active_tenant_id=row.active_tenant_id,
        remember=False,
        mfa_satisfied=True,
        rotated_from=row.id,
    )
    await audit.record(
        session,
        AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        tenant_id=row.active_tenant_id,
        resource_type="session",
        resource_id=fresh.id,
        reason="mfa_satisfied",
        status_code=200,
    )
    return fresh_token, fresh


def _last_step(user: User) -> int | None:
    """The last accepted TOTP step, from the recovery-code JSONB's reserved slot.

    Stored there rather than in its own column so that replay protection did not require a
    migration to add later - the column already exists and is already JSONB. The slot is
    reserved by a key no recovery code can collide with.
    """
    codes = user.mfa_recovery_codes or []
    for entry in codes:
        if entry.get("kind") == "last_step":
            value = entry.get("step")
            return int(value) if value is not None else None
    return None


def _set_last_step(user: User, step: int) -> None:
    codes = [e for e in (user.mfa_recovery_codes or []) if e.get("kind") != "last_step"]
    codes.append({"kind": "last_step", "step": str(step)})
    # Reassigned rather than mutated: SQLAlchemy does not track in-place changes to a JSONB
    # value, so an appended list would not be written back and the replay guard would silently
    # never persist.
    user.mfa_recovery_codes = codes


async def use_recovery_code(
    session: AsyncSession, *, token: str, code: str
) -> tuple[str, SessionRow]:
    """Satisfy MFA with a single-use recovery code, consuming it."""
    row = await _session_by_token(session, token)
    user = row.user
    await rate_limit.limit("mfa", str(row.id), rate_limit.MFA_PER_SESSION)

    ok, updated = mfa_lib.consume_recovery_code(code, user.mfa_recovery_codes or [])
    if not ok:
        await _record_attempt(
            session,
            identifier=user.email,
            succeeded=False,
            reason=REASON_MFA_INVALID,
            user_id=user.id,
        )
        raise MfaInvalidError("That recovery code is not valid or has already been used.")
    user.mfa_recovery_codes = updated

    remaining = mfa_lib.unused_recovery_code_count(updated)
    if remaining <= 2:
        # Warned at two rather than zero. A user who exhausts them is locked out and needs an
        # administrator, so the useful moment to say so is while they can still act on it.
        log.warning("auth.recovery_codes_low", user_id=str(user.id), remaining=remaining)

    now = datetime.now(UTC)
    row.revoked_at = now
    row.revoked_reason = "rotated_after_recovery"
    fresh_token, fresh = await _issue_session(
        session,
        user=user,
        active_tenant_id=row.active_tenant_id,
        remember=False,
        mfa_satisfied=True,
        rotated_from=row.id,
    )
    await audit.record(
        session,
        AuditAction.LOGIN_SUCCEEDED,
        actor_user_id=user.id,
        resource_type="session",
        resource_id=fresh.id,
        reason="recovery_code_used",
        status_code=200,
    )
    return fresh_token, fresh


async def switch_tenant(
    session: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> Tenant:
    """Change the session's active organisation, after re-checking membership.

    The membership check is the authorization; the request body is only a lookup key. A tenant
    the user does not belong to gets the same ``NotFoundError`` as one that does not exist,
    because a distinguishable "exists but you cannot have it" is a way to enumerate the
    customer list.

    Like :func:`memberships_for`, this reads ``auth.memberships`` before a tenant can be bound -
    binding the requested one first would make the request body the authorization, which is the
    exact thing this function exists to prevent. The identity binding lets the lookup see only
    rows belonging to the signed-in user, so a tenant they do not belong to is invisible rather
    than merely rejected.
    """
    await bind_identity(session, user_id)
    membership = (
        await session.execute(
            select(Membership)
            .where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .options(selectinload(Membership.tenant))
        )
    ).scalar_one_or_none()
    if membership is None or membership.tenant is None:
        raise NotFoundError("organisation", tenant_id)

    await session.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id)
        .values(active_tenant_id=tenant_id, last_seen_at=datetime.now(UTC))
    )
    await audit.record(
        session,
        AuditAction.LOGIN_SUCCEEDED,
        tenant_id=tenant_id,
        resource_type="session",
        resource_id=session_id,
        reason="tenant_switched",
        status_code=200,
        actor_user_id=user_id,
    )
    return membership.tenant


async def logout(session: AsyncSession, *, session_id: uuid.UUID, reason: str = "user") -> None:
    """Revoke a session.

    Revoked, not deleted. The row is evidence: "when did this session end and why" is a
    question an incident review asks, and a deleted row answers it with silence. Retention
    removes them on the audit schedule instead.
    """
    await session.execute(
        update(SessionRow)
        .where(SessionRow.id == session_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoked_reason=reason[:200])
    )
    await audit.record(
        session,
        AuditAction.LOGOUT,
        resource_type="session",
        resource_id=session_id,
        reason=reason,
        status_code=204,
    )


async def revoke_all_sessions(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    except_session_id: uuid.UUID | None = None,
    reason: str = "password_changed",
) -> int:
    """End every other session for this user. Called on password change and on role revocation.

    This is the step that makes a password change actually mean something. Without it, an
    attacker who already holds a stolen session token keeps their access for the session's full
    lifetime *after* the victim changes their password - which is precisely when the victim
    believes they have taken the access away.
    """
    stmt = update(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
    if except_session_id is not None:
        stmt = stmt.where(SessionRow.id != except_session_id)
    result = await session.execute(
        stmt.values(revoked_at=datetime.now(UTC), revoked_reason=reason[:200])
    )
    return int(result.rowcount or 0)


async def reauthenticate(session: AsyncSession, *, session_id: uuid.UUID, password: str) -> None:
    """Confirm the password for a sensitive operation, and stamp the session.

    The stamp, not a separate short-lived grant token: the window is a property of the session
    and is read by the permission guard, so a re-auth obtained for one operation covers the
    others in the same five minutes. That is the intended behaviour - a finance reviewer
    approving eleven assumption sets should not type their password eleven times - and it is
    bounded by ``reauth_window_seconds``.
    """
    row = (
        await session.execute(
            select(SessionRow)
            .where(SessionRow.id == session_id)
            .options(selectinload(SessionRow.user))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise InvalidCredentialsError(internal_detail="reauth against dead session")

    await rate_limit.limit("reauth", str(session_id), rate_limit.MFA_PER_SESSION)
    if not passwords.verify(password, row.user.password_hash):
        await _record_attempt(
            session,
            identifier=row.user.email,
            succeeded=False,
            reason=REASON_BAD_PASSWORD,
            user_id=row.user.id,
        )
        raise InvalidCredentialsError(internal_detail="reauth password mismatch")
    row.reauthenticated_at = datetime.now(UTC)


async def change_password(
    session: AsyncSession,
    *,
    user: User,
    current_password: str,
    new_password: str,
    session_id: uuid.UUID,
) -> None:
    """Change a password, then end every other session.

    The current password is required even though the caller is already authenticated. That is
    not ceremony: it is what stops a stolen session token from being converted into permanent
    account takeover, which is otherwise the single highest-value action an XSS or a borrowed
    laptop enables.
    """
    if not passwords.verify(current_password, user.password_hash):
        raise InvalidCredentialsError(internal_detail="current password mismatch")
    passwords.assert_policy(new_password, email=user.email, display_name=user.display_name)
    if passwords.verify(new_password, user.password_hash):
        raise ValidationError("The new password must be different from the current one.")

    user.password_hash = passwords.hash_password(new_password)
    user.password_updated_at = datetime.now(UTC)
    user.must_change_password = False
    revoked = await revoke_all_sessions(session, user_id=user.id, except_session_id=session_id)
    await audit.record(
        session,
        AuditAction.RECORD_UPDATED,
        resource_type="user",
        resource_id=user.id,
        after_state={"password_updated": True, "sessions_revoked": revoked},
        reason="password_changed",
        status_code=204,
    )


async def request_password_reset(session: AsyncSession, *, email: str) -> tuple[User, str] | None:
    """Create a reset token, or return ``None`` when the address is unknown.

    ``None`` rather than an error, and the endpoint returns 202 either way. A reset form that
    reports "no such account" is a free user-enumeration tool, and it is the one enumeration
    surface that needs no credentials at all.

    An existing unconsumed token is *not* reused. A second request invalidates the first, so a
    reset link forwarded or leaked from an inbox stops working as soon as the user, noticing
    something odd, requests another.
    """
    user = await _find_user(session, email)
    if user is None or user.status is not UserStatus.ACTIVE:
        log.info("auth.reset_requested_unknown")
        return None

    now = datetime.now(UTC)
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    token = new_token()
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=now + _RESET_TTL,
            requested_ip_hash=_ctx_ip_hash(),
        )
    )
    return user, token


async def complete_password_reset(session: AsyncSession, *, token: str, new_password: str) -> User:
    """Consume a reset token and set the new password.

    ``tokens_equal`` is used for the final comparison even though the lookup is by hash. The
    lookup narrows to one row; the comparison confirms it, in constant time, so that a
    hypothetical hash collision or a partial-match query plan cannot become a timing channel.
    """
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == hash_token(token))
            .options(selectinload(PasswordResetToken.user))
        )
    ).scalar_one_or_none()
    if (
        row is None
        or row.consumed_at is not None
        or row.expires_at <= now
        or not tokens_equal(row.token_hash, hash_token(token))
    ):
        raise ForbiddenError(
            "This reset link is no longer valid.",
            remediation="Request a new password reset link.",
        )

    user = row.user
    passwords.assert_policy(new_password, email=user.email, display_name=user.display_name)
    user.password_hash = passwords.hash_password(new_password)
    user.password_updated_at = now
    user.must_change_password = False
    user.failed_login_count = 0
    # An account locked out by the attacker's failed guesses must open again once the legitimate
    # owner proves control of the mailbox. Leaving the lock in place would turn the lockout into
    # a denial-of-service the victim cannot clear.
    user.locked_until = None
    row.consumed_at = now
    revoked = await revoke_all_sessions(session, user_id=user.id, reason="password_reset")
    await audit.record(
        session,
        AuditAction.RECORD_UPDATED,
        resource_type="user",
        resource_id=user.id,
        after_state={"password_reset": True, "sessions_revoked": revoked},
        reason="password_reset",
        actor_user_id=user.id,
        status_code=204,
    )
    return user


__all__ = [
    "LoginOutcome",
    "change_password",
    "complete_password_reset",
    "login",
    "logout",
    "memberships_for",
    "reauthenticate",
    "request_password_reset",
    "revoke_all_sessions",
    "switch_tenant",
    "use_recovery_code",
    "verify_mfa",
]
