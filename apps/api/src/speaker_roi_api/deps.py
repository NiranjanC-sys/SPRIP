"""FastAPI dependencies: authentication, authorization, scoping, paging, idempotency.

Everything a route needs in order to be safe by construction lives here, and the shape of
these dependencies is the main authorization control in the application. Three properties are
deliberate.

**The tenant comes from the session record, never from the request.** plan.md §15: *"never
accept a role, tenant or vendor scope directly from browser form data as proof of
authorization"*. A caller may *ask* to switch tenant, and that goes through an endpoint that
re-checks membership and rewrites the session row; it is not a header the API believes.

**The database session dependency depends on the principal.** That is not for convenience -
it is what makes the ordering guaranteed. FastAPI resolves dependencies depth-first, so
``session: TenantSession`` cannot be opened before ``get_principal`` has bound the tenant into
the ambient context, which is where :func:`session_scope` reads it from. If the two were
siblings, a route that happened to declare them in the wrong order would open a transaction
with no tenant bound and fail at the first query with a bare 42704 - or, worse, a future
refactor that made the tenant optional would open one with no policy applied.

**Authorization is by permission, never by role.** :func:`require` takes
:class:`~speaker_roi_api.security.rbac.Permission` members. A new role added to the matrix
therefore cannot silently inherit a capability, and reading a route's decorator tells you what
it needs without cross-referencing nine role definitions.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speaker_roi_api.security.rbac import (
    Permission,
    assert_permission,
    effective_permissions,
    requires_reauthentication,
)
from speaker_roi_api.security.tokens import decode_token, hash_token
from speaker_roi_core.config import Settings, get_settings
from speaker_roi_core.context import Principal, bind
from speaker_roi_core.db.session import get_sessionmaker, session_scope
from speaker_roi_core.enums import MembershipStatus, UserStatus
from speaker_roi_core.errors import (
    ForbiddenError,
    InvalidCursorError,
    MfaRequiredError,
    NotAuthenticatedError,
    ReauthenticationRequiredError,
    SessionExpiredError,
    TenantScopeRequiredError,
)
from speaker_roi_core.logging import get_logger
from speaker_roi_core.models import Membership, User
from speaker_roi_core.models import Session as SessionRow

log = get_logger(__name__)

#: Bearer tokens are accepted for service accounts and for the download-token flow only.
#: Browser sessions use the cookie, because a token in ``localStorage`` is readable by any
#: script that achieves execution, and an ``HttpOnly`` cookie is not.
_BEARER_PREFIX: Final = "Bearer "

#: How long after the last request a session row's ``last_seen_at`` is rewritten. Without a
#: threshold, every single request issues an UPDATE to the same row, which serialises the whole
#: application behind one row lock per user and produces a torrent of WAL for no information.
_TOUCH_INTERVAL_SECONDS: Final = 60


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(settings_dep)]


# ---------------------------------------------------------------------------
# Credential extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Credential:
    """A presented credential, before it is verified."""

    #: ``cookie`` | ``bearer``
    kind: str
    value: str


def _credential(request: Request, cookie_name: str) -> Credential | None:
    """Read the credential, preferring the cookie.

    The cookie wins when both are present. That order matters for CSRF: a request that
    carries a session cookie is a browser request whether or not it also carries a header,
    and letting a header override the cookie would allow a page to elevate a browser
    session's scope by attaching a service token it obtained elsewhere.
    """
    cookie = request.cookies.get(cookie_name)
    if cookie:
        return Credential("cookie", cookie)
    header = request.headers.get("authorization")
    if header and header.startswith(_BEARER_PREFIX):
        token = header[len(_BEARER_PREFIX) :].strip()
        if token:
            return Credential("bearer", token)
    return None


# ---------------------------------------------------------------------------
# Session resolution
# ---------------------------------------------------------------------------


async def _load_session(token: str) -> tuple[SessionRow, User]:
    """Fetch the session row and its user, or raise.

    Runs in a *platform* scope, not a tenant scope, for a structural reason: the tenant is
    not known until this row is read, so there is nothing to bind yet. ``auth.sessions`` and
    ``auth.users`` are in ``PLATFORM_TABLES`` and carry no RLS policy precisely so that this
    lookup is possible without a chicken-and-egg problem.

    A separate short transaction rather than the request's own, so that the request
    transaction begins with the correct tenant already bound and never has to be re-bound
    mid-flight - ``set_config(..., true)`` is transaction-local, and a second binding inside
    one transaction would be a silent scope change in the middle of a unit of work.
    """
    token_hash = hash_token(token)
    factory = get_sessionmaker()
    async with factory() as db, db.begin():
        # No platform GUC needed: neither table has a policy. Set nothing, claim nothing.
        row = (
            await db.execute(
                select(SessionRow)
                .where(SessionRow.token_hash == token_hash)
                .options(selectinload(SessionRow.user))
            )
        ).scalar_one_or_none()
        if row is None:
            # Deliberately the same error and the same message as an expired session. A
            # distinguishable "no such session" tells an attacker holding a stolen token
            # whether it was ever valid.
            raise NotAuthenticatedError("Your session is not valid. Please sign in again.")
        user = row.user
        now = datetime.now(UTC)
        if row.revoked_at is not None:
            raise SessionExpiredError("Your session was ended. Please sign in again.")
        if row.absolute_expires_at <= now or row.idle_expires_at <= now:
            raise SessionExpiredError("Your session has expired. Please sign in again.")
        if user is not None and user.locked_until is not None and user.locked_until > now:
            raise SessionExpiredError(
                "Your account is temporarily locked. Please try again later.",
            )
        if user is None or user.status is not UserStatus.ACTIVE:
            # A suspended user's existing sessions must stop working immediately, not at
            # their next natural expiry. Checked here rather than only at login because
            # suspension is usually a response to something in progress.
            raise SessionExpiredError("Your account is not active. Contact your administrator.")

        if (now - row.last_seen_at).total_seconds() >= _TOUCH_INTERVAL_SECONDS:
            row.last_seen_at = now
            row.idle_expires_at = now + _idle_delta()
        # Detach both so they remain readable after this transaction closes. Expunging
        # rather than refreshing avoids a second round trip for data already in hand.
        db.expunge_all()
        return row, user


def _idle_delta() -> Any:
    from datetime import timedelta

    return timedelta(seconds=get_settings().auth.session_idle_timeout_seconds)


async def _load_memberships(tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[Membership]:
    """Active memberships for this user in this tenant, with their scopes.

    ``memberships`` is tenant-scoped and under RLS, so this runs with the tenant bound. The
    ``tenant_id`` predicate is still written explicitly: RLS is the guarantee, the predicate
    is the index lookup, and a query that relies on the policy for correctness is one whose
    plan changes if the policy ever does.
    """
    async with session_scope(tenant_id=tenant_id, read_only=True) as db:
        rows = (
            await db.execute(
                select(Membership)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.user_id == user_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
                .options(
                    selectinload(Membership.brand_scopes),
                    selectinload(Membership.vendor_scopes),
                )
            )
        ).scalars()
        memberships = list(rows)
        db.expunge_all()
        return memberships


def _resolve_scopes(
    memberships: Iterable[Membership],
) -> tuple[frozenset[uuid.UUID] | None, uuid.UUID | None]:
    """Collapse several memberships into one brand scope and one vendor scope.

    A user can hold more than one role in a tenant - a brand manager who is also a finance
    reviewer - and the scopes then union. Two rules keep the union from being an escalation:

    *Any* membership with ``all_brands`` set makes the brand scope unrestricted, which is
    correct because that membership on its own already granted it.

    Vendor scope is the opposite: it *narrows*. A vendor contributor's membership names the
    vendors they may act for, and a second membership cannot widen that, because holding two
    vendor memberships in one tenant is a data-entry error rather than a legitimate state -
    so the first is taken and the situation is logged for an administrator to fix. Returning
    "all vendors" here would be the one bug in this file with unbounded blast radius.
    """
    brands: set[uuid.UUID] = set()
    unrestricted = False
    vendor_ids: list[uuid.UUID] = []
    for membership in memberships:
        if membership.all_brands:
            unrestricted = True
        else:
            brands.update(scope.brand_id for scope in membership.brand_scopes)
        vendor_ids.extend(scope.vendor_id for scope in membership.vendor_scopes)

    if len(set(vendor_ids)) > 1:
        log.error(
            "auth.multiple_vendor_scopes",
            vendor_count=len(set(vendor_ids)),
            remediation="a user must be linked to at most one vendor per tenant; "
            "the narrowest scope has been applied",
        )
    vendor_id = min(set(vendor_ids), key=str) if vendor_ids else None
    return (None if unrestricted else frozenset(brands)), vendor_id


def _principal_from_service_token(claims: dict[str, Any]) -> tuple[Principal, uuid.UUID | None]:
    """Build a principal from a signed service token.

    Service accounts get their permissions from the token, which is only safe because the
    token is signed by us and short-lived: a fifteen-minute TTL means a revoked API key stops
    working within fifteen minutes without a database lookup on every request. The
    intersection with the key's stored grants is checked at issue time, in the endpoint that
    mints these, not here - re-deriving it here would defeat the point of a stateless token.

    ``authenticated_at_epoch`` is left ``None``, which makes every re-auth-gated operation
    refuse. A machine cannot re-present credentials interactively, so publishing results or
    changing a role is simply not available to one - which is the correct answer, not a gap.
    """
    tenant_raw = claims.get("tenant_id")
    tenant_id = uuid.UUID(tenant_raw) if tenant_raw else None
    permissions = frozenset(str(p) for p in claims.get("permissions", ()))
    return (
        Principal(
            user_id=uuid.UUID(claims["sub"]),
            email=f"service:{claims.get('api_key_id', 'unknown')}",
            roles=frozenset({"SERVICE_ACCOUNT"}),
            permissions=permissions,
            brand_scope=None,
            vendor_id=None,
            authenticated_at_epoch=None,
            mfa_satisfied=True,
            session_id=None,
            is_platform_admin=False,
            is_service_account=True,
        ),
        tenant_id,
    )


async def _authenticate(
    request: Request, *, allow_unenrolled: bool = False
) -> tuple[Principal, uuid.UUID | None]:
    """Resolve the credential into a principal and the tenant its session names.

    ``allow_unenrolled`` is the one relaxation, and it exists to break a genuine deadlock: an
    administrator whose role requires a second factor cannot reach *any* principal-guarded
    endpoint until MFA is satisfied, and satisfying it requires enrolling, which is itself a
    principal-guarded endpoint. On a freshly provisioned tenant that is an account that can sign
    in and do nothing at all, for ever.

    The relaxation is narrow on purpose. It applies only when ``mfa_enrolled_at`` is null - the
    account has no working second factor, so there is nothing for a password-only session to
    bypass. The moment enrolment completes, the flag stops having any effect, which is what stops
    it from becoming a way to sidestep the second factor by asking to re-enrol.
    """
    settings = get_settings()
    credential = _credential(request, settings.auth.session_cookie_name)
    if credential is None:
        raise NotAuthenticatedError("Sign in to continue.")

    if credential.kind == "bearer":
        claims = decode_token(credential.value, expect_kind="service")
        principal, tenant_id = _principal_from_service_token(claims)
    else:
        row, user = await _load_session(credential.value)
        tenant_id = row.active_tenant_id
        roles: frozenset[str] = frozenset()
        brand_scope: frozenset[uuid.UUID] | None = None
        vendor_id: uuid.UUID | None = None
        if tenant_id is not None:
            memberships = await _load_memberships(tenant_id, user.id)
            if not memberships:
                # The session names a tenant the user is no longer a member of - a
                # revocation that happened while they were signed in. Refused rather than
                # silently downgraded to no tenant, because a downgrade would present as
                # an empty application with no explanation.
                raise ForbiddenError(
                    "Your access to this organisation has been removed.",
                    remediation="Contact your administrator, or switch to another "
                    "organisation you belong to.",
                )
            roles = frozenset(str(m.role) for m in memberships)
            brand_scope, vendor_id = _resolve_scopes(memberships)

        is_platform_admin = _is_platform_admin(user)
        permissions = effective_permissions(
            [*roles, *(["PLATFORM_ADMIN"] if is_platform_admin else [])],
            is_vendor=vendor_id is not None,
        )
        mfa_satisfied = row.mfa_satisfied_at is not None
        if not (allow_unenrolled and user.mfa_enrolled_at is None):
            _assert_mfa_satisfied(
                roles=roles,
                is_platform_admin=is_platform_admin,
                mfa_satisfied=mfa_satisfied,
                user_mfa_required=user.mfa_required,
                settings=settings,
            )
        reference = row.reauthenticated_at or row.issued_at
        principal = Principal(
            user_id=user.id,
            email=user.email,
            roles=roles,
            permissions=permissions,
            brand_scope=brand_scope,
            vendor_id=vendor_id,
            authenticated_at_epoch=reference.timestamp(),
            mfa_satisfied=mfa_satisfied,
            session_id=row.id,
            is_platform_admin=is_platform_admin,
            is_service_account=False,
        )

    return principal, tenant_id


async def get_principal(request: Request) -> AsyncIterator[Principal]:
    """Authenticate the caller and bind their identity and tenant into the ambient context.

    A generator dependency, so the amended context is bound for the whole request - including
    for the database session dependency that depends on this one, and for every log line the
    handler emits - and is unbound again on the way out even if the handler raises.
    """
    principal, tenant_id = await _authenticate(request)
    with bind(principal=principal, tenant_id=tenant_id):
        yield principal


async def get_enrolling_principal(request: Request) -> AsyncIterator[Principal]:
    """As :func:`get_principal`, but usable by a session whose second factor does not exist yet.

    Used by exactly two endpoints - start enrolment and confirm it - and by nothing else. Anything
    wider would be a way to trade a stolen password for access to an MFA-protected account.

    Note what is *not* relaxed: the session must still be live, unrevoked, within both expiries,
    belong to an active and unlocked user, and name a tenant the user still has a membership in.
    The only check suspended is the one that cannot be satisfied yet.
    """
    principal, tenant_id = await _authenticate(request, allow_unenrolled=True)
    with bind(principal=principal, tenant_id=tenant_id):
        yield principal


def _is_platform_admin(user: User) -> bool:
    """Platform administration is a column on the user, not a membership.

    Deliberate, and the model says so: a platform operator is not scoped to a tenant, so
    representing the grant as a membership row would require inventing a synthetic tenant for
    it to point at - and every tenant filter in the application would then have to know about
    that tenant and exclude it. One boolean, changeable only through the platform console and
    audited there.
    """
    return user.is_platform_admin


def _assert_mfa_satisfied(
    *,
    roles: frozenset[str],
    is_platform_admin: bool,
    mfa_satisfied: bool,
    user_mfa_required: bool,
    settings: Settings,
) -> None:
    """Refuse a session that has not completed MFA when policy demands it.

    Checked on *every* request rather than only at login. A session established before an
    administrator turned on the MFA requirement would otherwise keep working for its full
    twelve hours, which is exactly the window during which the requirement was turned on for
    a reason.
    """
    if mfa_satisfied:
        return
    required_roles = set(settings.auth.mfa_required_for_roles)
    if is_platform_admin:
        required_roles.add("PLATFORM_ADMIN")
    if user_mfa_required or (roles & required_roles) or is_platform_admin:
        raise MfaRequiredError(
            "Multi-factor authentication is required for your role.",
            remediation="Complete the verification step to continue.",
        )


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
#: Only for the two enrolment endpoints. See :func:`get_enrolling_principal`.
EnrollingPrincipal = Annotated[Principal, Depends(get_enrolling_principal)]


# ---------------------------------------------------------------------------
# Database sessions, ordered behind authentication
# ---------------------------------------------------------------------------


async def tenant_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    """A read-write transaction with the tenant bound.

    Takes ``principal`` purely to force the resolution order described in the module
    docstring; it does not read it. The tenant is taken from the ambient context, which is
    the only place a tenant is ever read from.
    """
    del principal
    async with session_scope() as db:
        yield db


async def readonly_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    """A read-only transaction with the tenant bound, for the analytical read paths.

    ``SET TRANSACTION READ ONLY`` turns "this endpoint does not write" from a convention
    into something the database enforces - which matters most on the endpoints that build
    large result sets, where an accidental write would be both slow and invisible.
    """
    del principal
    async with session_scope(read_only=True) as db:
        yield db


TenantSession = Annotated[AsyncSession, Depends(tenant_session)]
ReadOnlySession = Annotated[AsyncSession, Depends(readonly_session)]


def require_tenant(principal: CurrentPrincipal) -> uuid.UUID:
    """The active tenant, or a 428-style refusal naming the remedy.

    A signed-in user with no active tenant is a real and non-exceptional state: a platform
    admin, or someone who belongs to three organisations and has not chosen one yet. The
    frontend turns this error into the organisation picker, which is why it carries a
    specific code rather than a generic 403.
    """
    from speaker_roi_core.context import current_tenant_id_or_none

    tenant_id = current_tenant_id_or_none()
    if tenant_id is None:
        raise TenantScopeRequiredError(
            "Select an organisation to continue.",
            remediation="Choose an organisation, or ask an administrator for access.",
        )
    return tenant_id


TenantId = Annotated[uuid.UUID, Depends(require_tenant)]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def require(*permissions: Permission) -> Callable[..., None]:
    """Dependency factory: the caller must hold **all** of ``permissions``.

    All rather than any. An endpoint that legitimately accepts either of two permissions is
    two endpoints with different responses, or one whose response varies by permission - and
    in both cases writing the disjunction here would hide that from the reader. When a route
    really does need a disjunction it calls :meth:`Principal.has_any` in its body, where the
    consequence is visible.

    Re-authentication is enforced here too, for the permissions that demand it, so it cannot
    be forgotten at a call site: the requirement is a property of the permission.
    """

    def guard(request: Request, principal: CurrentPrincipal) -> None:
        for permission in permissions:
            assert_permission(principal, permission)
            if requires_reauthentication(permission):
                _assert_recent_authentication(principal, permission)
        # Recorded for the audit writer, which runs after the handler and would otherwise
        # have to guess which permission authorised the call it is describing.
        request.state.authorized_permissions = tuple(str(p) for p in permissions)

    return guard


def _assert_recent_authentication(principal: Principal, permission: Permission) -> None:
    settings = get_settings()
    if principal.authenticated_at_epoch is None:
        raise ReauthenticationRequiredError(
            "This action requires you to confirm your password, which a machine "
            "credential cannot do.",
            context={"permission": str(permission)},
        )
    age = datetime.now(UTC).timestamp() - principal.authenticated_at_epoch
    if age > settings.auth.reauth_window_seconds:
        raise ReauthenticationRequiredError(
            "Confirm your password to continue.",
            context={"permission": str(permission)},
            remediation="Re-enter your password; you will return to this action.",
        )


def require_platform_admin(principal: CurrentPrincipal) -> Principal:
    """For the platform console. Distinct from a permission check on purpose.

    Platform endpoints operate across tenants and must be unavailable to a tenant user even
    if a permission were mistakenly granted to a tenant role, so they gate on the flag that
    only a platform membership can set.
    """
    if not principal.is_platform_admin:
        raise ForbiddenError("This area is restricted to platform operators.")
    return principal


PlatformAdmin = Annotated[Principal, Depends(require_platform_admin)]


def deny_vendor(principal: CurrentPrincipal) -> None:
    """Belt to the braces of the permission subtraction.

    The vendor restriction is already applied once, where the principal is built, by removing
    the forbidden permissions. This exists for the handful of endpoints whose sensitivity does
    not map cleanly onto a single permission, and as a second failure that would have to also
    be forgotten before a vendor saw prescription-derived output.
    """
    if principal.is_vendor:
        raise ForbiddenError("This area is not available to external contributors.")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

_MAX_PAGE_SIZE: Final = 200
_DEFAULT_PAGE_SIZE: Final = 50


@dataclass(frozen=True, slots=True)
class Page:
    """Keyset pagination parameters.

    Keyset, not offset. ``OFFSET 50000`` makes PostgreSQL walk and discard fifty thousand
    rows, so the last page of a large list is the slowest request in the application; and on
    a table that is being written to, offset paging silently skips and repeats rows as the
    underlying order shifts. A cursor over ``(sort_key, id)`` is stable and costs the same on
    page one and page one thousand.
    """

    limit: int
    #: Opaque to the client, and *meant* to be: the moment a cursor is legible, someone
    #: constructs one by hand and it becomes part of the API contract.
    cursor: str | None

    def decode(self) -> tuple[Any, uuid.UUID] | None:
        """Split the cursor into its sort key and tie-breaker, or refuse it."""
        if not self.cursor:
            return None
        import base64
        import binascii

        try:
            raw = base64.urlsafe_b64decode(self.cursor.encode("ascii") + b"==").decode("utf-8")
            key, _, id_part = raw.rpartition("|")
            return key, uuid.UUID(id_part)
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            # A specific code rather than a generic 400: the frontend retries from the start
            # of the list on this one, which is the right recovery for a cursor invalidated
            # by a changed sort order.
            # No message or remediation passed: the exception fixes both, precisely so that
            # every rejection reads identically and a caller probing cursor forgeries learns
            # nothing from the difference between "not base64" and "not a valid uuid".
            raise InvalidCursorError(internal_detail=f"undecodable cursor: {exc!s}") from exc


def encode_cursor(sort_key: Any, row_id: uuid.UUID) -> str:
    import base64

    raw = f"{sort_key}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def page_params(
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
) -> Page:
    return Page(limit=limit, cursor=cursor)


PageParams = Annotated[Page, Depends(page_params)]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def idempotency_key(
    key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)] = None,
) -> str | None:
    """The caller's replay token for a non-idempotent request.

    Required by the endpoints that start expensive work or move money-shaped numbers, so that
    a client which retries after a timeout gets the original result rather than a second
    analysis run. Validated for length here and for reuse in the service layer, which is
    where the stored response lives.
    """
    return key


IdempotencyKey = Annotated[str | None, Depends(idempotency_key)]


__all__ = [
    "CurrentPrincipal",
    "EnrollingPrincipal",
    "IdempotencyKey",
    "Page",
    "PageParams",
    "PlatformAdmin",
    "ReadOnlySession",
    "SettingsDep",
    "TenantId",
    "TenantSession",
    "deny_vendor",
    "encode_cursor",
    "get_enrolling_principal",
    "get_principal",
    "require",
    "require_platform_admin",
    "require_tenant",
]
