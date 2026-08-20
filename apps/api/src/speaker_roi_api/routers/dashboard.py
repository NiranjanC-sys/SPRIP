"""Dashboard aggregate endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from speaker_roi_api.deps import ReadOnlySession, require
from speaker_roi_api.schemas.dashboard import (
    DashboardStats,
    EngagementBucket,
    EngagementResponse,
    MonthlyBrandSpend,
    RegionEngagement,
    RoiTrendResponse,
    SpecialtyEngagement,
)
from speaker_roi_api.security.rbac import Permission

router = APIRouter(tags=["Dashboard"])


@router.get(
    "/dashboard/stats",
    response_model=DashboardStats,
    summary="Dashboard overview stats",
    dependencies=[Depends(require(Permission.CAMPAIGN_READ))],
)
async def dashboard_stats(db: ReadOnlySession) -> DashboardStats:
    brand_count = (await db.execute(text("SELECT COUNT(*) FROM core.brands"))).scalar() or 0
    hcp_count = (await db.execute(text("SELECT COUNT(*) FROM core.hcps"))).scalar() or 0
    campaign_count = (await db.execute(text("SELECT COUNT(*) FROM core.campaigns"))).scalar() or 0
    event_count = (await db.execute(text("SELECT COUNT(*) FROM core.events"))).scalar() or 0
    total_spend = (await db.execute(text("SELECT COALESCE(SUM(amount), 0) FROM core.event_costs"))).scalar() or 0
    total_attendees = (await db.execute(text(
        "SELECT COUNT(DISTINCT hcp_id) FROM core.attendance WHERE verified_attended = true"
    ))).scalar() or 0

    engagement_rate = round(float(total_attendees) / float(hcp_count), 4) if hcp_count > 0 else 0.0

    # Try analytics.roi_results first
    avg_roi = None
    try:
        avg_roi_raw = (await db.execute(text(
            "SELECT AVG(benefit_cost_ratio) FROM analytics.roi_results WHERE level = 'BRAND'"
        ))).scalar()
        if avg_roi_raw is not None:
            avg_roi = round(float(avg_roi_raw), 2)
    except Exception:
        pass

    if avg_roi is None and float(total_spend) > 0:
        # Fallback: compute from Rx revenue proxy / spend
        try:
            total_trx = (await db.execute(text(
                "SELECT COALESCE(SUM(trx), 0) FROM core.hcp_rx_monthly"
            ))).scalar() or 0
            if total_trx > 0:
                avg_roi = round(float(total_trx) / float(total_spend), 2)
        except Exception:
            pass

    return DashboardStats(
        total_brands=int(brand_count),
        total_hcps=int(hcp_count),
        total_campaigns=int(campaign_count),
        total_events=int(event_count),
        total_spend=round(float(total_spend), 2),
        total_attendees=int(total_attendees),
        engagement_rate=engagement_rate,
        avg_roi=avg_roi,
    )


@router.get(
    "/dashboard/roi-trend",
    response_model=RoiTrendResponse,
    summary="Monthly ROI trend",
    dependencies=[Depends(require(Permission.CAMPAIGN_READ))],
)
async def roi_trend(db: ReadOnlySession) -> RoiTrendResponse:
    # Monthly spend per brand
    spend_rows = (await db.execute(text("""
        SELECT to_char(date_trunc('month', e.event_date), 'YYYY-MM') AS month,
               b.name AS brand,
               COALESCE(SUM(ec.amount), 0) AS spend
        FROM core.events e
        JOIN core.brands b ON b.id = e.brand_id
        LEFT JOIN core.event_costs ec ON ec.event_id = e.id
        GROUP BY date_trunc('month', e.event_date), b.name
        ORDER BY month, brand
    """))).mappings().all()

    # Monthly Rx per brand
    rx_rows = (await db.execute(text("""
        SELECT to_char(rx.month, 'YYYY-MM') AS month,
               b.name AS brand,
               COALESCE(SUM(rx.trx), 0) AS trx
        FROM core.hcp_rx_monthly rx
        JOIN core.brands b ON b.id = rx.brand_id
        GROUP BY rx.month, b.name
        ORDER BY month, brand
    """))).mappings().all()

    # Merge spend and rx by (month, brand)
    rx_lookup: dict[tuple[str, str], int] = {}
    for r in rx_rows:
        rx_lookup[(r["month"], r["brand"])] = int(r["trx"])

    trend = []
    for r in spend_rows:
        m = r["month"]
        br = r["brand"]
        trend.append(MonthlyBrandSpend(
            month=m,
            brand=br,
            spend=round(float(r["spend"]), 2),
            trx=rx_lookup.get((m, br), 0),
        ))

    # Add rx-only months that had no spend
    spend_keys = {(r["month"], r["brand"]) for r in spend_rows}
    for (m, br), trx in rx_lookup.items():
        if (m, br) not in spend_keys:
            trend.append(MonthlyBrandSpend(month=m, brand=br, spend=0.0, trx=trx))

    trend.sort(key=lambda x: (x.month, x.brand))
    return RoiTrendResponse(trend=trend)


@router.get(
    "/dashboard/engagement",
    response_model=EngagementResponse,
    summary="HCP engagement metrics",
    dependencies=[Depends(require(Permission.CAMPAIGN_READ))],
)
async def engagement_metrics(db: ReadOnlySession) -> EngagementResponse:
    # Count events attended per HCP, then bucket
    bucket_rows = (await db.execute(text("""
        SELECT
            CASE
                WHEN cnt >= 3 THEN 'High'
                WHEN cnt >= 1 THEN 'Medium'
                ELSE 'Low'
            END AS bucket,
            COUNT(*) AS count
        FROM (
            SELECT h.id, COALESCE(att.cnt, 0) AS cnt
            FROM core.hcps h
            LEFT JOIN (
                SELECT hcp_id, COUNT(*) AS cnt
                FROM core.attendance
                WHERE verified_attended = true
                GROUP BY hcp_id
            ) att ON att.hcp_id = h.id
        ) sub
        GROUP BY bucket
        ORDER BY bucket
    """))).mappings().all()

    buckets = [EngagementBucket(bucket=r["bucket"], count=int(r["count"])) for r in bucket_rows]

    # By specialty
    spec_rows = (await db.execute(text("""
        SELECT h.specialty_code AS specialty,
               AVG(COALESCE(att.cnt, 0)) AS avg_events
        FROM core.hcps h
        LEFT JOIN (
            SELECT hcp_id, COUNT(*) AS cnt
            FROM core.attendance
            WHERE verified_attended = true
            GROUP BY hcp_id
        ) att ON att.hcp_id = h.id
        WHERE h.specialty_code IS NOT NULL AND h.specialty_code != ''
        GROUP BY h.specialty_code
        ORDER BY avg_events DESC
    """))).mappings().all()

    by_specialty = [
        SpecialtyEngagement(specialty=r["specialty"], avg_events=round(float(r["avg_events"]), 2))
        for r in spec_rows
    ]

    # By region
    region_rows = (await db.execute(text("""
        SELECT h.region_code AS region,
               AVG(COALESCE(att.cnt, 0)) AS avg_events
        FROM core.hcps h
        LEFT JOIN (
            SELECT hcp_id, COUNT(*) AS cnt
            FROM core.attendance
            WHERE verified_attended = true
            GROUP BY hcp_id
        ) att ON att.hcp_id = h.id
        WHERE h.region_code IS NOT NULL AND h.region_code != ''
        GROUP BY h.region_code
        ORDER BY avg_events DESC
    """))).mappings().all()

    by_region = [
        RegionEngagement(region=r["region"], avg_events=round(float(r["avg_events"]), 2))
        for r in region_rows
    ]

    return EngagementResponse(
        buckets=buckets,
        by_specialty=by_specialty,
        by_region=by_region,
    )


__all__ = ["router"]
