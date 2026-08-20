"""Analytical tasks: ROI computation, portfolio aggregation, forecasting.

These are the heaviest operations in the system. A single compute_roi call reads a tenant's
full event and prescription history, fits causal models, and writes an evidence bundle.
Running them in the request path would mean multi-minute responses that time out behind
any reverse proxy.
"""

from __future__ import annotations

import uuid

from speaker_roi_worker import celery_app

from speaker_roi_core.logging import get_logger

log = get_logger(__name__)


@celery_app.task(bind=True, name="analytics.compute_roi", max_retries=2)
def compute_roi(
    self,
    tenant_id: str,
    brand_id: str,
    period_start: str,
    period_end: str,
    requested_by: str,
) -> dict:
    """Compute ROI for a brand over a date range.

    Reads event attendance, prescription data and finance assumptions, then fits
    a causal model to estimate the incremental impact of speaker programmes.
    """
    log.info(
        "task.compute_roi.started",
        tenant_id=tenant_id,
        brand_id=brand_id,
        period=f"{period_start}/{period_end}",
    )
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: implement actual model fitting
            result = {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "period_start": period_start,
                "period_end": period_end,
                "status": "completed",
                "roi_estimate": None,
                "confidence_interval": None,
                "model_version": "stub-v0",
            }
            log.info("task.compute_roi.completed", tenant_id=tenant_id, brand_id=brand_id)
            return result

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(bind=True, name="analytics.refresh_portfolio_aggregates", max_retries=2)
def refresh_portfolio_aggregates(
    self,
    tenant_id: str,
    requested_by: str | None = None,
) -> dict:
    """Refresh pre-computed portfolio aggregates for a tenant.

    Aggregates event counts, spend totals and prescription volumes per brand,
    storing results in the portfolio_aggregates table for fast dashboard reads.
    """
    log.info("task.refresh_portfolio.started", tenant_id=tenant_id)
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: aggregate from events + prescriptions into portfolio_aggregates
            result = {
                "tenant_id": tenant_id,
                "status": "completed",
                "brands_refreshed": 0,
            }
            log.info("task.refresh_portfolio.completed", tenant_id=tenant_id)
            return result

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(bind=True, name="analytics.generate_forecast", max_retries=2)
def generate_forecast(
    self,
    tenant_id: str,
    brand_id: str,
    horizon_months: int = 12,
    requested_by: str | None = None,
) -> dict:
    """Generate a forward-looking forecast for a brand.

    Uses historical event and prescription data to project expected ROI
    under current speaker programme assumptions.
    """
    log.info(
        "task.generate_forecast.started",
        tenant_id=tenant_id,
        brand_id=brand_id,
        horizon_months=horizon_months,
    )
    import asyncio

    from speaker_roi_core.db.session import session_scope

    async def _run() -> dict:
        tid = uuid.UUID(tenant_id)
        async with session_scope(tenant_id=tid) as db:
            # TODO: time-series forecasting
            result = {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "horizon_months": horizon_months,
                "status": "completed",
                "forecast": [],
                "model_version": "stub-v0",
            }
            log.info("task.generate_forecast.completed", tenant_id=tenant_id, brand_id=brand_id)
            return result

    return asyncio.get_event_loop().run_until_complete(_run())
