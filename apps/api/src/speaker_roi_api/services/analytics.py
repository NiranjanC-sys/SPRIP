"""Analytics service: ROI computation, brand summaries, and portfolio overviews.

Uses raw SQL via text() for aggregate queries, consistent with the dashboard
router pattern. All queries run against the analytics and core schemas.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def compute_event_roi(db: AsyncSession, event_id: UUID) -> dict:
    """Compute ROI for a single event using event_costs and attendance data.

    Returns a dict with event_id, total_cost, attendees, incremental_nrx, roi,
    and benefit_cost_ratio.
    """
    # Total cost for the event
    cost_row = (await db.execute(text(
        "SELECT COALESCE(SUM(amount), 0) AS total_cost "
        "FROM core.event_costs WHERE event_id = :event_id"
    ), {"event_id": event_id})).mappings().first()
    total_cost = float(cost_row["total_cost"]) if cost_row else 0.0

    # Verified attendee count
    att_row = (await db.execute(text(
        "SELECT COUNT(*) AS cnt "
        "FROM core.attendance "
        "WHERE event_id = :event_id AND verified_attended = true"
    ), {"event_id": event_id})).mappings().first()
    attendees = int(att_row["cnt"]) if att_row else 0

    # Get the event's brand_id and date for Rx lookups
    event_row = (await db.execute(text(
        "SELECT brand_id, event_date FROM core.events WHERE id = :event_id"
    ), {"event_id": event_id})).mappings().first()

    incremental_nrx = 0.0
    if event_row and attendees > 0:
        brand_id = event_row["brand_id"]
        event_date = event_row["event_date"]

        # Average post-event NRx for attendees (3 months after event)
        post_att = (await db.execute(text(
            "SELECT AVG(rx.nrx) AS avg_nrx "
            "FROM core.hcp_rx_monthly rx "
            "JOIN core.attendance a ON a.hcp_id = rx.hcp_id "
            "WHERE a.event_id = :event_id "
            "  AND a.verified_attended = true "
            "  AND rx.brand_id = :brand_id "
            "  AND rx.month > :event_date "
            "  AND rx.month <= :event_date + interval '3 months' "
            "  AND rx.nrx IS NOT NULL"
        ), {
            "event_id": event_id,
            "brand_id": brand_id,
            "event_date": event_date,
        })).scalar()

        # Average pre-event NRx for attendees (3 months before event)
        pre_att = (await db.execute(text(
            "SELECT AVG(rx.nrx) AS avg_nrx "
            "FROM core.hcp_rx_monthly rx "
            "JOIN core.attendance a ON a.hcp_id = rx.hcp_id "
            "WHERE a.event_id = :event_id "
            "  AND a.verified_attended = true "
            "  AND rx.brand_id = :brand_id "
            "  AND rx.month >= :event_date - interval '3 months' "
            "  AND rx.month < :event_date "
            "  AND rx.nrx IS NOT NULL"
        ), {
            "event_id": event_id,
            "brand_id": brand_id,
            "event_date": event_date,
        })).scalar()

        avg_post = float(post_att) if post_att is not None else 0.0
        avg_pre = float(pre_att) if pre_att is not None else 0.0
        att_lift = avg_post - avg_pre

        # Incremental NRx = per-attendee lift * attendee count
        incremental_nrx = round(max(att_lift, 0.0) * attendees, 2)

    # Benefit-cost ratio
    benefit_cost_ratio = None
    roi = None
    if total_cost > 0 and incremental_nrx > 0:
        # Use a revenue proxy (NRx * rough contribution) for ROI
        # For simplicity, benefit_cost_ratio = incremental_nrx / total_cost
        # (the actual monetisation uses finance_assumptions)
        benefit_cost_ratio = round(incremental_nrx / total_cost, 4)
        roi = round(incremental_nrx - total_cost, 2)

    return {
        "event_id": str(event_id),
        "total_cost": round(total_cost, 2),
        "attendees": attendees,
        "incremental_nrx": incremental_nrx,
        "roi": roi,
        "benefit_cost_ratio": benefit_cost_ratio,
    }


async def get_brand_summary(db: AsyncSession, brand_id: UUID) -> dict:
    """Aggregate ROI metrics for a brand from analytics.roi_results."""
    row = (await db.execute(text(
        "SELECT "
        "  COUNT(*) AS event_count, "
        "  COALESCE(SUM(incremental_nrx), 0) AS total_incremental_nrx, "
        "  COALESCE(SUM(total_cost), 0) AS total_cost, "
        "  COALESCE(SUM(gross_contribution), 0) AS total_revenue, "
        "  COALESCE(SUM(net_roi), 0) AS total_net_roi, "
        "  AVG(benefit_cost_ratio) AS avg_benefit_cost_ratio "
        "FROM analytics.roi_results "
        "WHERE brand_id = :brand_id AND level = 'EVENT'"
    ), {"brand_id": brand_id})).mappings().first()

    # Brand-level summary row
    brand_row = (await db.execute(text(
        "SELECT benefit_cost_ratio, incremental_nrx, total_cost, net_roi, "
        "       events_measured, evidence_grade "
        "FROM analytics.roi_results "
        "WHERE brand_id = :brand_id AND level = 'BRAND' "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"brand_id": brand_id})).mappings().first()

    result = {
        "brand_id": str(brand_id),
        "event_count": int(row["event_count"]) if row else 0,
        "total_incremental_nrx": round(float(row["total_incremental_nrx"]), 2) if row else 0.0,
        "total_cost": round(float(row["total_cost"]), 2) if row else 0.0,
        "total_revenue": round(float(row["total_revenue"]), 2) if row else 0.0,
        "total_net_roi": round(float(row["total_net_roi"]), 2) if row else 0.0,
        "avg_benefit_cost_ratio": (
            round(float(row["avg_benefit_cost_ratio"]), 4)
            if row and row["avg_benefit_cost_ratio"] is not None
            else None
        ),
    }

    if brand_row:
        result["brand_level"] = {
            "benefit_cost_ratio": (
                round(float(brand_row["benefit_cost_ratio"]), 4)
                if brand_row["benefit_cost_ratio"] is not None
                else None
            ),
            "incremental_nrx": (
                round(float(brand_row["incremental_nrx"]), 2)
                if brand_row["incremental_nrx"] is not None
                else None
            ),
            "total_cost": round(float(brand_row["total_cost"]), 2),
            "net_roi": (
                round(float(brand_row["net_roi"]), 2)
                if brand_row["net_roi"] is not None
                else None
            ),
            "events_measured": (
                int(brand_row["events_measured"])
                if brand_row["events_measured"] is not None
                else None
            ),
            "evidence_grade": str(brand_row["evidence_grade"]),
        }

    return result


async def get_portfolio_overview(db: AsyncSession) -> dict:
    """Roll-up across all brands from analytics.portfolio_aggregates."""
    rows = (await db.execute(text(
        "SELECT "
        "  brand_id, "
        "  level_key AS brand_name, "
        "  SUM(events_total) AS events_total, "
        "  SUM(events_measured) AS events_measured, "
        "  SUM(attendees_verified) AS attendees_verified, "
        "  COALESCE(SUM(incremental_nrx), 0) AS incremental_nrx, "
        "  COALESCE(SUM(total_cost), 0) AS total_cost, "
        "  COALESCE(SUM(net_roi), 0) AS net_roi, "
        "  AVG(benefit_cost_ratio) AS avg_bcr "
        "FROM analytics.portfolio_aggregates "
        "WHERE level = 'BRAND' "
        "GROUP BY brand_id, level_key "
        "ORDER BY level_key"
    ))).mappings().all()

    brands = []
    totals = {
        "events_total": 0,
        "events_measured": 0,
        "attendees_verified": 0,
        "incremental_nrx": 0.0,
        "total_cost": 0.0,
        "net_roi": 0.0,
    }

    for r in rows:
        brand = {
            "brand_id": str(r["brand_id"]),
            "brand_name": r["brand_name"],
            "events_total": int(r["events_total"]),
            "events_measured": int(r["events_measured"]),
            "attendees_verified": int(r["attendees_verified"]),
            "incremental_nrx": round(float(r["incremental_nrx"]), 2),
            "total_cost": round(float(r["total_cost"]), 2),
            "net_roi": round(float(r["net_roi"]), 2),
            "avg_benefit_cost_ratio": (
                round(float(r["avg_bcr"]), 4)
                if r["avg_bcr"] is not None
                else None
            ),
        }
        brands.append(brand)
        totals["events_total"] += brand["events_total"]
        totals["events_measured"] += brand["events_measured"]
        totals["attendees_verified"] += brand["attendees_verified"]
        totals["incremental_nrx"] += brand["incremental_nrx"]
        totals["total_cost"] += brand["total_cost"]
        totals["net_roi"] += brand["net_roi"]

    totals["incremental_nrx"] = round(totals["incremental_nrx"], 2)
    totals["total_cost"] = round(totals["total_cost"], 2)
    totals["net_roi"] = round(totals["net_roi"], 2)
    totals["avg_benefit_cost_ratio"] = (
        round(totals["incremental_nrx"] / totals["total_cost"], 4)
        if totals["total_cost"] > 0
        else None
    )

    return {
        "brands": brands,
        "totals": totals,
    }
