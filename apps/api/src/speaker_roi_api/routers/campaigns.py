"""Campaign management."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.campaigns import CampaignCreate, CampaignOut, CampaignPatch
from speaker_roi_api.schemas.common import Acknowledged, AuditStamp, Page
from speaker_roi_api.schemas.master_data import DeactivateRequest
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.enums import CampaignStatus
from speaker_roi_core.errors import ValidationError
from speaker_roi_core.models.core import Brand, Campaign, Event

router = APIRouter(tags=["Campaigns"])

_AUDIT = (
    "code",
    "name",
    "brand_id",
    "objective",
    "start_date",
    "end_date",
    "status",
    "planned_budget",
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


def _out(
    row: Campaign, *, brand_name: str | None = None, event_count: int | None = None
) -> CampaignOut:
    return CampaignOut(
        id=row.id,
        code=row.code,
        name=row.name,
        brand_id=row.brand_id,
        brand_name=brand_name,
        objective=row.objective,
        topic_code=row.topic_code,
        start_date=row.start_date,
        end_date=row.end_date,
        status=str(row.status),
        owner_user_id=row.owner_user_id,
        planned_budget=float(row.planned_budget) if row.planned_budget is not None else None,
        currency=row.currency,
        event_count=event_count,
        is_active=row.status != CampaignStatus.CANCELLED,
        audit=_stamp(row),
    )


@router.get(
    "/campaigns",
    response_model=Page[CampaignOut],
    summary="List campaigns",
    dependencies=[Depends(require(Permission.CAMPAIGN_READ))],
)
async def list_campaigns(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    campaign_status: Annotated[CampaignStatus | None, Query(alias="status")] = None,
    include_inactive: Annotated[bool, Query(alias="includeInactive")] = False,
) -> Page[CampaignOut]:
    principal = current_principal()
    stmt = select(Campaign).options(selectinload(Campaign.brand))
    if brand_id is not None:
        stmt = stmt.where(Campaign.brand_id == brand_id)
    if campaign_status is not None:
        stmt = stmt.where(Campaign.status == campaign_status)
    if not include_inactive:
        stmt = stmt.where(Campaign.status != CampaignStatus.CANCELLED)
    if principal is not None and principal.brand_scope is not None:
        stmt = stmt.where(Campaign.brand_id.in_(principal.brand_scope))

    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Campaign.start_date, id_column=Campaign.id
    )

    counts: dict[uuid.UUID, int] = {}
    if rows:
        counted = await db.execute(
            select(Event.campaign_id, func.count())
            .where(Event.campaign_id.in_([r.id for r in rows]))
            .group_by(Event.campaign_id)
        )
        counts = {cid: int(n) for cid, n in counted.all()}

    return Page(
        items=[
            _out(r, brand_name=r.brand.name if r.brand else None, event_count=counts.get(r.id, 0))
            for r in rows
        ],
        next_cursor=cursor,
    )


@router.post(
    "/campaigns",
    response_model=CampaignOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a campaign",
    dependencies=[Depends(require(Permission.CAMPAIGN_WRITE)), Depends(deny_vendor)],
)
async def create_campaign(db: TenantSession, payload: CampaignCreate) -> CampaignOut:
    brand = await crud.get_or_404(db, Brand, payload.brand_id, resource="brand")
    if not brand.is_active:
        raise ValidationError(
            "That brand has been retired.",
            remediation="Reactivate the brand first, or choose another.",
        )
    row = await crud.create(
        db,
        Campaign,
        payload.model_dump(exclude_unset=True),
        resource="campaign",
        audit_fields=_AUDIT,
        label=payload.code,
        actor_id=_actor_id(),
    )
    return _out(row, brand_name=brand.name, event_count=0)


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignOut,
    summary="Get a campaign",
    dependencies=[Depends(require(Permission.CAMPAIGN_READ))],
)
async def get_campaign(db: ReadOnlySession, campaign_id: uuid.UUID) -> CampaignOut:
    row = await crud.get_or_404(
        db, Campaign, campaign_id, resource="campaign", options=[selectinload(Campaign.brand)]
    )
    return _out(row, brand_name=row.brand.name if row.brand else None)


@router.patch(
    "/campaigns/{campaign_id}",
    response_model=CampaignOut,
    summary="Update a campaign",
    dependencies=[Depends(require(Permission.CAMPAIGN_WRITE)), Depends(deny_vendor)],
)
async def patch_campaign(
    db: TenantSession, campaign_id: uuid.UUID, payload: CampaignPatch
) -> CampaignOut:
    row = await crud.get_or_404(
        db, Campaign, campaign_id, resource="campaign", options=[selectinload(Campaign.brand)]
    )
    await crud.update(
        db,
        row,
        crud.patch_changes(
            payload,
            "name",
            "objective",
            "topic_code",
            "start_date",
            "end_date",
            "status",
            "owner_user_id",
            "planned_budget",
            "currency",
        ),
        resource="campaign",
        audit_fields=_AUDIT,
        expected_version=payload.version,
        label=row.code,
        actor_id=_actor_id(),
    )
    return _out(row, brand_name=row.brand.name if row.brand else None)


@router.post(
    "/campaigns/{campaign_id}/deactivate",
    response_model=Acknowledged,
    summary="Cancel a campaign",
    dependencies=[Depends(require(Permission.CAMPAIGN_WRITE)), Depends(deny_vendor)],
)
async def cancel_campaign(
    db: TenantSession, campaign_id: uuid.UUID, payload: DeactivateRequest
) -> Acknowledged:
    row = await crud.get_or_404(db, Campaign, campaign_id, resource="campaign")
    await crud.update(
        db,
        row,
        {"status": CampaignStatus.CANCELLED},
        resource="campaign",
        audit_fields=_AUDIT,
        label=row.code,
        actor_id=_actor_id(),
        reason=payload.reason,
    )
    return Acknowledged()


__all__ = ["router"]
