"""Finance: event costs, assumptions and ROI results."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, deny_vendor, require
from speaker_roi_api.schemas.common import AuditStamp, Page
from speaker_roi_api.schemas.finance import (
    EventCostCreate,
    EventCostOut,
    EventCostPatch,
    FinanceAssumptionCreate,
    FinanceAssumptionOut,
    FinanceAssumptionPatch,
    RoiResultOut,
)
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.context import current_principal
from speaker_roi_core.models.analytics import RoiResult
from speaker_roi_core.models.core import EventCost, FinanceAssumption

router = APIRouter(tags=["Finance"])


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


def _cost_out(row: EventCost) -> EventCostOut:
    return EventCostOut(
        id=row.id,
        event_id=row.event_id,
        category_code=row.category_code,
        description=row.description,
        amount=float(row.amount) if row.amount is not None else 0.0,
        currency=row.currency,
        vendor_id=row.vendor_id,
        is_active=row.is_active,
        audit=_stamp(row),
    )


def _assumption_out(row: FinanceAssumption) -> FinanceAssumptionOut:
    return FinanceAssumptionOut(
        id=row.id,
        finance_version_id=row.finance_version_id,
        brand_id=row.brand_id,
        scenario=str(row.scenario),
        contribution_per_nrx=float(row.contribution_per_nrx),
        currency=row.currency,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        persistence_months=row.persistence_months,
        note=row.note,
        audit=_stamp(row),
    )


def _roi_out(row: RoiResult) -> RoiResultOut:
    return RoiResultOut(
        id=row.id,
        run_id=row.run_id,
        level=str(row.level),
        event_id=row.event_id,
        brand_id=row.brand_id,
        finance_version_id=row.finance_version_id,
        incremental_nrx=float(row.incremental_nrx) if row.incremental_nrx is not None else None,
        gross_contribution=(
            float(row.gross_contribution) if row.gross_contribution is not None else None
        ),
        total_cost=float(row.total_cost),
        net_roi=float(row.net_roi) if row.net_roi is not None else None,
        benefit_cost_ratio=(
            float(row.benefit_cost_ratio) if row.benefit_cost_ratio is not None else None
        ),
        currency=row.currency,
        evidence_status=str(row.evidence_status),
        evidence_grade=str(row.evidence_grade),
        publication_state=str(row.publication_state),
        audit=_stamp(row),
    )


_COST_AUDIT = ("event_id", "category_code", "amount", "currency", "is_active")
_ASSUMPTION_AUDIT = (
    "brand_id",
    "scenario",
    "contribution_per_nrx",
    "effective_from",
    "effective_to",
)


@router.get(
    "/events/{event_id}/costs",
    response_model=list[EventCostOut],
    summary="List costs for an event",
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def list_event_costs(db: ReadOnlySession, event_id: uuid.UUID) -> list[EventCostOut]:
    result = await db.execute(
        select(EventCost).where(EventCost.event_id == event_id).order_by(EventCost.created_at)
    )
    return [_cost_out(r) for r in result.scalars().all()]


@router.post(
    "/events/{event_id}/costs",
    response_model=EventCostOut,
    status_code=201,
    summary="Add a cost line to an event",
    dependencies=[Depends(require(Permission.FINANCE_ASSUMPTION_WRITE)), Depends(deny_vendor)],
)
async def create_event_cost(
    db: TenantSession, event_id: uuid.UUID, payload: EventCostCreate
) -> EventCostOut:
    data = payload.model_dump(exclude_unset=True)
    data["event_id"] = event_id
    row = await crud.create(
        db,
        EventCost,
        data,
        resource="event_cost",
        audit_fields=_COST_AUDIT,
        label=f"{event_id}:{payload.category_code}",
        actor_id=_actor_id(),
    )
    return _cost_out(row)


@router.patch(
    "/events/{event_id}/costs/{cost_id}",
    response_model=EventCostOut,
    summary="Update a cost line",
    dependencies=[Depends(require(Permission.FINANCE_ASSUMPTION_WRITE)), Depends(deny_vendor)],
)
async def patch_event_cost(
    db: TenantSession, event_id: uuid.UUID, cost_id: uuid.UUID, payload: EventCostPatch
) -> EventCostOut:
    row = await crud.get_or_404(db, EventCost, cost_id, resource="event_cost")
    await crud.update(
        db,
        row,
        crud.patch_changes(payload, "category_code", "description", "amount", "currency"),
        resource="event_cost",
        audit_fields=_COST_AUDIT,
        expected_version=payload.version,
        label=f"{event_id}:{row.category_code}",
        actor_id=_actor_id(),
    )
    return _cost_out(row)


@router.get(
    "/finance/assumptions",
    response_model=Page[FinanceAssumptionOut],
    summary="List finance assumptions",
    dependencies=[Depends(require(Permission.FINANCE_READ))],
)
async def list_assumptions(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
) -> Page[FinanceAssumptionOut]:
    stmt = select(FinanceAssumption)
    if brand_id is not None:
        stmt = stmt.where(FinanceAssumption.brand_id == brand_id)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=FinanceAssumption.effective_from, id_column=FinanceAssumption.id
    )
    return Page(items=[_assumption_out(r) for r in rows], next_cursor=cursor)


@router.post(
    "/finance/assumptions",
    response_model=FinanceAssumptionOut,
    status_code=201,
    summary="Create a finance assumption",
    dependencies=[Depends(require(Permission.FINANCE_ASSUMPTION_WRITE)), Depends(deny_vendor)],
)
async def create_assumption(
    db: TenantSession, payload: FinanceAssumptionCreate
) -> FinanceAssumptionOut:
    row = await crud.create(
        db,
        FinanceAssumption,
        payload.model_dump(exclude_unset=True),
        resource="finance_assumption",
        audit_fields=_ASSUMPTION_AUDIT,
        label=f"{payload.brand_id}:{payload.scenario}",
        actor_id=_actor_id(),
    )
    return _assumption_out(row)


@router.patch(
    "/finance/assumptions/{assumption_id}",
    response_model=FinanceAssumptionOut,
    summary="Update a finance assumption",
    dependencies=[Depends(require(Permission.FINANCE_ASSUMPTION_WRITE)), Depends(deny_vendor)],
)
async def patch_assumption(
    db: TenantSession, assumption_id: uuid.UUID, payload: FinanceAssumptionPatch
) -> FinanceAssumptionOut:
    row = await crud.get_or_404(db, FinanceAssumption, assumption_id, resource="finance_assumption")
    await crud.update(
        db,
        row,
        crud.patch_changes(
            payload, "contribution_per_nrx", "effective_to", "persistence_months", "note"
        ),
        resource="finance_assumption",
        audit_fields=_ASSUMPTION_AUDIT,
        expected_version=payload.version,
        label=f"{row.brand_id}:{row.scenario}",
        actor_id=_actor_id(),
    )
    return _assumption_out(row)


    # ROI results endpoints moved to routers/roi.py (enriched with brand/event names)


__all__ = ["router"]
