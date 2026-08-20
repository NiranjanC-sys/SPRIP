#!/usr/bin/env python3
"""Seed the database with synthetic data for hackathon demo.

Generates and inserts: tenants, brands, products, HCPs, campaigns, events,
attendance, Rx data, event costs, and taxonomy values directly via SQLAlchemy ORM.

Usage:
    python scripts/seed_synthetic.py
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# -- DB connection (hardcoded per task spec, never from env/key.txt) ----------
SYNC_URL = "postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi"

# -- Import ORM models -------------------------------------------------------
from speaker_roi_core.models import (  # noqa: E402
    Attendance,
    Brand,
    Campaign,
    Event,
    EventCost,
    EventSpeaker,
    Hcp,
    HcpRxMonthly,
    Product,
    TaxonomyValue,
    Tenant,
)
from speaker_roi_core.enums import (  # noqa: E402
    AttendanceStatus,
    AttendanceVerificationSource,
    CampaignStatus,
    EventFormat,
    EventStatus,
    EventWorkflowStatus,
    TaxonomyKind,
    TenantStatus,
)

# -- Config -------------------------------------------------------------------
SEED = 42
NUM_HCPS = 150
NUM_BRANDS = 5
PRODUCTS_PER_BRAND = 2
NUM_CAMPAIGNS = 12
NUM_EVENTS = 60
RX_MONTHS = 18  # months of Rx history

SPECIALTIES = ["CARDIOLOGY", "ONCOLOGY", "NEUROLOGY", "ENDOCRINOLOGY", "PULMONOLOGY",
               "RHEUMATOLOGY", "GASTROENTEROLOGY", "NEPHROLOGY"]
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
TOPICS = ["HEART_FAILURE", "DIABETES_MGT", "ONCOLOGY_BIOMARKERS", "NEURO_INFLAMMATION",
          "RESPIRATORY_CARE", "IMMUNOTHERAPY", "GI_DISORDERS", "RENAL_FUNCTION"]
COST_CATEGORIES = ["VENUE", "HONORARIUM", "TRAVEL", "CATERING", "AV_EQUIPMENT"]
CITIES = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Hyderabad",
          "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow"]
BRAND_NAMES = [
    ("CARDIOMAX", "CardioMax", "Cardiovascular"),
    ("ONCOSHIELD", "OncoShield", "Oncology"),
    ("NEUROZEN", "NeuroZen", "Neurology"),
    ("ENDOCARE", "EndoCare", "Endocrinology"),
    ("PULMOFIT", "PulmoFit", "Respiratory"),
]
EVENT_FORMATS = [EventFormat.IN_PERSON, EventFormat.VIRTUAL, EventFormat.HYBRID,
                 EventFormat.ROUNDTABLE]
SPEAKER_TIERS = ["KOL", "NATIONAL", "REGIONAL", "LOCAL"]


def main() -> None:
    rng = random.Random(SEED)
    np_rng = np.random.default_rng(SEED)
    engine = create_engine(SYNC_URL)

    with Session(engine) as session:
        # Set the search path so we can use the ORM models directly
        session.execute(text("SET search_path TO core, analytics, ml, auth, audit, ingestion, public"))

        # ---- Tenant --------------------------------------------------------
        tenant_id = uuid.uuid4()
        tenant = Tenant(
            id=tenant_id,
            code="DEMO_PHARMA",
            name="Demo Pharmaceutical Corp",
            status=TenantStatus.ACTIVE,
            country="IN",
            reporting_currency="INR",
            synthetic_mode=True,
        )
        session.add(tenant)
        session.flush()
        print(f"[+] Tenant: {tenant.name} ({tenant_id})")

        # ---- Taxonomy values ------------------------------------------------
        taxonomy_ids: dict[str, uuid.UUID] = {}
        tax_items = []
        for kind, codes in [
            (TaxonomyKind.SPECIALTY, SPECIALTIES),
            (TaxonomyKind.REGION, REGIONS),
            (TaxonomyKind.TOPIC, TOPICS),
            (TaxonomyKind.COST_CATEGORY, COST_CATEGORIES),
            (TaxonomyKind.THERAPEUTIC_AREA, ["Cardiovascular", "Oncology", "Neurology",
                                              "Endocrinology", "Respiratory"]),
        ]:
            for i, code in enumerate(codes):
                tv_id = uuid.uuid4()
                taxonomy_ids[f"{kind.value}:{code}"] = tv_id
                tax_items.append(TaxonomyValue(
                    id=tv_id,
                    tenant_id=tenant_id,
                    kind=kind,
                    code=code,
                    label=code.replace("_", " ").title(),
                    sort_order=i,
                    is_active=True,
                ))
        session.add_all(tax_items)
        session.flush()
        print(f"[+] Taxonomy values: {len(tax_items)}")

        # ---- Brands ---------------------------------------------------------
        brand_ids: list[uuid.UUID] = []
        brand_objs: list[Brand] = []
        for code, name, ta in BRAND_NAMES[:NUM_BRANDS]:
            bid = uuid.uuid4()
            brand_ids.append(bid)
            b = Brand(
                id=bid,
                tenant_id=tenant_id,
                code=code,
                name=name,
                therapeutic_area_code=ta,
                molecule=f"{name}mab",
                is_active=True,
                launch_date=date(2020, 1, 1),
            )
            brand_objs.append(b)
        session.add_all(brand_objs)
        session.flush()
        print(f"[+] Brands: {len(brand_objs)}")

        # ---- Products -------------------------------------------------------
        product_ids: list[uuid.UUID] = []
        product_brand_map: dict[uuid.UUID, uuid.UUID] = {}
        products: list[Product] = []
        for bid in brand_ids:
            for j in range(PRODUCTS_PER_BRAND):
                pid = uuid.uuid4()
                product_ids.append(pid)
                product_brand_map[pid] = bid
                brand_obj = next(b for b in brand_objs if b.id == bid)
                products.append(Product(
                    id=pid,
                    tenant_id=tenant_id,
                    brand_id=bid,
                    code=f"{brand_obj.code}_{j+1}",
                    name=f"{brand_obj.name} {['Tablets', 'Injection', 'Capsules'][j % 3]}",
                    formulation=["TABLET", "INJECTION", "CAPSULE"][j % 3],
                    strength=f"{rng.choice([5, 10, 25, 50, 100])}mg",
                    is_active=True,
                ))
        session.add_all(products)
        session.flush()
        print(f"[+] Products: {len(products)}")

        # ---- HCPs -----------------------------------------------------------
        hcp_ids: list[uuid.UUID] = []
        hcps: list[Hcp] = []
        for i in range(NUM_HCPS):
            hid = uuid.uuid4()
            hcp_ids.append(hid)
            hcps.append(Hcp(
                id=hid,
                tenant_id=tenant_id,
                master_hcp_id=f"HCP{i+1:04d}",
                specialty_code=rng.choice(SPECIALTIES),
                region_code=rng.choice(REGIONS),
                practice_type=rng.choice(["HOSPITAL", "CLINIC", "ACADEMIC"]),
                segment=rng.choice(["HIGH", "MEDIUM", "LOW"]),
                city_code=rng.choice(CITIES),
                is_active=True,
                first_seen_on=date(2022, 1, 1),
            ))
        session.add_all(hcps)
        session.flush()
        print(f"[+] HCPs: {len(hcps)}")

        # ---- Campaigns ------------------------------------------------------
        campaign_ids: list[uuid.UUID] = []
        campaigns: list[Campaign] = []
        for i in range(NUM_CAMPAIGNS):
            cid = uuid.uuid4()
            campaign_ids.append(cid)
            brand_id = rng.choice(brand_ids)
            start = date(2024, 1, 1) + timedelta(days=rng.randint(0, 365))
            campaigns.append(Campaign(
                id=cid,
                tenant_id=tenant_id,
                code=f"CAMP{i+1:03d}",
                name=f"Campaign {i+1} - {rng.choice(TOPICS).replace('_',' ').title()}",
                brand_id=brand_id,
                objective=rng.choice(["Awareness", "Adoption", "Retention", "Education"]),
                topic_code=rng.choice(TOPICS),
                start_date=start,
                end_date=start + timedelta(days=rng.randint(60, 180)),
                status=rng.choice([CampaignStatus.ACTIVE, CampaignStatus.COMPLETED]),
                planned_budget=float(rng.randint(200_000, 2_000_000)),
                currency="INR",
            ))
        session.add_all(campaigns)
        session.flush()
        print(f"[+] Campaigns: {len(campaigns)}")

        # ---- Events ---------------------------------------------------------
        event_ids: list[uuid.UUID] = []
        event_objs: list[Event] = []
        event_brand_map: dict[uuid.UUID, uuid.UUID] = {}
        event_date_map: dict[uuid.UUID, date] = {}
        for i in range(NUM_EVENTS):
            eid = uuid.uuid4()
            event_ids.append(eid)
            brand_id = rng.choice(brand_ids)
            event_brand_map[eid] = brand_id
            fmt = rng.choice(EVENT_FORMATS)
            ev_date = date(2024, 1, 1) + timedelta(days=rng.randint(0, 500))
            event_date_map[eid] = ev_date
            # Most events completed, some proposed
            if i < 50:
                status = EventStatus.COMPLETED
                wf_status = EventWorkflowStatus.MEASURABLE
            else:
                status = EventStatus.PROPOSED
                wf_status = EventWorkflowStatus.DRAFT
            event_objs.append(Event(
                id=eid,
                tenant_id=tenant_id,
                code=f"EVT{i+1:04d}",
                name=f"Speaker Program {i+1}",
                campaign_id=rng.choice(campaign_ids),
                brand_id=brand_id,
                event_date=ev_date,
                start_time=time(rng.randint(9, 17), 0),
                format=fmt,
                topic_code=rng.choice(TOPICS),
                region_code=rng.choice(REGIONS),
                venue_city=rng.choice(CITIES),
                speaker_tier=rng.choice(SPEAKER_TIERS),
                planned_attendance=rng.randint(15, 80),
                status=status,
                workflow_status=wf_status,
                measurement_eligible=True,
                currency="INR",
            ))
        session.add_all(event_objs)
        session.flush()
        print(f"[+] Events: {len(event_objs)}")

        # ---- Event Speakers -------------------------------------------------
        speakers: list[EventSpeaker] = []
        for eid in event_ids:
            n_speakers = rng.randint(1, 3)
            for _ in range(n_speakers):
                speakers.append(EventSpeaker(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    event_id=eid,
                    hcp_id=rng.choice(hcp_ids),
                    tier=rng.choice(SPEAKER_TIERS),
                    speaking_role=rng.choice(["PRIMARY", "PANEL", "CHAIR"]),
                    honorarium_amount=float(rng.randint(10_000, 100_000)),
                    currency="INR",
                ))
        session.add_all(speakers)
        session.flush()
        print(f"[+] Event speakers: {len(speakers)}")

        # ---- Attendance (only for completed events) -------------------------
        completed_event_ids = [e.id for e in event_objs if e.status == EventStatus.COMPLETED]
        attendance_records: list[Attendance] = []
        # Track (event_id, hcp_id) to avoid duplicates
        attendance_keys: set[tuple[uuid.UUID, uuid.UUID]] = set()
        hcp_event_attendance: dict[uuid.UUID, list[uuid.UUID]] = {h: [] for h in hcp_ids}

        for eid in completed_event_ids:
            n_attendees = rng.randint(10, 50)
            attendee_hcps = rng.sample(hcp_ids, min(n_attendees, len(hcp_ids)))
            for hid in attendee_hcps:
                key = (eid, hid)
                if key in attendance_keys:
                    continue
                attendance_keys.add(key)
                verified = rng.random() > 0.15  # 85% verified
                attendance_records.append(Attendance(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    event_id=eid,
                    hcp_id=hid,
                    registration_status=AttendanceStatus.ATTENDED if verified else AttendanceStatus.REGISTERED,
                    verified_attended=verified,
                    verification_source=(
                        rng.choice([AttendanceVerificationSource.SIGN_IN_SHEET,
                                    AttendanceVerificationSource.BADGE_SCAN])
                        if verified
                        else AttendanceVerificationSource.UNVERIFIED
                    ),
                    duration_minutes=rng.randint(30, 120) if verified else None,
                ))
                if verified:
                    hcp_event_attendance[hid].append(eid)

        session.add_all(attendance_records)
        session.flush()
        print(f"[+] Attendance records: {len(attendance_records)}")

        # ---- HCP Rx Monthly ------------------------------------------------
        # Generate 18 months of Rx data for each HCP-product pair
        # HCPs who attended events get a bump in post-event months
        rx_records: list[HcpRxMonthly] = []
        base_date = date(2024, 1, 1)
        rx_keys: set[tuple[uuid.UUID, uuid.UUID, date]] = set()

        for hid in hcp_ids:
            # Each HCP prescribes 1-3 products
            n_products = rng.randint(1, 3)
            hcp_products = rng.sample(product_ids, min(n_products, len(product_ids)))

            for pid in hcp_products:
                bid = product_brand_map[pid]
                base_nrx = np_rng.poisson(lam=rng.uniform(5, 30))

                for m in range(RX_MONTHS):
                    month = date(base_date.year + (base_date.month + m - 1) // 12,
                                 (base_date.month + m - 1) % 12 + 1, 1)
                    rx_key = (hid, pid, month)
                    if rx_key in rx_keys:
                        continue
                    rx_keys.add(rx_key)

                    # Simulate treatment effect: boost Rx after event attendance
                    boost = 0.0
                    for evt_id in hcp_event_attendance.get(hid, []):
                        evt_date = event_date_map.get(evt_id)
                        if evt_date and evt_date < month and (month - evt_date).days < 180:
                            boost += np_rng.uniform(1.5, 5.0)

                    nrx = max(0, base_nrx + np_rng.normal(0, 3) + boost)
                    trx = nrx * np_rng.uniform(1.1, 1.5)

                    rx_records.append(HcpRxMonthly(
                        tenant_id=tenant_id,
                        hcp_id=hid,
                        product_id=pid,
                        month=month,
                        brand_id=bid,
                        nrx=round(float(nrx), 2),
                        trx=round(float(trx), 2),
                        is_observed=True,
                        coverage_factor=rng.uniform(0.7, 1.0),
                    ))

        # Bulk insert Rx data in batches
        BATCH_SIZE = 2000
        for i in range(0, len(rx_records), BATCH_SIZE):
            session.add_all(rx_records[i:i + BATCH_SIZE])
            session.flush()
        print(f"[+] Rx monthly records: {len(rx_records)}")

        # ---- Event Costs ----------------------------------------------------
        cost_records: list[EventCost] = []
        for eid in completed_event_ids:
            for cat in rng.sample(COST_CATEGORIES, rng.randint(2, 4)):
                cost_records.append(EventCost(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    event_id=eid,
                    category_code=cat,
                    amount=float(rng.randint(5_000, 200_000)),
                    currency="INR",
                    amount_base=float(rng.randint(5_000, 200_000)),
                    invoice_reference=f"INV-{uuid.uuid4().hex[:8].upper()}",
                ))
        session.add_all(cost_records)
        session.flush()
        print(f"[+] Event costs: {len(cost_records)}")

        # ---- Commit everything ----------------------------------------------
        session.commit()
        print("\n=== Synthetic data seeded successfully ===")
        print(f"    Tenant:     {tenant.name}")
        print(f"    Brands:     {len(brand_objs)}")
        print(f"    Products:   {len(products)}")
        print(f"    HCPs:       {len(hcps)}")
        print(f"    Campaigns:  {len(campaigns)}")
        print(f"    Events:     {len(event_objs)}")
        print(f"    Attendance: {len(attendance_records)}")
        print(f"    Rx records: {len(rx_records)}")
        print(f"    Costs:      {len(cost_records)}")
        print(f"\n    Tenant ID:  {tenant_id}")


if __name__ == "__main__":
    main()
