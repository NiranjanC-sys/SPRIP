"""ROI results and portfolio summary."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from speaker_roi_api.deps import PageParams, ReadOnlySession, deny_vendor, require
from speaker_roi_api.schemas.common import AuditStamp, Page
from speaker_roi_api.schemas.roi import BrandRoiSummary, RoiResultOut, RoiSummaryOut
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.models.analytics import RoiResult
from speaker_roi_core.models.core import Brand, Event

router = APIRouter(tags=["ROI"])


def _stamp(row: Any) -> AuditStamp:
    return AuditStamp(
        created_at=row.created_at,
        updated_at=getattr(row, "updated_at", None),
        created_by=getattr(row, "created_by", None),
        updated_by=getattr(row, "updated_by", None),
        version=getattr(row, "row_version", None),
    )


def _result_out(
    row: RoiResult,
    *,
    brand_name: str | None = None,
    event_name: str | None = None,
) -> RoiResultOut:
    return RoiResultOut(
        id=row.id,
        run_id=row.run_id,
        level=str(row.level),
        event_id=row.event_id,
        event_name=event_name,
        brand_id=row.brand_id,
        brand_name=brand_name,
        incremental_nrx=float(row.incremental_nrx) if row.incremental_nrx is not None else None,
        gross_contribution=float(row.gross_contribution) if row.gross_contribution is not None else None,
        total_cost=float(row.total_cost),
        net_roi=float(row.net_roi) if row.net_roi is not None else None,
        benefit_cost_ratio=float(row.benefit_cost_ratio) if row.benefit_cost_ratio is not None else None,
        evidence_grade=str(row.evidence_grade),
        currency=row.currency,
        audit=_stamp(row),
    )


@router.get(
    "/roi/results",
    response_model=Page[RoiResultOut],
    summary="List ROI results",
    dependencies=[Depends(require(Permission.ROI_READ)), Depends(deny_vendor)],
)
async def list_roi_results(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
    level: Annotated[str | None, Query()] = None,
    min_bcr: Annotated[float | None, Query(alias="minBcr")] = None,
) -> Page[RoiResultOut]:
    stmt = select(RoiResult)
    if brand_id is not None:
        stmt = stmt.where(RoiResult.brand_id == brand_id)
    if level is not None:
        stmt = stmt.where(RoiResult.level == level)
    if min_bcr is not None:
        stmt = stmt.where(RoiResult.benefit_cost_ratio >= min_bcr)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=RoiResult.created_at, id_column=RoiResult.id
    )

    # Batch-fetch brand names via ORM
    brand_names: dict[uuid.UUID, str] = {}
    brand_ids = {r.brand_id for r in rows if r.brand_id is not None}
    if brand_ids:
        bn_rows = (
            await db.execute(select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids)))
        ).all()
        brand_names = {r[0]: r[1] for r in bn_rows}

    # Batch-fetch event names via ORM
    event_names: dict[uuid.UUID, str] = {}
    event_ids = {r.event_id for r in rows if r.event_id is not None}
    if event_ids:
        en_rows = (
            await db.execute(select(Event.id, Event.name).where(Event.id.in_(event_ids)))
        ).all()
        event_names = {r[0]: r[1] for r in en_rows}

    return Page(
        items=[
            _result_out(
                r,
                brand_name=brand_names.get(r.brand_id) if r.brand_id else None,
                event_name=event_names.get(r.event_id) if r.event_id else None,
            )
            for r in rows
        ],
        next_cursor=cursor,
    )


@router.get(
    "/roi/results/{result_id}",
    response_model=RoiResultOut,
    summary="Get a single ROI result",
    dependencies=[Depends(require(Permission.ROI_READ)), Depends(deny_vendor)],
)
async def get_roi_result(db: ReadOnlySession, result_id: uuid.UUID) -> RoiResultOut:
    row = await crud.get_or_404(db, RoiResult, result_id, resource="roi_result")

    brand_name: str | None = None
    if row.brand_id is not None:
        brand_name = (
            await db.execute(select(Brand.name).where(Brand.id == row.brand_id))
        ).scalar()

    event_name: str | None = None
    if row.event_id is not None:
        event_name = (
            await db.execute(select(Event.name).where(Event.id == row.event_id))
        ).scalar()

    return _result_out(row, brand_name=brand_name, event_name=event_name)


@router.get(
    "/roi/summary",
    response_model=RoiSummaryOut,
    summary="Aggregate ROI metrics across brands",
    dependencies=[Depends(require(Permission.ROI_READ)), Depends(deny_vendor)],
)
async def roi_summary(db: ReadOnlySession) -> RoiSummaryOut:
    stmt = (
        select(
            RoiResult.brand_id,
            func.count().label("total_events"),
            func.avg(RoiResult.benefit_cost_ratio).label("avg_bcr"),
            func.sum(RoiResult.total_cost).label("total_spend"),
            func.sum(RoiResult.net_roi).label("net_roi"),
        )
        .where(RoiResult.brand_id.is_not(None))
        .group_by(RoiResult.brand_id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    brands: list[BrandRoiSummary] = []
    portfolio_spend = 0.0
    portfolio_contribution = 0.0
    portfolio_cost = 0.0
    for row in rows:
        spend = float(row.total_spend) if row.total_spend is not None else 0.0
        nr = float(row.net_roi) if row.net_roi is not None else None
        brands.append(
            BrandRoiSummary(
                brand_id=row.brand_id,
                brand_name=None,
                total_events=int(row.total_events),
                avg_bcr=float(row.avg_bcr) if row.avg_bcr is not None else None,
                total_spend=spend,
                net_roi=nr,
            )
        )
        portfolio_spend += spend
        portfolio_cost += spend
        if nr is not None:
            portfolio_contribution += nr + spend

    portfolio_bcr = (portfolio_contribution / portfolio_cost) if portfolio_cost > 0 else None

    return RoiSummaryOut(
        brands=brands,
        portfolio_bcr=portfolio_bcr,
        total_spend=portfolio_spend,
    )


__all__ = ["router"]
