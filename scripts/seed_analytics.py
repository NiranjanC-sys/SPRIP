"""Seed analytics schema tables with synthetic data derived from core tables.

Populates analysis_runs, event_impacts, roi_results, and portfolio_aggregates
so the frontend dashboards have data to render.  Idempotent: deletes existing
analytics rows before inserting.

Usage:
    python scripts/seed_analytics.py
"""

import asyncio
import hashlib
import json
import random
import uuid
from datetime import date, datetime, timedelta, timezone

TENANT_CODE = "demo-pharma"
REVENUE_PER_NRX = 850.0

random.seed(42)


def _deterministic_float(seed_str: str, low: float, high: float) -> float:
    """Return a deterministic float in [low, high] based on a hash of seed_str."""
    h = hashlib.sha256(seed_str.encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF
    return low + frac * (high - low)


async def main() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )

    async with engine.begin() as conn:
        # ── 1. Tenant & admin ──────────────────────────────────────────
        row = await conn.execute(
            text("SELECT id FROM core.tenants WHERE code = :code"),
            {"code": TENANT_CODE},
        )
        tenant_id = row.scalar_one()
        print(f"Tenant: {tenant_id}")

        row = await conn.execute(
            text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'")
        )
        admin_id = row.scalar_one()

        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await conn.execute(text(f"SET app.identity_user_id = '{admin_id}'"))

        # ── 2. Read existing core data ─────────────────────────────────
        print("Reading core data...")

        rows = await conn.execute(text("SELECT id, name FROM core.brands"))
        brands = [dict(r._mapping) for r in rows]
        print(f"  {len(brands)} brands")

        rows = await conn.execute(
            text("SELECT id, brand_id, event_date FROM core.events")
        )
        events = [dict(r._mapping) for r in rows]
        print(f"  {len(events)} events")

        rows = await conn.execute(text(
            "SELECT event_id, COUNT(*) as att_count "
            "FROM core.attendance WHERE verified_attended = true "
            "GROUP BY event_id"
        ))
        attendance_by_event = {r.event_id: r.att_count for r in rows}

        rows = await conn.execute(text(
            "SELECT event_id, SUM(amount) as total_cost "
            "FROM core.event_costs GROUP BY event_id"
        ))
        cost_by_event = {r.event_id: float(r.total_cost) for r in rows}

        # ── 3. Clear analytics tables ──────────────────────────────────
        print("Clearing analytics tables...")
        for tbl in [
            "analytics.portfolio_aggregates",
            "analytics.roi_results",
            "analytics.event_impacts",
            "analytics.analysis_runs",
        ]:
            await conn.execute(text(f"DELETE FROM {tbl}"))

        # ── 4. Create analysis_runs (one per brand) ────────────────────
        print("Creating analysis_runs...")
        now = datetime.now(timezone.utc)
        finance_version_id = uuid.uuid4()  # shared fake finance version

        brand_run_map = {}  # brand_id -> run_id
        for brand in brands:
            run_id = uuid.uuid4()
            brand_run_map[brand["id"]] = run_id
            params = json.dumps({"brand_id": str(brand["id"]), "brand_name": brand["name"]})
            await conn.execute(text("""
                INSERT INTO analytics.analysis_runs
                    (id, tenant_id, run_kind, status, parameters, input_data_versions,
                     started_at, finished_at, duration_ms, progress_percent,
                     requested_by, code_version, random_seed, created_at, updated_at)
                VALUES
                    (:id, :tid, 'CAUSAL_ESTIMATE', 'SUCCEEDED',
                     CAST(:params AS jsonb), CAST(:idv AS jsonb),
                     :started, :finished, :dur, 100,
                     :admin, 'seed-v1', 42, :now, :now)
            """), {
                "id": run_id,
                "tid": tenant_id,
                "params": params,
                "idv": json.dumps({"rx": 1, "events": 1, "attendance": 1}),
                "started": now - timedelta(hours=1),
                "finished": now,
                "dur": 3600000,
                "admin": admin_id,
                "now": now,
            })
        print(f"  {len(brand_run_map)} analysis runs")

        # ── 5. Create event_impacts (one per event) ────────────────────
        print("Creating event_impacts...")
        event_impact_map = {}  # event_id -> impact dict
        batch = []

        for evt in events:
            event_id = evt["id"]
            brand_id = evt["brand_id"]
            event_dt = evt["event_date"]
            run_id = brand_run_map.get(brand_id)
            if run_id is None:
                continue

            n_treated = attendance_by_event.get(event_id, 0)
            if n_treated == 0:
                n_treated = max(5, int(_deterministic_float(str(event_id) + "nt", 5, 40)))
            n_control = n_treated * 2

            att = round(_deterministic_float(str(event_id), 2.0, 12.0), 4)
            incremental_nrx = round(att * n_treated, 2)
            se = round(att * 0.3, 4)
            t_stat = att / se if se > 0 else 10.0
            p_value = round(max(0.001, min(0.2, 0.5 / t_stat)), 6)
            ci_low = round(att - 1.96 * se, 4)
            ci_high = round(att + 1.96 * se, 4)

            if p_value < 0.05 and n_treated > 20:
                evidence_grade = "STRONG"
            elif p_value < 0.10:
                evidence_grade = "MODERATE"
            else:
                evidence_grade = "DIRECTIONAL"

            impact_id = uuid.uuid4()
            impact = {
                "id": impact_id,
                "run_id": run_id,
                "event_id": event_id,
                "brand_id": brand_id,
                "event_date": event_dt,
                "att": att,
                "incremental_nrx": incremental_nrx,
                "se": se,
                "p_value": p_value,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n_treated": n_treated,
                "n_control": n_control,
                "evidence_grade": evidence_grade,
            }
            event_impact_map[event_id] = impact

            batch.append({
                "id": impact_id,
                "tid": tenant_id,
                "run_id": run_id,
                "event_id": event_id,
                "brand_id": brand_id,
                "event_date": event_dt,
                "att": att,
                "se": se,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "p_value": p_value,
                "incremental_nrx": incremental_nrx,
                "n_treated": n_treated,
                "n_control": n_control,
                "evidence_grade": evidence_grade,
                "now": now,
            })

            if len(batch) >= 200:
                await conn.execute(text("""
                    INSERT INTO analytics.event_impacts
                        (id, tenant_id, run_id, event_id, outcome_metric, grain,
                         estimator_kind, att, standard_error, ci_low, ci_high, p_value,
                         confidence_level, incremental_nrx, n_treated, n_control,
                         pre_periods, post_periods,
                         evidence_status, evidence_grade, publication_state,
                         brand_id, event_date, row_version, created_at, updated_at)
                    VALUES
                        (:id, :tid, :run_id, :event_id, 'NRX', 'HCP',
                         'COHORT_TIME_ATT', :att, :se, :ci_low, :ci_high, :p_value,
                         0.95, :incremental_nrx, :n_treated, :n_control,
                         6, 3,
                         'ESTIMATED', :evidence_grade, 'PUBLISHED',
                         :brand_id, :event_date, 1, :now, :now)
                """), batch)
                batch = []

        if batch:
            await conn.execute(text("""
                INSERT INTO analytics.event_impacts
                    (id, tenant_id, run_id, event_id, outcome_metric, grain,
                     estimator_kind, att, standard_error, ci_low, ci_high, p_value,
                     confidence_level, incremental_nrx, n_treated, n_control,
                     pre_periods, post_periods,
                     evidence_status, evidence_grade, publication_state,
                     brand_id, event_date, row_version, created_at, updated_at)
                VALUES
                    (:id, :tid, :run_id, :event_id, 'NRX', 'HCP',
                     'COHORT_TIME_ATT', :att, :se, :ci_low, :ci_high, :p_value,
                     0.95, :incremental_nrx, :n_treated, :n_control,
                     6, 3,
                     'ESTIMATED', :evidence_grade, 'PUBLISHED',
                     :brand_id, :event_date, 1, :now, :now)
            """), batch)
        print(f"  {len(event_impact_map)} event impacts")

        # ── 6. Create roi_results ──────────────────────────────────────
        print("Creating roi_results...")

        # EVENT grain
        roi_batch = []
        brand_agg = {}  # brand_id -> {inc_nrx, revenue, cost, count, impact_ids, evidence_grades}

        for evt in events:
            event_id = evt["id"]
            brand_id = evt["brand_id"]
            run_id = brand_run_map.get(brand_id)
            if run_id is None or event_id not in event_impact_map:
                continue

            impact = event_impact_map[event_id]
            inc_nrx = impact["incremental_nrx"]
            inc_revenue = round(inc_nrx * REVENUE_PER_NRX, 2)
            total_cost = cost_by_event.get(event_id, 0.0)
            bcr = round(inc_revenue / total_cost, 4) if total_cost > 0 else None
            net_roi = round(inc_revenue - total_cost, 2)

            # Accumulate for brand aggregate
            if brand_id not in brand_agg:
                brand_agg[brand_id] = {
                    "inc_nrx": 0.0, "revenue": 0.0, "cost": 0.0,
                    "count": 0, "grades": [],
                }
            brand_agg[brand_id]["inc_nrx"] += inc_nrx
            brand_agg[brand_id]["revenue"] += inc_revenue
            brand_agg[brand_id]["cost"] += total_cost
            brand_agg[brand_id]["count"] += 1
            brand_agg[brand_id]["grades"].append(impact["evidence_grade"])

            roi_batch.append({
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "run_id": run_id,
                "level": "EVENT",
                "event_id": event_id,
                "brand_id": brand_id,
                "event_impact_id": impact["id"],
                "finance_vid": finance_version_id,
                "contrib": REVENUE_PER_NRX,
                "inc_nrx": inc_nrx,
                "gross": inc_revenue,
                "total_cost": total_cost,
                "net_roi": net_roi,
                "bcr": bcr,
                "evidence_grade": impact["evidence_grade"],
                "currency": "INR",
                "now": now,
            })

            if len(roi_batch) >= 200:
                await conn.execute(text("""
                    INSERT INTO analytics.roi_results
                        (id, tenant_id, run_id, level, event_id, brand_id,
                         event_impact_id, finance_version_id, scenario,
                         contribution_per_nrx, incremental_nrx,
                         gross_contribution, total_cost, net_roi, benefit_cost_ratio,
                         evidence_status, evidence_grade, publication_state,
                         currency, row_version, created_at, updated_at)
                    VALUES
                        (:id, :tid, :run_id, :level, :event_id, :brand_id,
                         :event_impact_id, :finance_vid, 'BASE',
                         :contrib, :inc_nrx,
                         :gross, :total_cost, :net_roi, :bcr,
                         'ESTIMATED', :evidence_grade, 'PUBLISHED',
                         :currency, 1, :now, :now)
                """), roi_batch)
                roi_batch = []

        if roi_batch:
            await conn.execute(text("""
                INSERT INTO analytics.roi_results
                    (id, tenant_id, run_id, level, event_id, brand_id,
                     event_impact_id, finance_version_id, scenario,
                     contribution_per_nrx, incremental_nrx,
                     gross_contribution, total_cost, net_roi, benefit_cost_ratio,
                     evidence_status, evidence_grade, publication_state,
                     currency, row_version, created_at, updated_at)
                VALUES
                    (:id, :tid, :run_id, :level, :event_id, :brand_id,
                     :event_impact_id, :finance_vid, 'BASE',
                     :contrib, :inc_nrx,
                     :gross, :total_cost, :net_roi, :bcr,
                     'ESTIMATED', :evidence_grade, 'PUBLISHED',
                     :currency, 1, :now, :now)
            """), roi_batch)

        event_roi_count = len(event_impact_map)
        print(f"  {event_roi_count} EVENT-grain roi_results")

        # BRAND grain
        brand_roi_count = 0
        for brand_id, agg in brand_agg.items():
            run_id = brand_run_map.get(brand_id)
            if run_id is None:
                continue
            bcr = round(agg["revenue"] / agg["cost"], 4) if agg["cost"] > 0 else None
            # Dominant grade
            from collections import Counter
            grade_counts = Counter(agg["grades"])
            dominant = grade_counts.most_common(1)[0][0] if grade_counts else "DIRECTIONAL"

            await conn.execute(text("""
                INSERT INTO analytics.roi_results
                    (id, tenant_id, run_id, level, brand_id,
                     finance_version_id, scenario,
                     contribution_per_nrx, incremental_nrx,
                     gross_contribution, total_cost, net_roi, benefit_cost_ratio,
                     evidence_status, evidence_grade, publication_state,
                     events_measured, evidence_mix,
                     currency, row_version, created_at, updated_at)
                VALUES
                    (:id, :tid, :run_id, 'BRAND', :brand_id,
                     :finance_vid, 'BASE',
                     :contrib, :inc_nrx,
                     :gross, :total_cost, :net_roi, :bcr,
                     'ESTIMATED', :evidence_grade, 'PUBLISHED',
                     :events_measured, CAST(:emix AS jsonb),
                     'INR', 1, :now, :now)
            """), {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "run_id": run_id,
                "brand_id": brand_id,
                "finance_vid": finance_version_id,
                "contrib": REVENUE_PER_NRX,
                "inc_nrx": round(agg["inc_nrx"], 2),
                "gross": round(agg["revenue"], 2),
                "total_cost": round(agg["cost"], 2),
                "net_roi": round(agg["revenue"] - agg["cost"], 2),
                "bcr": bcr,
                "evidence_grade": dominant,
                "events_measured": agg["count"],
                "emix": json.dumps(dict(grade_counts)),
                "now": now,
            })
            brand_roi_count += 1
        print(f"  {brand_roi_count} BRAND-grain roi_results")

        # ── 7. Create portfolio_aggregates (monthly per brand) ─────────
        print("Creating portfolio_aggregates...")

        # Build monthly buckets per brand from events
        monthly_brand = {}  # (brand_id, year, month) -> {events, inc_nrx, cost, grades, attendees}
        for evt in events:
            event_id = evt["id"]
            brand_id = evt["brand_id"]
            event_dt = evt["event_date"]
            if event_id not in event_impact_map:
                continue
            impact = event_impact_map[event_id]
            key = (brand_id, event_dt.year, event_dt.month)
            if key not in monthly_brand:
                monthly_brand[key] = {
                    "events": 0, "inc_nrx": 0.0, "cost": 0.0,
                    "grades": [], "attendees": 0,
                }
            bucket = monthly_brand[key]
            bucket["events"] += 1
            bucket["inc_nrx"] += impact["incremental_nrx"]
            bucket["cost"] += cost_by_event.get(event_id, 0.0)
            bucket["grades"].append(impact["evidence_grade"])
            bucket["attendees"] += impact["n_treated"]

        # Generate rows for Jan 2025 - Jun 2026 for each brand
        pa_batch = []
        for brand in brands:
            brand_id = brand["id"]
            run_id = brand_run_map.get(brand_id)
            if run_id is None:
                continue

            cur = date(2025, 1, 1)
            end = date(2026, 6, 30)
            while cur <= end:
                y, m = cur.year, cur.month
                # Next month for period_end
                if m == 12:
                    p_end = date(y + 1, 1, 1) - timedelta(days=1)
                    next_month = date(y + 1, 1, 1)
                else:
                    next_month = date(y, m + 1, 1)
                    p_end = next_month - timedelta(days=1)

                key = (brand_id, y, m)
                bucket = monthly_brand.get(key)

                if bucket:
                    events_total = bucket["events"]
                    inc_nrx = round(bucket["inc_nrx"], 2)
                    total_cost = round(bucket["cost"], 2)
                    revenue = round(inc_nrx * REVENUE_PER_NRX, 2)
                    bcr = round(revenue / total_cost, 4) if total_cost > 0 else None
                    net_roi_val = round(revenue - total_cost, 2)
                    attendees = bucket["attendees"]
                    from collections import Counter
                    gc = Counter(bucket["grades"])
                    dominant = gc.most_common(1)[0][0] if gc else None
                    emix = json.dumps(dict(gc))
                else:
                    events_total = 0
                    inc_nrx = 0.0
                    total_cost = 0.0
                    bcr = None
                    net_roi_val = 0.0
                    attendees = 0
                    dominant = None
                    emix = json.dumps({})

                pa_batch.append({
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "run_id": run_id,
                    "level": "BRAND",
                    "level_key": brand["name"],
                    "brand_id": brand_id,
                    "p_start": cur,
                    "p_end": p_end,
                    "events_total": events_total,
                    "events_measured": events_total,
                    "events_ne": 0,
                    "attendees": attendees,
                    "inc_nrx": inc_nrx if inc_nrx else None,
                    "total_cost": total_cost if total_cost else None,
                    "net_roi": net_roi_val if events_total > 0 else None,
                    "bcr": bcr,
                    "currency": "INR",
                    "emix": emix,
                    "dominant": dominant,
                    "pub": "PUBLISHED" if events_total > 0 else "DRAFT",
                    "now": now,
                })

                cur = next_month

                if len(pa_batch) >= 200:
                    await conn.execute(text("""
                        INSERT INTO analytics.portfolio_aggregates
                            (id, tenant_id, run_id, level, level_key, brand_id,
                             period_start, period_end,
                             events_total, events_measured, events_not_estimable,
                             attendees_verified,
                             incremental_nrx, total_cost, net_roi, benefit_cost_ratio,
                             currency, evidence_mix, dominant_grade, publication_state,
                             created_at, updated_at)
                        VALUES
                            (:id, :tid, :run_id, :level, :level_key, :brand_id,
                             :p_start, :p_end,
                             :events_total, :events_measured, :events_ne,
                             :attendees,
                             :inc_nrx, :total_cost, :net_roi, :bcr,
                             :currency, CAST(:emix AS jsonb), :dominant, :pub,
                             :now, :now)
                    """), pa_batch)
                    pa_batch = []

        if pa_batch:
            await conn.execute(text("""
                INSERT INTO analytics.portfolio_aggregates
                    (id, tenant_id, run_id, level, level_key, brand_id,
                     period_start, period_end,
                     events_total, events_measured, events_not_estimable,
                     attendees_verified,
                     incremental_nrx, total_cost, net_roi, benefit_cost_ratio,
                     currency, evidence_mix, dominant_grade, publication_state,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :run_id, :level, :level_key, :brand_id,
                     :p_start, :p_end,
                     :events_total, :events_measured, :events_ne,
                     :attendees,
                     :inc_nrx, :total_cost, :net_roi, :bcr,
                     :currency, CAST(:emix AS jsonb), :dominant, :pub,
                     :now, :now)
            """), pa_batch)

        total_pa = len(brands) * 18  # 18 months
        print(f"  ~{total_pa} portfolio_aggregate rows")

        # -- 8. Create forecasts (future events) ──────────────────────────
        print("Creating forecasts...")
        await conn.execute(text("DELETE FROM analytics.forecasts"))

        # Get future events (event_date > today) for forecasting
        future_events = [
            evt for evt in events if evt["event_date"] > date.today()
        ]
        # If not enough future events, use recent ones
        if len(future_events) < 50:
            sorted_events = sorted(events, key=lambda e: e["event_date"], reverse=True)
            future_events = sorted_events[:50]

        forecast_count = 0
        for evt in future_events[:50]:
            event_id = evt["id"]
            brand_id = evt["brand_id"]
            run_id = brand_run_map.get(brand_id)
            if run_id is None:
                continue

            # Generate realistic forecast values
            seed_str = str(event_id) + "forecast"
            point_est = round(_deterministic_float(seed_str, 3.0, 15.0), 4)
            pi_low = round(point_est * 0.5, 4)
            pi_high = round(point_est * 1.8, 4)
            n_eff = round(_deterministic_float(seed_str + "neff", 5.0, 50.0), 1)
            exp_att = round(_deterministic_float(seed_str + "att", 15.0, 80.0), 1)
            exp_att_low = round(exp_att * 0.6, 1)
            exp_att_high = round(exp_att * 1.4, 1)
            exp_inc_nrx = round(point_est * exp_att, 2)
            exp_cost = round(_deterministic_float(seed_str + "cost", 50000, 300000), 2)
            exp_net_roi = round(exp_inc_nrx * REVENUE_PER_NRX - exp_cost, 2)
            exp_net_roi_low = round(pi_low * exp_att_low * REVENUE_PER_NRX - exp_cost, 2)

            # Most forecasts are MODEL, some POOLED
            mode = "MODEL" if _deterministic_float(seed_str + "mode", 0, 1) > 0.25 else "POOLED"
            pooling_cell = f"brand={brand_id}" if mode == "POOLED" else None
            pooling_level = "BRAND" if mode == "POOLED" else None
            blend_weight = round(_deterministic_float(seed_str + "bw", 0.3, 0.9), 2) if mode == "POOLED" else None

            await conn.execute(text("""
                INSERT INTO analytics.forecasts
                    (id, tenant_id, run_id, brand_id, mode,
                     point_estimate, pi_low, pi_high, alpha,
                     n_effective, pooling_cell, pooling_level, blend_weight,
                     expected_attendance, expected_attendance_low, expected_attendance_high,
                     expected_incremental_nrx, expected_cost,
                     expected_net_roi, expected_net_roi_low, currency,
                     created_at, updated_at)
                VALUES
                    (:id, :tid, :run_id, :brand_id, :mode,
                     :point_est, :pi_low, :pi_high, 0.20,
                     :n_eff, :pooling_cell, :pooling_level, :blend_weight,
                     :exp_att, :exp_att_low, :exp_att_high,
                     :exp_inc_nrx, :exp_cost,
                     :exp_net_roi, :exp_net_roi_low, 'INR',
                     :now, :now)
            """), {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "run_id": run_id,
                "brand_id": brand_id,
                "mode": mode,
                "point_est": point_est,
                "pi_low": pi_low,
                "pi_high": pi_high,
                "n_eff": n_eff,
                "pooling_cell": pooling_cell,
                "pooling_level": pooling_level,
                "blend_weight": blend_weight,
                "exp_att": exp_att,
                "exp_att_low": exp_att_low,
                "exp_att_high": exp_att_high,
                "exp_inc_nrx": exp_inc_nrx,
                "exp_cost": exp_cost,
                "exp_net_roi": exp_net_roi,
                "exp_net_roi_low": exp_net_roi_low,
                "now": now,
            })
            forecast_count += 1
        print(f"  {forecast_count} forecasts")

    await engine.dispose()
    print("\n=== Analytics seed complete ===")


if __name__ == "__main__":
    asyncio.run(main())
