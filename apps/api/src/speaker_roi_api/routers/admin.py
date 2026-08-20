"""Platform administration endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from speaker_roi_api.deps import PlatformAdmin, ReadOnlySession, TenantSession, require
from speaker_roi_api.schemas.admin import SystemStatsOut, TenantToggleOut, TenantUsageOut
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.enums import TenantStatus
from speaker_roi_core.models import User
from speaker_roi_core.models.core import Event, Tenant

router = APIRouter(tags=["Admin"])


@router.get(
    "/admin/system-stats",
    response_model=SystemStatsOut,
    summary="Platform-wide statistics",
    dependencies=[Depends(require(Permission.PLATFORM_HEALTH_READ))],
)
async def system_stats(db: ReadOnlySession, _admin: PlatformAdmin) -> SystemStatsOut:
    # These queries run against tables that are not tenant-scoped (Tenant, User)
    # or use aggregate counts. The PlatformAdmin dependency ensures only platform
    # operators reach this endpoint.
    tenant_count = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    # Event is tenant-scoped; count across all visible rows. For a true cross-tenant
    # count without RLS, a platform-level query or a separate connection would be
    # needed. This gives the count for the admin's visible scope.
    event_count = (await db.execute(select(func.count()).select_from(Event))).scalar_one()
    return SystemStatsOut(
        tenant_count=int(tenant_count),
        user_count=int(user_count),
        total_events=int(event_count),
    )


@router.get(
    "/admin/tenants",
    response_model=list[TenantUsageOut],
    summary="List all tenants with usage stats",
    dependencies=[Depends(require(Permission.PLATFORM_TENANT_READ))],
)
async def list_tenants(db: ReadOnlySession, _admin: PlatformAdmin) -> list[TenantUsageOut]:
    rows = (await db.execute(select(Tenant))).scalars().all()
    results: list[TenantUsageOut] = []
    for tenant in rows:
        results.append(
            TenantUsageOut(
                id=tenant.id,
                code=tenant.code,
                name=tenant.name,
                status=str(tenant.status),
                user_count=0,
                event_count=0,
            )
        )
    return results


@router.post(
    "/admin/tenants/{tenant_id}/toggle",
    response_model=TenantToggleOut,
    summary="Enable or disable a tenant",
    dependencies=[Depends(require(Permission.PLATFORM_TENANT_WRITE))],
)
async def toggle_tenant(
    db: TenantSession, tenant_id: uuid.UUID, _admin: PlatformAdmin
) -> TenantToggleOut:
    row = await crud.get_or_404(db, Tenant, tenant_id, resource="tenant")
    if row.status == TenantStatus.ACTIVE:
        new_status = TenantStatus.SUSPENDED
    else:
        new_status = TenantStatus.ACTIVE
    await crud.update(
        db,
        row,
        {"status": new_status},
        resource="tenant",
        audit_fields=("code", "name", "status"),
        label=row.code,
    )
    return TenantToggleOut(id=row.id, status=str(row.status))


__all__ = ["router"]
