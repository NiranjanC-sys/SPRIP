"""Forecast generation and listing."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from speaker_roi_api.deps import PageParams, ReadOnlySession, TenantSession, require
from speaker_roi_api.schemas.common import Page
from speaker_roi_api.schemas.forecasts import ForecastCreate, ForecastOut, ForecastTaskOut
from speaker_roi_api.security.rbac import Permission
from speaker_roi_api.services import crud
from speaker_roi_core.models.analytics import Forecast

router = APIRouter(tags=["Forecasts"])


def _forecast_out(row: Forecast, *, brand_name: str | None = None) -> ForecastOut:
    return ForecastOut(
        id=row.id,
        brand_id=row.brand_id,
        brand_name=brand_name,
        period_start=None,
        period_end=None,
        predicted_nrx=float(row.point_estimate) if row.point_estimate is not None else None,
        predicted_revenue=float(row.expected_net_roi) if row.expected_net_roi is not None else None,
        confidence_low=float(row.pi_low) if row.pi_low is not None else None,
        confidence_high=float(row.pi_high) if row.pi_high is not None else None,
        model_version=str(row.model_version_id) if row.model_version_id is not None else None,
        created_at=row.created_at,
    )


@router.get(
    "/forecasts",
    response_model=Page[ForecastOut],
    summary="List forecasts",
    dependencies=[Depends(require(Permission.FORECAST_READ))],
)
async def list_forecasts(
    db: ReadOnlySession,
    page: PageParams,
    brand_id: Annotated[uuid.UUID | None, Query(alias="brandId")] = None,
) -> Page[ForecastOut]:
    from sqlalchemy import select

    from speaker_roi_core.models.core import Brand

    stmt = select(Forecast)
    if brand_id is not None:
        stmt = stmt.where(Forecast.brand_id == brand_id)
    rows, cursor, _ = await crud.paginate(
        db, stmt, page, sort_column=Forecast.created_at, id_column=Forecast.id
    )

    # Batch-fetch brand names via ORM
    brand_names: dict[uuid.UUID, str] = {}
    bids = {r.brand_id for r in rows if r.brand_id is not None}
    if bids:
        bn_rows = (
            await db.execute(select(Brand.id, Brand.name).where(Brand.id.in_(bids)))
        ).all()
        brand_names = {r[0]: r[1] for r in bn_rows}

    return Page(
        items=[
            _forecast_out(
                r,
                brand_name=brand_names.get(r.brand_id) if r.brand_id else None,
            )
            for r in rows
        ],
        next_cursor=cursor,
    )


@router.get(
    "/forecasts/{forecast_id}",
    response_model=ForecastOut,
    summary="Get a single forecast",
    dependencies=[Depends(require(Permission.FORECAST_READ))],
)
async def get_forecast(db: ReadOnlySession, forecast_id: uuid.UUID) -> ForecastOut:
    from sqlalchemy import select

    from speaker_roi_core.models.core import Brand

    row = await crud.get_or_404(db, Forecast, forecast_id, resource="forecast")

    brand_name: str | None = None
    if row.brand_id is not None:
        brand_name = (
            await db.execute(select(Brand.name).where(Brand.id == row.brand_id))
        ).scalar()

    return _forecast_out(row, brand_name=brand_name)


@router.post(
    "/forecasts",
    response_model=ForecastTaskOut,
    status_code=202,
    summary="Trigger forecast generation",
    dependencies=[Depends(require(Permission.ANALYSIS_RUN))],
)
async def create_forecast(db: TenantSession, payload: ForecastCreate) -> ForecastTaskOut:
    # Celery integration point: when the worker package is available on the API's
    # Python path, replace the placeholder below with:
    #   celery_app.send_task(
    #       "analytics.generate_forecast",
    #       args=[str(payload.brand_id), payload.horizon_months],
    #   )
    # For now, return a placeholder acknowledging the request.
    task_id = str(uuid.uuid4())
    return ForecastTaskOut(task_id=task_id, status="QUEUED")


__all__ = ["router"]
