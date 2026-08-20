"""HCP (Healthcare Professional) management.

Professional-grain only - no PII. See plan.md §15: names, phones, emails, addresses and ABHA
identifiers are never ingested. Measurement needs specialty, geography and segment, not identity.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.hcps import (
    AttendedEventItem,
    HcpCreate,
    HcpDetailOut,
    HcpOut,
    HcpPatch,
    RxHistoryItem,
)
from speaker_roi_api.schemas.master_data import DeactivateRequest
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.models.core import Hcp

router = APIRouter(tags=["HCPs"])

_HCP_AUDIT = (
    "master_hcp_id",
    "specialty_code",
    "region_code",
    "practice_type",
    "segment",
    "city_code",
    "is_active",
)


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


def _hcp_out(row: Hcp) -> HcpOut:
    return HcpOut(
        id=row.id,
        master_hcp_id=row.master_hcp_id,
        specialty_code=row.specialty_code,
        region_code=row.region_code,
        practice_type=row.practice_type,
        segment=row.segment,
        city_code=row.city_code,
        is_active=row.is_active,
        first_seen_on=row.first_seen_on,
        audit=_stamp(row),
    )


@router.get(
    "/hcps",
    response_model=Page[HcpOut],
    summary="List HCPs",
    dependencies=[Depends(require(Permission.HCP_READ))],
)
async def list_hcps(
    db: ReadOnlySession,
    page: PageParams,
    specialty: Annotated[str | None, Query(alias="specialty", max_length=60)] = None,
    region: Annotated[str | None, Query(alias="region", max_length=60)] = None,
    segment: Annotated[str | None, Query(alias="segment", max_length=60)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[HcpOut]:
    from sqlalchemy import func, select

    stmt = select(Hcp)
    if not include_inactive:
        stmt = stmt.where(Hcp.is_active.is_(True))
    if specialty:
        stmt = stmt.where(Hcp.specialty_code == specialty)
    if region:
        stmt = stmt.where(Hcp.region_code == region)
    if segment:
        stmt = stmt.where(Hcp.segment == segment)
    if q:
        pattern = f"%{q.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = stmt.where(
            Hcp.master_hcp_id.like(pattern, escape="!")
            | func.coalesce(Hcp.specialty_code, "").like(pattern.lower(), escape="!")
        )

    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Hcp.created_at, id_column=Hcp.id
    )
    return Page(items=[_hcp_out(r) for r in rows], next_cursor=cursor)


@router.post(
    "/hcps",
    response_model=HcpOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an HCP",
    dependencies=[Depends(require(Permission.HCP_WRITE)), Depends(deny_vendor)],
)
async def create_hcp(db: TenantSession, payload: HcpCreate) -> HcpOut:
    row = await crud.create(
        db,
        Hcp,
        payload.model_dump(exclude_unset=True),
        resource="hcp",
        audit_fields=_HCP_AUDIT,
        label=payload.master_hcp_id,
        actor_id=_actor_id(),
    )
    return _hcp_out(row)


@router.get(
    "/hcps/{hcp_id}",
    response_model=HcpDetailOut,
    summary="Get an HCP with Rx history and events",
    dependencies=[Depends(require(Permission.HCP_READ))],
)
async def get_hcp(db: ReadOnlySession, hcp_id: uuid.UUID) -> HcpDetailOut:
    from sqlalchemy import select, text

    row = await crud.get_or_404(db, Hcp, hcp_id, resource="hcp")
    base = _hcp_out(row)

    rx_rows = (await db.execute(text(
        "SELECT month, nrx, trx, brand_id "
        "FROM core.hcp_rx_monthly "
        "WHERE hcp_id = :hid "
        "ORDER BY month"
    ), {"hid": hcp_id})).all()

    rx_history = [
        RxHistoryItem(
            month=str(r[0])[:7],
            nrx=float(r[1] or 0),
            trx=float(r[2] or 0),
            brand_id=str(r[3]),
        )
        for r in rx_rows
    ]

    event_rows = (await db.execute(text(
        "SELECT e.id, e.name, e.event_date, e.status, "
        "a.registration_status, a.verified_attended "
        "FROM core.attendance a "
        "JOIN core.events e ON e.id = a.event_id "
        "WHERE a.hcp_id = :hid "
        "ORDER BY e.event_date DESC "
        "LIMIT 50"
    ), {"hid": hcp_id})).all()

    events_attended = [
        AttendedEventItem(
            id=r[0],
            name=r[1],
            date=str(r[2]) if r[2] else None,
            status=str(r[3]) if r[3] else None,
            role=str(r[4]) if r[4] else None,
        )
        for r in event_rows
    ]

    return HcpDetailOut(
        **base.model_dump(by_alias=False),
        rx_history=rx_history,
        events_attended=events_attended,
    )


@router.patch(
    "/hcps/{hcp_id}",
    response_model=HcpOut,
    summary="Update an HCP",
    dependencies=[Depends(require(Permission.HCP_WRITE)), Depends(deny_vendor)],
)
async def patch_hcp(db: TenantSession, hcp_id: uuid.UUID, payload: HcpPatch) -> HcpOut:
    row = await crud.get_or_404(db, Hcp, hcp_id, resource="hcp")
    await crud.update(
        db,
        row,
        crud.patch_changes(
            payload, "specialty_code", "region_code", "practice_type", "segment", "city_code"
        ),
        resource="hcp",
        audit_fields=_HCP_AUDIT,
        expected_version=payload.version,
        label=row.master_hcp_id,
        actor_id=_actor_id(),
    )
    return _hcp_out(row)


@router.post(
    "/hcps/{hcp_id}/deactivate",
    response_model=Acknowledged,
    summary="Deactivate an HCP",
    dependencies=[Depends(require(Permission.HCP_WRITE)), Depends(deny_vendor)],
)
async def deactivate_hcp(
    db: TenantSession, hcp_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    row = await crud.get_or_404(db, Hcp, hcp_id, resource="hcp")
    await crud.deactivate(
        db,
        row,
        resource="hcp",
        audit_fields=_HCP_AUDIT,
        status_field="is_active",
        inactive_value=False,
        reason=payload.reason,
        actor_id=_actor_id(),
    )
    return Acknowledged()


__all__ = ["router"]
