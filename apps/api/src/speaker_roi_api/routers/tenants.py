"""Platform tenant administration.

Every endpoint here requires ``PLATFORM_ADMIN``, which is a flag on the user rather than a
membership. Platform admins see across tenants but hold no tenant-scoped permissions, so
there is no data-access leakage: they manage the *envelope* (status, currency, retention)
and never the *contents* (brands, events, prescriptions).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from speaker_roi_api.deps import PageParams, PlatformAdmin
from speaker_roi_api.schemas.common import AuditStamp, Page
from speaker_roi_api.schemas.tenants import (
    SuspendRequest,
    TenantCreate,
    TenantOut,
    TenantPatch,
)
from speaker_roi_api.services import audit as audit_svc
from speaker_roi_core.context import current_principal
from speaker_roi_core.db.session import platform_session_scope
from speaker_roi_core.enums import AuditAction, TenantStatus
from speaker_roi_core.errors import ConflictError, NotFoundError, PreconditionFailedError
from speaker_roi_core.models import Membership
from speaker_roi_core.models.core import Tenant

router = APIRouter(tags=["Tenants"])

_AUDIT_FIELDS = ("code", "name", "status", "country", "reporting_currency", "locale", "timezone")


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


def _tenant_out(row: Tenant, user_count: int | None = None) -> TenantOut:
    return TenantOut(
        id=row.id,
        code=row.code,
        name=row.name,
        status=row.status,
        country=row.country,
        reporting_currency=row.reporting_currency,
        locale=row.locale,
        timezone=row.timezone,
        fiscal_year_start_month=row.fiscal_year_start_month,
        synthetic_mode=row.synthetic_mode,
        data_retention_days=row.data_retention_days,
        user_count=user_count,
        suspended_at=row.suspended_at,
        suspended_reason=row.suspended_reason,
        audit=_stamp(row),
    )


@router.get("/tenants", response_model=Page[TenantOut], summary="List tenants")
async def list_tenants(
    _admin: PlatformAdmin,
    page: PageParams,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[TenantStatus | None, Query(alias="status")] = None,
) -> Page[TenantOut]:
    from speaker_roi_api.services.crud import paginate

    async with platform_session_scope(reason="list tenants") as db:
        stmt = select(Tenant)
        if status_filter is not None:
            stmt = stmt.where(Tenant.status == status_filter)
        if q:
            pattern = f"%{q.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
            stmt = stmt.where(
                func.lower(Tenant.name).like(pattern.lower(), escape="!")
                | Tenant.code.like(pattern.lower(), escape="!")
            )

        rows, cursor, _ = await paginate(
            db, stmt, page, sort_column=Tenant.created_at, id_column=Tenant.id
        )

        counts: dict[uuid.UUID, int] = {}
        if rows:
            counted = await db.execute(
                select(Membership.tenant_id, func.count(func.distinct(Membership.user_id)))
                .where(Membership.tenant_id.in_([r.id for r in rows]))
                .group_by(Membership.tenant_id)
            )
            counts = {tid: int(n) for tid, n in counted.all()}

        return Page(
            items=[_tenant_out(r, user_count=counts.get(r.id, 0)) for r in rows],
            next_cursor=cursor,
        )


@router.get("/tenants/{tenant_id}", response_model=TenantOut, summary="Get tenant")
async def get_tenant(_admin: PlatformAdmin, tenant_id: uuid.UUID) -> TenantOut:
    async with platform_session_scope(reason="get tenant") as db:
        row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if row is None:
            raise NotFoundError("tenant", tenant_id)

        count_result = await db.execute(
            select(func.count(func.distinct(Membership.user_id))).where(
                Membership.tenant_id == tenant_id
            )
        )
        user_count = int(count_result.scalar_one())
        return _tenant_out(row, user_count=user_count)


@router.post(
    "/tenants",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant",
)
async def create_tenant(_admin: PlatformAdmin, payload: TenantCreate) -> TenantOut:
    async with platform_session_scope(reason="create tenant") as db:
        existing = (
            await db.execute(select(Tenant).where(Tenant.code == payload.code))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(f"A tenant with code '{payload.code}' already exists.")

        actor = _actor_id()
        row = Tenant(
            **payload.model_dump(exclude_unset=True),
            status=TenantStatus.ACTIVE,
            created_by=actor,
        )
        db.add(row)
        await db.flush([row])
        await audit_svc.record(
            db,
            AuditAction.RECORD_CREATED,
            resource_type="tenant",
            resource_id=row.id,
            resource_label=row.code,
            after_state={k: getattr(row, k) for k in _AUDIT_FIELDS},
            actor_user_id=actor,
            status_code=201,
        )
        return _tenant_out(row, user_count=0)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut, summary="Update a tenant")
async def update_tenant(
    _admin: PlatformAdmin, tenant_id: uuid.UUID, payload: TenantPatch
) -> TenantOut:
    async with platform_session_scope(reason="update tenant") as db:
        row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if row is None:
            raise NotFoundError("tenant", tenant_id)
        if row.row_version != payload.version:
            raise PreconditionFailedError(
                "This record was updated by someone else.",
                remediation="Reload the tenant and re-apply your changes.",
            )
        before = {k: getattr(row, k) for k in _AUDIT_FIELDS}
        changes = payload.model_dump(exclude_unset=True, exclude={"version"})
        for key, val in changes.items():
            setattr(row, key, val)
        row.updated_by = _actor_id()
        await db.flush([row])
        after = {k: getattr(row, k) for k in _AUDIT_FIELDS}
        await audit_svc.record(
            db,
            AuditAction.RECORD_UPDATED,
            resource_type="tenant",
            resource_id=row.id,
            resource_label=row.code,
            before_state=before,
            after_state=after,
            actor_user_id=_actor_id(),
            status_code=200,
        )
        return _tenant_out(row)


@router.post(
    "/tenants/{tenant_id}/suspend",
    response_model=TenantOut,
    summary="Suspend a tenant",
)
async def suspend_tenant(
    _admin: PlatformAdmin, tenant_id: uuid.UUID, payload: SuspendRequest
) -> TenantOut:
    async with platform_session_scope(reason="suspend tenant") as db:
        row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if row is None:
            raise NotFoundError("tenant", tenant_id)
        row.status = TenantStatus.SUSPENDED
        row.suspended_at = datetime.now(UTC)
        row.suspended_reason = payload.reason
        row.updated_by = _actor_id()
        await db.flush([row])
        await audit_svc.record(
            db,
            AuditAction.RECORD_DEACTIVATED,
            resource_type="tenant",
            resource_id=row.id,
            resource_label=row.code,
            reason=payload.reason,
            actor_user_id=_actor_id(),
            status_code=200,
        )
        return _tenant_out(row)


@router.post(
    "/tenants/{tenant_id}/activate",
    response_model=TenantOut,
    summary="Reactivate a suspended tenant",
)
async def activate_tenant(_admin: PlatformAdmin, tenant_id: uuid.UUID) -> TenantOut:
    async with platform_session_scope(reason="activate tenant") as db:
        row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if row is None:
            raise NotFoundError("tenant", tenant_id)
        row.status = TenantStatus.ACTIVE
        row.suspended_at = None
        row.suspended_reason = None
        row.updated_by = _actor_id()
        await db.flush([row])
        await audit_svc.record(
            db,
            AuditAction.RECORD_ACTIVATED,
            resource_type="tenant",
            resource_id=row.id,
            resource_label=row.code,
            actor_user_id=_actor_id(),
            status_code=200,
        )
        return _tenant_out(row)


__all__ = ["router"]
