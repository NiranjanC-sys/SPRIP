"""Seed the database with synthetic data from DATA_EXTRACT/syn dt/data/bronze/."""

import asyncio
import csv
import random
import uuid
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "DATA_EXTRACT" / "syn dt" / "data" / "bronze"
TENANT_CODE = "demo-pharma"


async def main():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        "postgresql+asyncpg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi",
        poolclass=NullPool,
    )

    async with engine.begin() as conn:
        row = await conn.execute(text("SELECT id FROM core.tenants WHERE code = :code"), {"code": TENANT_CODE})
        tenant_id = row.scalar_one()
        print(f"Tenant: {tenant_id}")

        row = await conn.execute(text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'"))
        admin_id = row.scalar_one()

        await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
        await conn.execute(text(f"SET app.identity_user_id = '{admin_id}'"))

        # --- Clear ---
        print("Clearing old data...")
        for tbl in [
            # Analytics tables reference core tables (brands, events) via FK
            "analytics.forecasts",
            "analytics.portfolio_aggregates",
            "analytics.roi_results",
            "analytics.event_impacts",
            "analytics.analysis_runs",
            # Core tables
            "core.attendance", "core.event_costs", "core.event_speakers",
            "core.hcp_rx_monthly", "core.marketing_activity", "core.market_factors",
            "core.events", "core.campaigns", "core.hcp_identifiers", "core.hcps",
            "core.products", "core.brands",
        ]:
            await conn.execute(text(f"DELETE FROM {tbl}"))

        # --- Brands & Products ---
        print("Loading brands & products...")
        products_set = set()
        with open(DATA_DIR / "hcp_rx_monthly.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                products_set.add(r["product"])

        brand_map = {}   # product_name -> brand_id
        product_map = {} # product_name -> product_id
        for prod in sorted(products_set):
            bid = uuid.uuid4()
            pid = uuid.uuid4()
            code = prod.lower().replace(" ", "-").replace("_", "-")[:58]
            brand_map[prod] = bid
            product_map[prod] = pid
            await conn.execute(text("""
                INSERT INTO core.brands (id, tenant_id, code, name, is_active, row_version, created_at, updated_at)
                VALUES (:id, :tid, :code, :name, true, 1, now(), now())
            """), {"id": bid, "tid": tenant_id, "code": code, "name": prod})
            await conn.execute(text("""
                INSERT INTO core.products (id, tenant_id, brand_id, code, name, is_active, row_version, created_at, updated_at)
                VALUES (:id, :tid, :bid, :code, :name, true, 1, now(), now())
            """), {"id": pid, "tid": tenant_id, "bid": bid, "code": code, "name": prod})
        print(f"  {len(brand_map)} brands: {', '.join(sorted(brand_map))}")

        # Round-robin brand assignment list for events
        brand_id_list = [brand_map[b] for b in sorted(brand_map.keys())]

        # Venue data for realistic event locations
        CITIES = [
            "Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad",
            "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Lucknow",
        ]
        VENUES = [
            "Grand Hotel Conference Center",
            "Medical Association Hall",
            "Pharma Convention Center",
            "University Auditorium",
            "Hospital Conference Room",
            "City Medical Forum",
            "Healthcare Summit Venue",
            "Research Institute Hall",
            "Professional Development Center",
            "Clinical Excellence Auditorium",
        ]
        random.seed(42)

        # --- HCPs ---
        print("Loading HCPs...")
        hcp_map = {}
        with open(DATA_DIR / "hcp_master.csv", encoding="utf-8") as f:
            batch = []
            for r in csv.DictReader(f):
                hid = uuid.uuid4()
                hcp_map[r["hcp_id"]] = hid
                batch.append({
                    "id": hid, "tid": tenant_id,
                    "master": r["hcp_id"],
                    "spec": (r.get("specialty") or "")[:58],
                    "region": (r.get("region") or "")[:58],
                    "segment": (r.get("segment") or "")[:58],
                })
                if len(batch) >= 500:
                    await conn.execute(text("""
                        INSERT INTO core.hcps (id, tenant_id, master_hcp_id, specialty_code, region_code, segment, is_active, row_version, created_at, updated_at)
                        VALUES (:id, :tid, :master, :spec, :region, :segment, true, 1, now(), now())
                    """), batch)
                    batch = []
            if batch:
                await conn.execute(text("""
                    INSERT INTO core.hcps (id, tenant_id, master_hcp_id, specialty_code, region_code, segment, is_active, row_version, created_at, updated_at)
                    VALUES (:id, :tid, :master, :spec, :region, :segment, true, 1, now(), now())
                """), batch)
        print(f"  {len(hcp_map)} HCPs")

        # --- Events ---
        print("Loading events...")
        fmt_map = {"Virtual": "VIRTUAL", "In-person": "IN_PERSON", "Hybrid": "HYBRID"}
        sts_map = {"Completed": "COMPLETED", "Confirmed": "CONFIRMED", "Cancelled": "CANCELLED", "Proposed": "PROPOSED"}
        event_map = {}
        event_brand_map = {}  # event_id (csv) -> brand_id
        event_idx = 0
        with open(DATA_DIR / "events.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                eid = uuid.uuid4()
                event_map[r["event_id"]] = eid
                code = r["event_id"].lower()[:58]
                fmt = fmt_map.get(r.get("format", ""), "IN_PERSON")
                sts = sts_map.get(r.get("status", ""), "PROPOSED")
                topic = (r.get("topic") or "")[:58]
                name = (r.get("topic") or code)[:120]
                # Round-robin brand assignment
                assigned_brand_id = brand_id_list[event_idx % len(brand_id_list)]
                event_brand_map[r["event_id"]] = assigned_brand_id
                # Random venue data
                venue_city = random.choice(CITIES)
                venue_name = random.choice(VENUES)
                event_idx += 1
                await conn.execute(text("""
                    INSERT INTO core.events (id, tenant_id, brand_id, code, name, event_date, format, status, topic_code,
                        venue_city, venue_name,
                        workflow_status, measurement_eligible, row_version, created_at, updated_at)
                    VALUES (:id, :tid, :bid, :code, :name, :dt, :fmt, :sts, :topic,
                        :vcity, :vname,
                        'DRAFT', true, 1, now(), now())
                """), {"id": eid, "tid": tenant_id, "bid": assigned_brand_id, "code": code, "name": name, "dt": date.fromisoformat(r.get("date", "2026-01-01")), "fmt": fmt, "sts": sts, "topic": topic or None, "vcity": venue_city, "vname": venue_name})
        print(f"  {len(event_map)} events")

        # --- Event Costs ---
        print("Loading event costs...")
        cost_count = 0
        with open(DATA_DIR / "event_cost.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["event_id"] not in event_map:
                    continue
                eid = event_map[r["event_id"]]
                categories = ["honorarium", "venue", "meal", "travel", "agency"]
                for cat in categories:
                    amt = float(r.get(cat, 0) or 0)
                    if amt <= 0:
                        continue
                    await conn.execute(text("""
                        INSERT INTO core.event_costs (id, tenant_id, event_id, category_code, amount, currency, invoice_reference, row_version, created_at, updated_at)
                        VALUES (:id, :tid, :eid, :cat, :amt, 'INR', '', 1, now(), now())
                    """), {"id": uuid.uuid4(), "tid": tenant_id, "eid": eid, "cat": cat, "amt": amt})
                    cost_count += 1
        print(f"  {cost_count} cost line items")

        # --- Attendance (deduplicate by event+hcp) ---
        print("Loading attendance...")
        att_count = 0
        seen_att = set()
        with open(DATA_DIR / "event_attendance.csv", encoding="utf-8") as f:
            batch = []
            for r in csv.DictReader(f):
                if r["event_id"] not in event_map or r["hcp_id"] not in hcp_map:
                    continue
                key = (r["event_id"], r["hcp_id"])
                if key in seen_att:
                    continue
                seen_att.add(key)
                attended = r.get("verified_attended", "0") == "1"
                registered = r.get("registered", "0") == "1"
                reg_status = "ATTENDED" if attended else ("REGISTERED" if registered else "NOT_REGISTERED")
                vsource = "SIGN_IN_SHEET" if attended else "UNVERIFIED"
                dur = int(float(r.get("duration", 0) or 0)) or None
                batch.append({
                    "id": uuid.uuid4(), "tid": tenant_id,
                    "eid": event_map[r["event_id"]], "hid": hcp_map[r["hcp_id"]],
                    "reg": reg_status, "attended": attended, "vsource": vsource,
                    "dur": dur,
                })
                if len(batch) >= 1000:
                    await conn.execute(text("""
                        INSERT INTO core.attendance (id, tenant_id, event_id, hcp_id, registration_status, verified_attended, verification_source, duration_minutes, row_version, created_at, updated_at)
                        VALUES (:id, :tid, :eid, :hid, :reg, :attended, :vsource, :dur, 1, now(), now())
                    """), batch)
                    att_count += len(batch)
                    batch = []
            if batch:
                await conn.execute(text("""
                    INSERT INTO core.attendance (id, tenant_id, event_id, hcp_id, registration_status, verified_attended, verification_source, duration_minutes, row_version, created_at, updated_at)
                    VALUES (:id, :tid, :eid, :hid, :reg, :attended, :vsource, :dur, 1, now(), now())
                """), batch)
                att_count += len(batch)
        print(f"  {att_count} attendance records")

        # --- Rx Monthly ---
        print("Loading Rx data (large — please wait)...")
        rx_count = 0
        with open(DATA_DIR / "hcp_rx_monthly.csv", encoding="utf-8") as f:
            batch = []
            for r in csv.DictReader(f):
                if r["hcp_id"] not in hcp_map or r["product"] not in product_map:
                    continue
                m = r.get("month", "2026-01")
                try:
                    month_date = date.fromisoformat(m + "-01") if len(m) == 7 else date.fromisoformat(m)
                except ValueError:
                    continue
                batch.append({
                    "tid": tenant_id,
                    "hid": hcp_map[r["hcp_id"]],
                    "pid": product_map[r["product"]],
                    "bid": brand_map[r["product"]],
                    "month": month_date,
                    "nrx": int(float(r.get("nrx", 0) or 0)),
                    "trx": int(float(r.get("trx", 0) or 0)),
                    "ctrx": int(float(r.get("competitor_trx", 0) or 0)),
                })
                if len(batch) >= 2000:
                    await conn.execute(text("""
                        INSERT INTO core.hcp_rx_monthly (tenant_id, hcp_id, product_id, brand_id, month, nrx, trx, competitor_trx, created_at, updated_at)
                        VALUES (:tid, :hid, :pid, :bid, :month, :nrx, :trx, :ctrx, now(), now())
                    """), batch)
                    rx_count += len(batch)
                    if rx_count % 20000 == 0:
                        print(f"    {rx_count:,} rows...")
                    batch = []
            if batch:
                await conn.execute(text("""
                    INSERT INTO core.hcp_rx_monthly (tenant_id, hcp_id, product_id, brand_id, month, nrx, trx, competitor_trx, created_at, updated_at)
                    VALUES (:tid, :hid, :pid, :bid, :month, :nrx, :trx, :ctrx, now(), now())
                """), batch)
                rx_count += len(batch)
        print(f"  {rx_count:,} Rx records")

        # --- Market Factors ---
        print("Loading market factors...")
        mf_count = 0
        with open(DATA_DIR / "market_factors.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                m = r.get("month", "2026-01")
                try:
                    month_date = date.fromisoformat(m + "-01") if len(m) == 7 else date.fromisoformat(m)
                except ValueError:
                    continue
                region = (r.get("region") or "unknown")[:58]
                for prod, bid in brand_map.items():
                    await conn.execute(text("""
                        INSERT INTO core.market_factors (id, tenant_id, brand_id, region_code, month, access_index, seasonality_index, competitor_index, created_at, updated_at)
                        VALUES (:id, :tid, :bid, :region, :month, :access, :season, :comp, now(), now())
                        ON CONFLICT (tenant_id, brand_id, region_code, month) DO NOTHING
                    """), {
                        "id": uuid.uuid4(), "tid": tenant_id, "bid": bid,
                        "region": region, "month": month_date,
                        "access": float(r.get("access", 0) or 0),
                        "season": float(r.get("seasonality", 1) or 1),
                        "comp": float(r.get("competitor_index", 1) or 1),
                    })
                    mf_count += 1
        print(f"  {mf_count} market factor rows")

        # --- Campaigns (2 per brand) ---
        print("Loading campaigns...")
        brand_list = sorted(brand_map.keys())
        campaign_templates = [
            ("launch", "Product Launch", "ACTIVE", "Launch campaign to drive initial adoption"),
            ("awareness", "Awareness Program", "ACTIVE", "Speaker-led awareness and education program"),
        ]
        campaign_map = {}  # campaign_id -> brand_id
        campaigns_by_brand: dict[uuid.UUID, list[uuid.UUID]] = {}  # brand_id -> [campaign_ids]
        for brand_name in brand_list:
            bid = brand_map[brand_name]
            campaigns_by_brand[bid] = []
            for suffix, label, status, objective in campaign_templates:
                cid = uuid.uuid4()
                code_str = f"{brand_name.lower().replace(' ', '-')[:40]}-{suffix}"[:58]
                cname = f"{brand_name} {label}"[:200]
                campaign_map[cid] = bid
                campaigns_by_brand[bid].append(cid)
                await conn.execute(text("""
                    INSERT INTO core.campaigns (id, tenant_id, code, name, brand_id, objective, topic_code,
                        start_date, end_date, status, planned_budget, currency, row_version, created_at, updated_at)
                    VALUES (:id, :tid, :code, :name, :bid, :objective, :topic,
                        :start, :end, :status, :budget, 'INR', 1, now(), now())
                """), {
                    "id": cid, "tid": tenant_id, "code": code_str, "name": cname,
                    "bid": bid, "objective": objective, "topic": suffix,
                    "start": date(2026, 1, 1), "end": date(2026, 12, 31),
                    "status": status, "budget": 500000.0,
                })
        print(f"  {len(campaign_map)} campaigns")

        # --- Link events to campaigns ---
        print("Linking events to campaigns...")
        linked = 0
        for bid, cids in campaigns_by_brand.items():
            if not cids:
                continue
            # Fetch all event IDs for this brand that have no campaign yet
            result = await conn.execute(text(
                "SELECT id FROM core.events WHERE brand_id = :bid AND campaign_id IS NULL"
            ), {"bid": bid})
            event_ids = [row[0] for row in result.fetchall()]
            if not event_ids:
                continue
            # Split events roughly evenly across the brand's campaigns
            per_campaign = max(1, len(event_ids) // len(cids))
            for i, cid in enumerate(cids):
                start = i * per_campaign
                end = start + per_campaign if i < len(cids) - 1 else len(event_ids)
                chunk = event_ids[start:end]
                if not chunk:
                    continue
                for eid in chunk:
                    await conn.execute(text(
                        "UPDATE core.events SET campaign_id = :cid WHERE id = :eid"
                    ), {"cid": cid, "eid": eid})
                    linked += 1
        print(f"  {linked} events linked to campaigns")

    await engine.dispose()
    print("\n=== Seed complete ===")


if __name__ == "__main__":
    asyncio.run(main())
