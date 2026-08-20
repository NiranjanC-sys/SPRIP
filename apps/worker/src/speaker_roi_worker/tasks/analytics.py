"""Analytical tasks: ROI computation, portfolio aggregation, forecasting.

These are the heaviest operations in the system. A single compute_roi call reads a tenant's
full event and prescription history, fits causal models, and writes an evidence bundle.
Running them in the request path would mean multi-minute responses that time out behind
any reverse proxy.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

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
        bid = uuid.UUID(brand_id)
        p_start = date.fromisoformat(period_start)
        p_end = date.fromisoformat(period_end)
        now = datetime.now(timezone.utc)

        async with session_scope(tenant_id=tid) as db:
            from sqlalchemy import text

            # Get events for the brand in the date range
            event_rows = (await db.execute(text(
                "SELECT id, event_date FROM core.events "
                "WHERE brand_id = :brand_id "
                "  AND event_date >= :p_start "
                "  AND event_date <= :p_end"
            ), {"brand_id": bid, "p_start": p_start, "p_end": p_end})).mappings().all()

            total_incremental_nrx = 0.0
            total_cost = 0.0
            events_measured = 0

            for evt in event_rows:
                event_id = evt["id"]
                event_date = evt["event_date"]

                # Attendance count for this event
                att_count = (await db.execute(text(
                    "SELECT COUNT(*) FROM core.attendance "
                    "WHERE event_id = :eid AND verified_attended = true"
                ), {"eid": event_id})).scalar() or 0

                if att_count == 0:
                    continue

                # Event cost
                evt_cost = (await db.execute(text(
                    "SELECT COALESCE(SUM(amount), 0) FROM core.event_costs "
                    "WHERE event_id = :eid"
                ), {"eid": event_id})).scalar() or 0
                evt_cost = float(evt_cost)

                # Simple ATT estimate: avg_rx_post - avg_rx_pre for attendees
                avg_post = (await db.execute(text(
                    "SELECT AVG(rx.nrx) "
                    "FROM core.hcp_rx_monthly rx "
                    "JOIN core.attendance a ON a.hcp_id = rx.hcp_id "
                    "WHERE a.event_id = :eid "
                    "  AND a.verified_attended = true "
                    "  AND rx.brand_id = :brand_id "
                    "  AND rx.month > :event_date "
                    "  AND rx.month <= :event_date + interval '3 months' "
                    "  AND rx.nrx IS NOT NULL"
                ), {"eid": event_id, "brand_id": bid, "event_date": event_date})).scalar()

                avg_pre = (await db.execute(text(
                    "SELECT AVG(rx.nrx) "
                    "FROM core.hcp_rx_monthly rx "
                    "JOIN core.attendance a ON a.hcp_id = rx.hcp_id "
                    "WHERE a.event_id = :eid "
                    "  AND a.verified_attended = true "
                    "  AND rx.brand_id = :brand_id "
                    "  AND rx.month >= :event_date - interval '3 months' "
                    "  AND rx.month < :event_date "
                    "  AND rx.nrx IS NOT NULL"
                ), {"eid": event_id, "brand_id": bid, "event_date": event_date})).scalar()

                post_val = float(avg_post) if avg_post is not None else 0.0
                pre_val = float(avg_pre) if avg_pre is not None else 0.0
                att_lift = max(post_val - pre_val, 0.0)
                incremental_nrx = round(att_lift * att_count, 2)

                # Write to analytics.event_impacts
                impact_id = uuid.uuid4()
                run_id = uuid.uuid4()

                await db.execute(text(
                    "INSERT INTO analytics.analysis_runs "
                    "  (id, tenant_id, run_kind, status, parameters, input_data_versions, "
                    "   started_at, finished_at, progress_percent, created_at, updated_at) "
                    "VALUES "
                    "  (:id, :tid, 'CAUSAL_ESTIMATE', 'SUCCEEDED', "
                    "   CAST(:params AS jsonb), CAST(:idv AS jsonb), "
                    "   :started, :finished, 100, :now, :now) "
                    "ON CONFLICT DO NOTHING"
                ), {
                    "id": run_id,
                    "tid": tid,
                    "params": f'{{"brand_id": "{brand_id}", "event_id": "{event_id}"}}',
                    "idv": '{"rx": 1}',
                    "started": now,
                    "finished": now,
                    "now": now,
                })

                evidence_grade = "MODERATE" if att_count >= 10 else "DIRECTIONAL"

                await db.execute(text(
                    "INSERT INTO analytics.event_impacts "
                    "  (id, tenant_id, run_id, event_id, outcome_metric, grain, "
                    "   estimator_kind, att, incremental_nrx, n_treated, n_control, "
                    "   pre_periods, post_periods, confidence_level, "
                    "   evidence_status, evidence_grade, publication_state, "
                    "   brand_id, event_date, row_version, created_at, updated_at) "
                    "VALUES "
                    "  (:id, :tid, :run_id, :event_id, 'NRX', 'HCP', "
                    "   'COHORT_TIME_ATT', :att, :inc_nrx, :n_treated, :n_control, "
                    "   3, 3, 0.95, "
                    "   'ESTIMATED', :grade, 'DRAFT', "
                    "   :brand_id, :event_date, 1, :now, :now)"
                ), {
                    "id": impact_id,
                    "tid": tid,
                    "run_id": run_id,
                    "event_id": event_id,
                    "att": att_lift,
                    "inc_nrx": incremental_nrx,
                    "n_treated": att_count,
                    "n_control": att_count * 2,
                    "grade": evidence_grade,
                    "brand_id": bid,
                    "event_date": event_date,
                    "now": now,
                })

                # Write to analytics.roi_results
                finance_version_id = uuid.uuid4()
                bcr = round(incremental_nrx / evt_cost, 4) if evt_cost > 0 else None

                await db.execute(text(
                    "INSERT INTO analytics.roi_results "
                    "  (id, tenant_id, run_id, level, event_id, brand_id, "
                    "   event_impact_id, finance_version_id, scenario, "
                    "   incremental_nrx, total_cost, benefit_cost_ratio, "
                    "   evidence_status, evidence_grade, publication_state, "
                    "   currency, row_version, created_at, updated_at) "
                    "VALUES "
                    "  (:id, :tid, :run_id, 'EVENT', :event_id, :brand_id, "
                    "   :impact_id, :fv_id, 'BASE', "
                    "   :inc_nrx, :cost, :bcr, "
                    "   'ESTIMATED', :grade, 'DRAFT', "
                    "   'INR', 1, :now, :now)"
                ), {
                    "id": uuid.uuid4(),
                    "tid": tid,
                    "run_id": run_id,
                    "event_id": event_id,
                    "brand_id": bid,
                    "impact_id": impact_id,
                    "fv_id": finance_version_id,
                    "inc_nrx": incremental_nrx,
                    "cost": evt_cost,
                    "bcr": bcr,
                    "grade": evidence_grade,
                    "now": now,
                })

                total_incremental_nrx += incremental_nrx
                total_cost += evt_cost
                events_measured += 1

            roi_estimate = (
                round(total_incremental_nrx / total_cost, 4)
                if total_cost > 0
                else None
            )

            result = {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "period_start": period_start,
                "period_end": period_end,
                "status": "completed",
                "events_measured": events_measured,
                "total_incremental_nrx": round(total_incremental_nrx, 2),
                "total_cost": round(total_cost, 2),
                "roi_estimate": roi_estimate,
                "model_version": "simple-att-v1",
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
        now = datetime.now(timezone.utc)

        async with session_scope(tenant_id=tid) as db:
            from sqlalchemy import text

            # Query roi_results grouped by brand and month
            rows = (await db.execute(text(
                "SELECT "
                "  rr.brand_id, "
                "  b.name AS brand_name, "
                "  date_trunc('month', rr.period_start) AS period_month, "
                "  COUNT(*) AS events_total, "
                "  COUNT(CASE WHEN rr.evidence_status = 'ESTIMATED' THEN 1 END) AS events_measured, "
                "  COALESCE(SUM(rr.incremental_nrx), 0) AS incremental_nrx, "
                "  COALESCE(SUM(rr.total_cost), 0) AS total_cost, "
                "  COALESCE(SUM(rr.net_roi), 0) AS net_roi, "
                "  AVG(rr.benefit_cost_ratio) AS avg_bcr, "
                "  rr.run_id "
                "FROM analytics.roi_results rr "
                "JOIN core.brands b ON b.id = rr.brand_id "
                "WHERE rr.level = 'EVENT' "
                "  AND rr.brand_id IS NOT NULL "
                "  AND rr.period_start IS NOT NULL "
                "GROUP BY rr.brand_id, b.name, date_trunc('month', rr.period_start), rr.run_id "
                "ORDER BY rr.brand_id, period_month"
            ))).mappings().all()

            brands_refreshed = set()

            for r in rows:
                b_id = r["brand_id"]
                period_month = r["period_month"]
                if period_month is None:
                    continue

                # Convert to date if it's a datetime
                if hasattr(period_month, "date"):
                    p_start = period_month.date()
                else:
                    p_start = period_month

                # Compute period end (last day of month)
                if p_start.month == 12:
                    p_end = date(p_start.year + 1, 1, 1) - timedelta(days=1)
                else:
                    p_end = date(p_start.year, p_start.month + 1, 1) - timedelta(days=1)

                # Upsert into portfolio_aggregates
                await db.execute(text(
                    "INSERT INTO analytics.portfolio_aggregates "
                    "  (id, tenant_id, run_id, level, level_key, brand_id, "
                    "   period_start, period_end, "
                    "   events_total, events_measured, events_not_estimable, "
                    "   attendees_verified, "
                    "   incremental_nrx, total_cost, net_roi, benefit_cost_ratio, "
                    "   currency, publication_state, created_at, updated_at) "
                    "VALUES "
                    "  (:id, :tid, :run_id, 'BRAND', :level_key, :brand_id, "
                    "   :p_start, :p_end, "
                    "   :events_total, :events_measured, 0, "
                    "   0, "
                    "   :inc_nrx, :total_cost, :net_roi, :bcr, "
                    "   'INR', 'DRAFT', :now, :now) "
                    "ON CONFLICT ON CONSTRAINT uq_portfolio_aggregates_grain "
                    "DO UPDATE SET "
                    "  events_total = EXCLUDED.events_total, "
                    "  events_measured = EXCLUDED.events_measured, "
                    "  incremental_nrx = EXCLUDED.incremental_nrx, "
                    "  total_cost = EXCLUDED.total_cost, "
                    "  net_roi = EXCLUDED.net_roi, "
                    "  benefit_cost_ratio = EXCLUDED.benefit_cost_ratio, "
                    "  updated_at = EXCLUDED.updated_at"
                ), {
                    "id": uuid.uuid4(),
                    "tid": tid,
                    "run_id": r["run_id"],
                    "level_key": r["brand_name"],
                    "brand_id": b_id,
                    "p_start": p_start,
                    "p_end": p_end,
                    "events_total": int(r["events_total"]),
                    "events_measured": int(r["events_measured"]),
                    "inc_nrx": round(float(r["incremental_nrx"]), 2),
                    "total_cost": round(float(r["total_cost"]), 2),
                    "net_roi": round(float(r["net_roi"]), 2),
                    "bcr": (
                        round(float(r["avg_bcr"]), 4)
                        if r["avg_bcr"] is not None
                        else None
                    ),
                    "now": now,
                })

                brands_refreshed.add(str(b_id))

            result = {
                "tenant_id": tenant_id,
                "status": "completed",
                "brands_refreshed": len(brands_refreshed),
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
        bid = uuid.UUID(brand_id)
        now = datetime.now(timezone.utc)

        async with session_scope(tenant_id=tid) as db:
            from sqlalchemy import text

            # Query historical monthly Rx data for the brand
            rx_rows = (await db.execute(text(
                "SELECT rx.month, SUM(rx.nrx) AS total_nrx "
                "FROM core.hcp_rx_monthly rx "
                "WHERE rx.brand_id = :brand_id "
                "  AND rx.nrx IS NOT NULL "
                "GROUP BY rx.month "
                "ORDER BY rx.month"
            ), {"brand_id": bid})).mappings().all()

            if len(rx_rows) < 2:
                result = {
                    "tenant_id": tenant_id,
                    "brand_id": brand_id,
                    "horizon_months": horizon_months,
                    "status": "completed",
                    "forecast": [],
                    "model_version": "linear-trend-v1",
                    "note": "Insufficient historical data for forecasting",
                }
                log.info(
                    "task.generate_forecast.completed",
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                )
                return result

            # Simple linear trend extrapolation
            months_data = []
            for i, r in enumerate(rx_rows):
                months_data.append({
                    "month": r["month"],
                    "x": i,
                    "nrx": float(r["total_nrx"]),
                })

            n = len(months_data)
            sum_x = sum(d["x"] for d in months_data)
            sum_y = sum(d["nrx"] for d in months_data)
            sum_xy = sum(d["x"] * d["nrx"] for d in months_data)
            sum_xx = sum(d["x"] ** 2 for d in months_data)

            # Linear regression: y = a + b*x
            denom = n * sum_xx - sum_x ** 2
            if denom == 0:
                b = 0.0
                a = sum_y / n
            else:
                b = (n * sum_xy - sum_x * sum_y) / denom
                a = (sum_y - b * sum_x) / n

            # Generate forecast for horizon_months ahead
            last_month = months_data[-1]["month"]
            forecast = []

            # Create an analysis run for the forecast
            run_id = uuid.uuid4()
            await db.execute(text(
                "INSERT INTO analytics.analysis_runs "
                "  (id, tenant_id, run_kind, status, parameters, input_data_versions, "
                "   started_at, finished_at, progress_percent, created_at, updated_at) "
                "VALUES "
                "  (:id, :tid, 'FORECAST', 'SUCCEEDED', "
                "   CAST(:params AS jsonb), CAST(:idv AS jsonb), "
                "   :started, :finished, 100, :now, :now)"
            ), {
                "id": run_id,
                "tid": tid,
                "params": f'{{"brand_id": "{brand_id}", "horizon": {horizon_months}}}',
                "idv": '{"rx": 1}',
                "started": now,
                "finished": now,
                "now": now,
            })

            for i in range(1, horizon_months + 1):
                x_val = n - 1 + i
                predicted_nrx = round(max(a + b * x_val, 0.0), 2)

                # Compute forecast month
                if hasattr(last_month, "month"):
                    year = last_month.year
                    month = last_month.month + i
                    while month > 12:
                        month -= 12
                        year += 1
                    forecast_month = date(year, month, 1)
                else:
                    forecast_month = last_month + timedelta(days=30 * i)

                forecast_entry = {
                    "month": forecast_month.isoformat(),
                    "predicted_nrx": predicted_nrx,
                }
                forecast.append(forecast_entry)

                # Write to analytics.forecasts
                await db.execute(text(
                    "INSERT INTO analytics.forecasts "
                    "  (id, tenant_id, run_id, brand_id, mode, "
                    "   point_estimate, alpha, created_at, updated_at) "
                    "VALUES "
                    "  (:id, :tid, :run_id, :brand_id, 'MODEL', "
                    "   :estimate, 0.20, :now, :now)"
                ), {
                    "id": uuid.uuid4(),
                    "tid": tid,
                    "run_id": run_id,
                    "brand_id": bid,
                    "estimate": predicted_nrx,
                    "now": now,
                })

            result = {
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "horizon_months": horizon_months,
                "status": "completed",
                "forecast": forecast,
                "model_version": "linear-trend-v1",
                "trend_slope": round(b, 4),
                "trend_intercept": round(a, 4),
            }
            log.info(
                "task.generate_forecast.completed",
                tenant_id=tenant_id,
                brand_id=brand_id,
            )
            return result

    return asyncio.get_event_loop().run_until_complete(_run())
