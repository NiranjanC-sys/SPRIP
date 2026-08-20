"""User management within the current tenant.

Reads are available to any authenticated user with ``USER_READ``. Writes (invite, role change,
deactivation) require ``USER_INVITE`` which is held by ``PHARMA_ADMIN`` only.

User creation here is an *invitation*, not a direct create: the user is added with status
``INVITED`` and a welcome/set-password flow is expected to activate them. This is the only
safe pattern when MFA is required — the new user must set their own password and enrol their
own authenticator.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from speaker_roi_api.deps import (
    PageParams,
    ReadOnlySession,
    TenantSession,
    require,
)
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.users import (
    DeactivateUserRequest,
    MembershipOut,
    UserInvite,
    UserOut,
    UserRoleUpdate,
)
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import audit as audit_svc
from speaker_roi_core.context import current_principal, current_tenant_id
from speaker_roi_core.enums import (
    AuditAction,
    AuthProviderKind,
    MembershipStatus,
    Role,
    UserStatus,
)
from speaker_roi_core.errors import ConflictError, NotFoundError, ValidationError
from speaker_roi_core.models import Membership, User

router = APIRouter(tags=["Users"])


def _stamp(row: Any) -> AuditStamp:
    return AuditStamp(
        created_at=row.created_at,
        updated_at=getattr(row, "updated_at", None),
        created_by=getattr(row, "created_by", None),
        updated_by=getattr(row, "updated_by", None),
        version=getattr(row, "row_version", None),
    )


def _actor_id() -> uuid.UUID | None:
    principal = current_principal()
    return principal.user_id if principal else None


def _user_out(user: User, memberships: list[Membership] | None = None) -> UserOut:
    ms = memberships if memberships is not None else getattr(user, "memberships", [])
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        mfa_enrolled=user.mfa_enrolled_at is not None,
        last_login_at=user.last_login_at,
        is_platform_admin=user.is_platform_admin,
        memberships=[
            MembershipOut(
                id=m.id,
                role=m.role,
                status=m.status,
                all_brands=m.all_brands,
                granted_at=m.granted_at,
            )
            for m in ms
            if m.status == MembershipStatus.ACTIVE
        ],
        audit=_stamp(user),
    )


@router.get(
    "/users",
    response_model=Page[UserOut],
    summary="List users in the current tenant",
    dependencies=[Depends(require(Permission.USER_READ))],
)
async def list_users(
    db: ReadOnlySession,
    page: PageParams,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role_filter: Annotated[Role | None, Query(alias="role")] = None,
    status_filter: Annotated[UserStatus | None, Query(alias="status")] = None,
) -> Page[UserOut]:
    from speaker_roi_api.services.crud import paginate

    tenant_id = current_tenant_id()
    stmt = (
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == MembershipStatus.ACTIVE,
        )
        .options(selectinload(User.memberships))
        .distinct()
    )
    if q:
        pattern = f"%{q.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = stmt.where(
            func.lower(User.display_name).like(pattern.lower(), escape="!")
            | func.lower(User.email).like(pattern.lower(), escape="!")
        )
    if role_filter is not None:
        stmt = stmt.where(Membership.role == role_filter)
    if status_filter is not None:
        stmt = stmt.where(User.status == status_filter)

    rows, cursor, _ = await paginate(db, stmt, page, sort_column=User.created_at, id_column=User.id)
    return Page(
        items=[_user_out(r) for r in rows],
        next_cursor=cursor,
    )


@router.get(
    "/users/{user_id}",
    response_model=UserOut,
    summary="Get a user",
    dependencies=[Depends(require(Permission.USER_READ))],
)
async def get_user(db: ReadOnlySession, user_id: uuid.UUID) -> UserOut:
    tenant_id = current_tenant_id()
    row = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
            .options(selectinload(User.memberships))
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("user", user_id)
    return _user_out(row)


@router.post(
    "/users/invite",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a user to this tenant",
    dependencies=[Depends(require(Permission.USER_INVITE))],
)
async def invite_user(db: TenantSession, payload: UserInvite) -> UserOut:
    tenant_id = current_tenant_id()
    actor = _actor_id()

    existing = (
        await db.execute(
            select(User).where(func.lower(User.email) == payload.email.strip().lower())
        )
    ).scalar_one_or_none()

    if existing is not None:
        has_membership = (
            await db.execute(
                select(Membership.id).where(
                    Membership.user_id == existing.id,
                    Membership.tenant_id == tenant_id,
                    Membership.status == MembershipStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if has_membership is not None:
            raise ConflictError(
                f"A user with email '{payload.email}' already has access to this organisation."
            )
        user = existing
    else:
        user = User(
            email=payload.email.strip().lower(),
            display_name=payload.display_name,
            status=UserStatus.INVITED,
            auth_provider_kind=AuthProviderKind.LOCAL,
            created_by=actor,
        )
        db.add(user)
        await db.flush([user])

    membership = Membership(
        user_id=user.id,
        tenant_id=tenant_id,
        role=payload.role,
        all_brands=payload.all_brands,
        status=MembershipStatus.ACTIVE,
        granted_at=datetime.now(UTC),
        created_by=actor,
    )
    db.add(membership)
    await db.flush([membership])

    await audit_svc.record(
        db,
        AuditAction.RECORD_CREATED,
        resource_type="user",
        resource_id=user.id,
        resource_label=user.email,
        after_state={"role": str(payload.role), "all_brands": payload.all_brands},
        actor_user_id=actor,
        status_code=201,
    )
    return _user_out(user, [membership])


@router.patch(
    "/users/{user_id}/role",
    response_model=UserOut,
    summary="Update a user's role in this tenant",
    dependencies=[Depends(require(Permission.USER_INVITE))],
)
async def update_user_role(
    db: TenantSession, user_id: uuid.UUID, payload: UserRoleUpdate
) -> UserOut:
    tenant_id = current_tenant_id()
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("user", user_id)
    if membership.row_version != payload.version:
        from speaker_roi_core.errors import PreconditionFailedError

        raise PreconditionFailedError(
            "This membership was updated by someone else.",
            remediation="Reload the user and re-apply your changes.",
        )

    before = {"role": str(membership.role), "all_brands": membership.all_brands}
    membership.role = payload.role
    membership.all_brands = payload.all_brands
    membership.updated_by = _actor_id()
    await db.flush([membership])

    user = (
        await db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.memberships))
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("user", user_id)

    await audit_svc.record(
        db,
        AuditAction.RECORD_UPDATED,
        resource_type="user",
        resource_id=user_id,
        after_state={"role": str(payload.role), "all_brands": payload.all_brands},
        before_state=before,
        actor_user_id=_actor_id(),
        status_code=200,
    )
    return _user_out(user)


@router.post(
    "/users/{user_id}/deactivate",
    response_model=Acknowledged,
    summary="Deactivate a user in this tenant",
    dependencies=[Depends(require(Permission.USER_INVITE))],
)
async def deactivate_user(
    db: TenantSession, user_id: uuid.UUID, payload: DeactivateUserRequest
) -> Acknowledged:
    tenant_id = current_tenant_id()
    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.tenant_id == tenant_id,
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("user", user_id)

    principal = current_principal()
    if principal and principal.user_id == user_id:
        raise ValidationError(
            "You cannot deactivate your own account.",
            remediation="Ask another administrator to deactivate your account.",
        )

    membership.status = MembershipStatus.SUSPENDED
    membership.revoked_at = datetime.now(UTC)
    membership.revoked_reason = payload.reason
    membership.updated_by = _actor_id()
    await db.flush([membership])

    await audit_svc.record(
        db,
        AuditAction.RECORD_DEACTIVATED,
        resource_type="user",
        resource_id=user_id,
        reason=payload.reason,
        actor_user_id=_actor_id(),
        status_code=200,
    )
    return Acknowledged()


__all__ = ["router"]
