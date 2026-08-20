"""Authentication endpoints, and the cookie policy that makes them safe in a browser.

The cookie is where most of the security of this router lives, so the attributes are set in one
place and explained here rather than repeated at four call sites.

``HttpOnly`` - unreadable by page script, so an XSS can *act* as the user for as long as the page
is open but cannot exfiltrate a credential that outlives it. ``Secure`` - never sent over plain
HTTP, so a downgraded link cannot leak it. ``SameSite=Lax`` - not sent on cross-site POSTs, which
is the cheap half of CSRF protection; the expensive half is that state-changing endpoints require
either a JSON content type or an explicit header, both of which a cross-site form cannot set.
``Path`` scoped to the API prefix - so the cookie is not attached to requests for static assets,
which is both fewer bytes and one fewer place it can be logged by a CDN.

Two endpoints here are unauthenticated by necessity - login and password reset - and both are
rate limited by identifier *and* by source address before touching the database. The reset
endpoint additionally answers 202 whether or not the address exists, because a reset form that
distinguishes them is the easiest user-enumeration tool in any application.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from speaker_roi_api.deps import CurrentPrincipal, EnrollingPrincipal, SettingsDep
from speaker_roi_api.middleware import rate_limit
from speaker_roi_api.schemas import auth as sch
from speaker_roi_api.security import mfa as mfa_lib
from speaker_roi_api.security.tokens import new_recovery_codes
from speaker_roi_api.services import audit
from speaker_roi_api.services import auth as svc
from speaker_roi_core.config import Settings, get_settings
from speaker_roi_core.context import bind, current_context
from speaker_roi_core.db.session import platform_session_scope
from speaker_roi_core.enums import AuditAction, AuditOutcome
from speaker_roi_core.errors import NotAuthenticatedError, ValidationError
from speaker_roi_core.logging import get_logger
from speaker_roi_core.models import Membership, Tenant, User
from speaker_roi_core.models import Session as SessionRow

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(
    response: Response, token: str, settings: Settings, *, expires_at: datetime
) -> None:
    """Attach the session cookie with the full attribute set.

    ``max_age`` is derived from the session's own absolute expiry rather than configured
    separately, so the browser forgets the cookie at the same moment the server stops honouring
    it. Two independently configured lifetimes drift, and the drift shows up as a user who
    appears signed in and receives 401 on every request.
    """
    max_age = max(int((expires_at - datetime.now(UTC)).total_seconds()), 0)
    response.set_cookie(
        settings.auth.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth.cookie_secure,
        samesite=settings.auth.cookie_samesite,
        domain=settings.auth.cookie_domain,
        path=settings.api_prefix or "/",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    """Delete the cookie, with the *same* domain and path it was set with.

    Mismatched attributes produce a second cookie of the same name rather than removing the
    first, and the browser then sends both - so the user stays signed in after clicking sign
    out, which is the kind of bug that is only ever found by a security review.
    """
    response.delete_cookie(
        settings.auth.session_cookie_name,
        domain=settings.auth.cookie_domain,
        path=settings.api_prefix or "/",
        httponly=True,
        secure=settings.auth.cookie_secure,
        samesite=settings.auth.cookie_samesite,
    )


def _tenant_summary(tenant: Tenant, role: str | None = None) -> sch.TenantSummary:
    return sch.TenantSummary(
        id=tenant.id, name=tenant.name, code=tenant.code, status=str(tenant.status), role=role
    )


def _session_user(user: User) -> sch.SessionUser:
    return sch.SessionUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_platform_admin=user.is_platform_admin,
        mfa_enrolled=user.mfa_enrolled_at is not None,
    )


@router.post(
    "/login",
    response_model=sch.LoginResponse,
    summary="Sign in with email and password",
    responses={
        401: {"description": "Wrong credentials, or a second factor is outstanding."},
        423: {"description": "Locked after repeated failures. Honour `retry_after_seconds`."},
    },
)
async def login(
    body: sch.LoginRequest, response: Response, settings: SettingsDep
) -> sch.LoginResponse:
    """Verify credentials, establish a session, and set the session cookie.

    Runs in a platform-scoped transaction because the tenant is *derived from* the credentials -
    there is nothing to bind a tenant to until the user is known. This is one of the two places
    in the application that legitimately operates without a tenant bound, and the reason is
    recorded in the transaction so the audit of platform-scope usage stays honest.
    """
    async with platform_session_scope(reason="authenticate credentials") as db:
        outcome = await svc.login(
            db, email=body.email, password=body.password, remember=body.remember
        )
        role_by_tenant = {
            m.tenant_id: str(m.role) for m in await svc.memberships_for(db, outcome.user.id)
        }
        payload = sch.LoginResponse(
            user=_session_user(outcome.user),
            mfa_required=outcome.mfa_required,
            mfa_enrolment_required=(outcome.mfa_required and outcome.user.mfa_enrolled_at is None),
            must_change_password=outcome.must_change_password,
            tenants=[_tenant_summary(t, role_by_tenant.get(t.id)) for t in outcome.tenants],
            active_tenant_id=outcome.active_tenant_id,
            expires_at=outcome.expires_at,
        )
        _set_session_cookie(response, outcome.token, settings, expires_at=outcome.expires_at)
    return payload


@router.post(
    "/mfa/verify",
    response_model=sch.LoginResponse,
    summary="Complete the second factor",
)
async def verify_mfa(
    body: sch.MfaVerifyRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
) -> sch.LoginResponse:
    """Verify a TOTP code and rotate the session token.

    The token is read from the cookie directly rather than through the usual principal
    dependency, because that dependency refuses a session whose second factor is outstanding -
    which is precisely the state this endpoint exists to leave.
    """
    token = _pending_token(request, settings)
    async with platform_session_scope(reason="complete second factor") as db:
        fresh_token, fresh = await svc.verify_mfa(db, token=token, code=body.code)
        payload = await _post_mfa_payload(db, fresh)
        # The *new* token, from the rotated row. Re-setting the old one would leave the client
        # holding a token this transaction just revoked.
        _set_session_cookie(response, fresh_token, settings, expires_at=fresh.absolute_expires_at)
    return payload


@router.post(
    "/mfa/recovery",
    response_model=sch.LoginResponse,
    summary="Complete the second factor with a recovery code",
)
async def use_recovery_code(
    body: sch.RecoveryCodeRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
) -> sch.LoginResponse:
    """Spend a single-use recovery code. For a lost or reset authenticator."""
    token = _pending_token(request, settings)
    async with platform_session_scope(reason="recovery code sign-in") as db:
        fresh_token, fresh = await svc.use_recovery_code(db, token=token, code=body.code)
        payload = await _post_mfa_payload(db, fresh)
        _set_session_cookie(response, fresh_token, settings, expires_at=fresh.absolute_expires_at)
    return payload


def _pending_token(request: Request, settings: Settings) -> str:
    """The raw session token from the cookie, or a bearer header.

    Raises rather than returning ``None`` so every caller is spared the check. A missing token
    here is indistinguishable from an expired one on purpose - both mean "start again".
    """
    token = request.cookies.get(settings.auth.session_cookie_name)
    if not token:
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            token = header[7:].strip()
    if not token:
        raise NotAuthenticatedError("Sign in before verifying a second factor.")
    return token


async def _post_mfa_payload(db: AsyncSession, row: SessionRow) -> sch.LoginResponse:
    """The same response shape login returns, rebuilt after the second factor.

    Returned rather than a bare acknowledgement so the client has the tenant list and the flags
    in hand without a second round trip - and so it can use one rendering path for both stages
    of sign-in instead of two that drift apart.
    """
    user = row.user
    memberships = await svc.memberships_for(db, user.id)
    tenants = [m.tenant for m in memberships if m.tenant is not None]
    role_by_tenant = {m.tenant_id: str(m.role) for m in memberships}
    return sch.LoginResponse(
        user=_session_user(user),
        mfa_required=False,
        mfa_enrolment_required=False,
        must_change_password=user.must_change_password,
        tenants=[_tenant_summary(t, role_by_tenant.get(t.id)) for t in tenants],
        active_tenant_id=row.active_tenant_id,
        expires_at=row.absolute_expires_at,
    )


@router.post(
    "/logout",
    response_model=sch.LogoutResponse,
    summary="Sign out of the current session",
)
async def logout(
    principal: CurrentPrincipal, response: Response, settings: SettingsDep
) -> sch.LogoutResponse:
    """Revoke this session and clear the cookie.

    Not idempotent-by-accident: revoking an already-revoked session is a no-op at the database
    level, so a double-clicked sign-out button behaves. What it must never do is fail and leave
    the cookie in place.
    """
    if principal.session_id is not None:
        async with platform_session_scope(reason="revoke own session") as db:
            await svc.logout(db, session_id=principal.session_id, reason="user")
    _clear_session_cookie(response, settings)
    return sch.LogoutResponse()


@router.post(
    "/switch-tenant",
    response_model=sch.TenantSummary,
    summary="Change the active organisation",
)
async def switch_tenant(
    body: sch.SwitchTenantRequest, principal: CurrentPrincipal
) -> sch.TenantSummary:
    """Re-check membership, then rewrite the session's active organisation.

    The tenant in the body is a lookup key, never a claim. plan.md §15 forbids accepting a
    tenant scope from request data as proof of authorization, and this is the endpoint where
    that rule is most tempting to break - the client already knows which organisation it wants,
    so it is easy to just believe it.
    """
    if principal.session_id is None:
        raise NotAuthenticatedError("A session is required to switch organisation.")
    async with platform_session_scope(reason="switch active tenant") as db:
        tenant = await svc.switch_tenant(
            db,
            session_id=principal.session_id,
            user_id=principal.user_id,
            tenant_id=body.tenant_id,
        )
        return _tenant_summary(tenant)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your own password",
)
async def change_password(body: sch.ChangePasswordRequest, principal: CurrentPrincipal) -> Response:
    """Change the password and end every *other* session.

    The current password is required even though the caller is authenticated. That is what stops
    a stolen session token from being upgraded into permanent account takeover - otherwise the
    single most valuable thing an XSS or a borrowed laptop buys.
    """
    async with platform_session_scope(reason="change own password") as db:
        user = (await db.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        await svc.change_password(
            db,
            user=user,
            current_password=body.current_password,
            new_password=body.new_password,
            session_id=principal.session_id or uuid.uuid4(),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/reauthenticate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Re-enter your password to unlock sensitive operations",
)
async def reauthenticate(body: sch.ReauthenticateRequest, principal: CurrentPrincipal) -> Response:
    """Stamp the session as freshly authenticated for the configured window.

    The window covers every re-auth-gated permission, not just the one that triggered the
    prompt. A finance reviewer approving eleven assumption sets should type their password once,
    and the bound is time rather than count.
    """
    if principal.session_id is None:
        raise NotAuthenticatedError("A session is required.")
    async with platform_session_scope(reason="re-authenticate") as db:
        await svc.reauthenticate(db, session_id=principal.session_id, password=body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset link",
)
async def request_password_reset(body: sch.PasswordResetRequest, request: Request) -> Response:
    """Always 202, whether or not the address exists.

    An honest 404 here is a user-enumeration endpoint that needs no credentials, and it is the
    one such endpoint every application has. The cost of the ambiguity is a user who mistyped
    their address waiting for an email that will not arrive; the cost of the alternative is a
    verified list of every customer's staff.

    The token is *not* returned in the response. It is delivered out of band, and in a
    non-production environment it is written to the log at info level so a developer can
    complete the flow without a mail server - which is safe precisely because a hardened
    environment is what the ``is_hardened`` check tests for.
    """
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    await rate_limit.limit("reset-ip", client_ip, rate_limit.RESET_PER_IP)

    async with platform_session_scope(reason="password reset request") as db:
        result = await svc.request_password_reset(db, email=body.email)
        if result is not None:
            user, token = result
            if settings.is_hardened:
                log.info("auth.reset_token_issued", user_id=str(user.id))
            else:
                # Development convenience, gated on the environment rather than on a flag
                # someone could set in production. A reset token in a log is a credential in a
                # log, and no amount of "we only enable it for debugging" makes that safe.
                log.info(
                    "auth.reset_token_issued_dev",
                    user_id=str(user.id),
                    reset_token=token,
                    detail="non-hardened environment only",
                )
            await audit.record(
                db,
                AuditAction.RECORD_UPDATED,
                resource_type="password_reset",
                resource_id=user.id,
                reason="reset_requested",
                actor_user_id=user.id,
                status_code=202,
            )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password/reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password using a reset token",
)
async def confirm_password_reset(body: sch.PasswordResetConfirmRequest) -> Response:
    """Consume the token, set the password, clear any lockout, end every session.

    Clearing the lockout matters: an attacker who locked the account with failed guesses must
    not be able to keep the legitimate owner out after they have proved control of the mailbox.
    Ending every session matters for the mirror-image reason - a reset is what someone does when
    they believe an account is compromised, and it has to actually revoke the compromise.
    """
    async with platform_session_scope(reason="password reset completion") as db:
        await svc.complete_password_reset(db, token=body.token, new_password=body.new_password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Second-factor enrolment
# ---------------------------------------------------------------------------


@router.post(
    "/mfa/enrol",
    response_model=sch.MfaEnrolStartResponse,
    summary="Begin second-factor enrolment",
)
async def start_mfa_enrolment(principal: EnrollingPrincipal) -> sch.MfaEnrolStartResponse:
    """Generate and store a new secret, and return it once.

    Stored immediately, encrypted, rather than held in a pending cache: the confirmation step
    needs it, and a cache is a second expiry to get wrong. It is stored in the *pending* column,
    so an enrolment that is started and abandoned changes nothing about how the account
    authenticates - a first-time user stays unenrolled, and a user who is replacing a lost phone
    keeps the authenticator they still have until the new one is proved.

    ``EnrollingPrincipal`` rather than ``CurrentPrincipal``, because a role that requires a second
    factor cannot otherwise reach this endpoint to acquire one. That dependency relaxes only while
    ``mfa_enrolled_at`` is null; a caller who is already enrolled needs a satisfied session here
    like everywhere else, so re-enrolment is not a bypass.
    """
    secret = mfa_lib.new_secret()
    async with platform_session_scope(reason="mfa enrolment") as db:
        user = (await db.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        user.mfa_pending_secret_encrypted = mfa_lib.encrypt_secret(secret)
        uri = mfa_lib.provisioning_uri(secret, account=user.email)
    return sch.MfaEnrolStartResponse(secret=secret, provisioning_uri=uri)


@router.post(
    "/mfa/enrol/confirm",
    response_model=sch.RecoveryCodesResponse,
    summary="Confirm enrolment and receive recovery codes",
)
async def confirm_mfa_enrolment(
    body: sch.MfaEnrolConfirmRequest, principal: EnrollingPrincipal
) -> sch.RecoveryCodesResponse:
    """Prove the authenticator works, then issue recovery codes.

    Confirmation is not a formality. Marking a user enrolled without verifying one code locks
    out anyone whose clock is wrong or who scanned the QR into the wrong app - and the recovery
    path they would need is the thing this same call is about to create.
    """
    async with platform_session_scope(reason="mfa enrolment confirmation") as db:
        user = (await db.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        if user.mfa_pending_secret_encrypted is None:
            raise ValidationError(
                "Start enrolment before confirming it.",
                remediation="Request a new enrolment secret.",
            )
        secret = mfa_lib.decrypt_secret(user.mfa_pending_secret_encrypted)
        # No replay guard on this one call: there is no previously accepted step to compare
        # against, and the code being confirmed is by definition the first one this secret has
        # produced. The guard begins with the next verification.
        step = mfa_lib.verify_code(secret, body.code)
        plaintext, stored = new_recovery_codes()
        # Promote only now that a code from it has been proved, and drop the pending copy so a
        # stale secret cannot be confirmed twice or resurrected later.
        user.mfa_secret_encrypted = user.mfa_pending_secret_encrypted
        user.mfa_pending_secret_encrypted = None
        user.mfa_enrolled_at = datetime.now(UTC)
        user.mfa_recovery_codes = [*stored, {"kind": "last_step", "step": str(step)}]
        if principal.session_id is not None:
            await db.execute(
                update(SessionRow)
                .where(SessionRow.id == principal.session_id)
                .values(mfa_satisfied_at=datetime.now(UTC))
            )
        # Flush the user and session changes before the audit call. audit.record
        # uses a savepoint so a failed audit INSERT rolls back only itself, but
        # SQLAlchemy's flush([event]) sends ALL pending changes — so without this
        # explicit flush the user's mfa_enrolled_at would be inside the savepoint
        # and lost if the audit write fails.
        await db.flush()
        await audit.record(
            db,
            AuditAction.RECORD_UPDATED,
            tenant_id=None,
            resource_type="user",
            resource_id=user.id,
            after_state={"mfa_enrolled": True},
            reason="mfa_enrolled",
            status_code=200,
        )
    return sch.RecoveryCodesResponse(codes=plaintext, count=len(plaintext))


@router.post(
    "/mfa/recovery-codes",
    response_model=sch.RecoveryCodesResponse,
    summary="Regenerate recovery codes",
)
async def regenerate_recovery_codes(
    principal: CurrentPrincipal, body: sch.ReauthenticateRequest
) -> sch.RecoveryCodesResponse:
    """Replace every recovery code with a fresh set, after re-entering the password.

    Password-gated because a regenerate is equivalent to revoking the old codes, and a stolen
    session should not be able to invalidate the printed sheet in someone's drawer.
    """
    if principal.session_id is None:
        raise NotAuthenticatedError("A session is required.")
    async with platform_session_scope(reason="regenerate recovery codes") as db:
        await svc.reauthenticate(db, session_id=principal.session_id, password=body.password)
        user = (await db.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        last_step = [e for e in (user.mfa_recovery_codes or []) if e.get("kind") == "last_step"]
        plaintext, stored = new_recovery_codes()
        # The replay marker is preserved across regeneration. Dropping it would reopen the
        # ninety-second replay window on the very next verification.
        user.mfa_recovery_codes = [*stored, *last_step]
        await audit.record(
            db,
            AuditAction.RECORD_UPDATED,
            resource_type="user",
            resource_id=user.id,
            after_state={"recovery_codes_regenerated": True},
            reason="recovery_codes_regenerated",
            status_code=200,
        )
    return sch.RecoveryCodesResponse(codes=plaintext, count=len(plaintext))


# ---------------------------------------------------------------------------
# Session inventory
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=list[sch.SessionSummary],
    summary="List your active sessions",
)
async def list_sessions(principal: CurrentPrincipal) -> list[sch.SessionSummary]:
    """Every live session for this user, newest first."""
    async with platform_session_scope(reason="list own sessions") as db:
        rows = (
            await db.execute(
                select(SessionRow)
                .where(
                    SessionRow.user_id == principal.user_id,
                    SessionRow.revoked_at.is_(None),
                    SessionRow.absolute_expires_at > datetime.now(UTC),
                )
                .order_by(SessionRow.issued_at.desc())
                .limit(50)
            )
        ).scalars()
        return [
            sch.SessionSummary(
                id=row.id,
                issued_at=row.issued_at,
                last_seen_at=row.last_seen_at,
                absolute_expires_at=row.absolute_expires_at,
                is_current=row.id == principal.session_id,
                mfa_satisfied=row.mfa_satisfied_at is not None,
            )
            for row in rows
        ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one of your sessions",
)
async def revoke_session(session_id: uuid.UUID, principal: CurrentPrincipal) -> Response:
    """End another of the caller's own sessions.

    Scoped to the caller's own rows by the ``user_id`` predicate rather than by a permission
    check, because "revoke somebody else's session" is a different, administrative operation
    with a different audit action. A request for another user's session id simply matches
    nothing and returns 204 - which is honest, since afterwards the stated goal holds: that
    session id is not one of yours and is not active for you.
    """
    async with platform_session_scope(reason="revoke own session") as db:
        result = await db.execute(
            update(SessionRow)
            .where(
                SessionRow.id == session_id,
                SessionRow.user_id == principal.user_id,
                SessionRow.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC), revoked_reason="user_revoked")
        )
        if result.rowcount:
            await audit.record(
                db,
                AuditAction.LOGOUT,
                resource_type="session",
                resource_id=session_id,
                reason="user_revoked_other_session",
                status_code=204,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# The signed-in user's own view
# ---------------------------------------------------------------------------

me_router = APIRouter(prefix="/me", tags=["me"])


@me_router.get("", response_model=sch.MeResponse, summary="The signed-in user")
async def me(principal: CurrentPrincipal, settings: SettingsDep) -> sch.MeResponse:
    """Everything the frontend needs to render the shell and gate its navigation.

    One request rather than four, because the application shell cannot draw a single nav item
    until it knows the permission set - so splitting this across endpoints puts three sequential
    round trips in front of the first paint.
    """
    from speaker_roi_core.db.session import bind_identity

    async with platform_session_scope(reason="read own profile") as db:
        user = (await db.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        await bind_identity(db, principal.user_id)
        memberships = list(
            (
                await db.execute(
                    select(Membership)
                    .where(Membership.user_id == principal.user_id)
                    .options(selectinload(Membership.tenant))
                    .order_by(Membership.granted_at.desc())
                )
            ).scalars()
        )
        session_row = None
        if principal.session_id is not None:
            session_row = (
                await db.execute(select(SessionRow).where(SessionRow.id == principal.session_id))
            ).scalar_one_or_none()

    ctx = current_context()
    active_tenant_id = ctx.tenant_id if ctx else None
    active = next((m for m in memberships if m.tenant_id == active_tenant_id), None)
    reauth_until = None
    if session_row is not None and session_row.reauthenticated_at is not None:
        reauth_until = session_row.reauthenticated_at + timedelta(
            seconds=settings.auth.reauth_window_seconds
        )

    return sch.MeResponse(
        user=_session_user(user),
        active_tenant=(
            _tenant_summary(active.tenant, str(active.role))
            if active is not None and active.tenant is not None
            else None
        ),
        memberships=[
            sch.MembershipSummary(
                tenant=_tenant_summary(m.tenant, str(m.role)),
                role=str(m.role),
                all_brands=m.all_brands,
                brand_ids=[],
                vendor_id=None,
                granted_at=m.granted_at,
            )
            for m in memberships
            if m.tenant is not None
        ],
        permissions=sorted(principal.permissions),
        roles=sorted(principal.roles),
        is_vendor=principal.is_vendor,
        brand_scope=(
            sorted(principal.brand_scope, key=str) if principal.brand_scope is not None else None
        ),
        session_expires_at=session_row.absolute_expires_at if session_row else None,
        reauthentication_valid_until=reauth_until,
    )


@me_router.post(
    "/acknowledge-notice",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record that the user has seen a compliance notice",
)
async def acknowledge_notice(
    principal: CurrentPrincipal,
    notice: Annotated[
        str,
        Query(
            max_length=100,
            pattern=r"^[a-z0-9_-]+$",
            description="Identifier of the notice, e.g. `methodology` or `hcp-privacy`.",
        ),
    ] = "methodology",
) -> Response:
    """Record an acknowledgement in the audit trail rather than on the user row.

    plan.md §15 wants "who saw which disclosure, when" to be answerable years later. A boolean
    on the user row answers "have they" and destroys the history the moment the notice text
    changes; an audit entry answers the question that is actually asked in a review.
    """
    async with platform_session_scope(reason="record notice acknowledgement") as db:
        with bind(principal=principal):
            await audit.record(
                db,
                AuditAction.RECORD_UPDATED,
                outcome=AuditOutcome.SUCCESS,
                resource_type="compliance_notice",
                resource_label=notice[:100],
                reason="acknowledged",
                status_code=204,
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["me_router", "router"]
