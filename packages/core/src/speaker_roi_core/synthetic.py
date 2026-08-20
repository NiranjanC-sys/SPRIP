"""Deterministic synthetic data generator for demo and model validation.

All data is clearly labelled as synthetic. Random seeds are fixed so repeated
runs produce identical datasets. No real patient, prescriber, or commercial data
is fabricated.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

SEED = 42
RNG = np.random.RandomState(SEED)

SPECIALTIES = ["CARDIOLOGY", "ENDOCRINOLOGY", "ONCOLOGY", "NEUROLOGY", "RHEUMATOLOGY"]
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
SEGMENTS = ["HIGH", "MEDIUM", "LOW"]
FORMATS = ["IN_PERSON", "VIRTUAL", "HYBRID"]
TOPICS = ["EFFICACY", "SAFETY", "DOSING", "GUIDELINES", "CASE_STUDIES"]


def _uuid_from_seed(label: str) -> uuid.UUID:
    return uuid.UUID(hashlib.md5(label.encode()).hexdigest())  # noqa: S324


def generate_tenant(tenant_code: str = "DEMO_PHARMA") -> dict[str, Any]:
    return {
        "id": _uuid_from_seed(f"tenant:{tenant_code}"),
        "code": tenant_code,
        "name": f"{tenant_code.replace('_', ' ').title()} (Synthetic)",
        "status": "ACTIVE",
        "country_code": "US",
    }


def generate_brands(tenant_id: uuid.UUID, n: int = 3) -> list[dict[str, Any]]:
    names = ["CardioMax", "EndoBalance", "OncoShield"]
    return [
        {
            "id": _uuid_from_seed(f"brand:{i}"),
            "tenant_id": tenant_id,
            "code": f"BRAND_{i:02d}",
            "name": f"{names[i % len(names)]} (Synthetic)",
            "therapeutic_area": SPECIALTIES[i % len(SPECIALTIES)],
            "is_active": True,
        }
        for i in range(n)
    ]


def generate_hcps(tenant_id: uuid.UUID, n: int = 200) -> pd.DataFrame:
    records = []
    for i in range(n):
        records.append(
            {
                "id": str(_uuid_from_seed(f"hcp:{i}")),
                "tenant_id": str(tenant_id),
                "master_hcp_id": f"HCP-{i:05d}",
                "specialty_code": SPECIALTIES[i % len(SPECIALTIES)],
                "region_code": REGIONS[i % len(REGIONS)],
                "segment": SEGMENTS[i % len(SEGMENTS)],
                "practice_type": "GROUP" if i % 3 == 0 else "SOLO",
                "city_code": f"CITY_{(i % 10):02d}",
                "is_active": True,
            }
        )
    return pd.DataFrame(records)


def generate_events(
    tenant_id: uuid.UUID,
    brand_ids: list[uuid.UUID],
    n: int = 60,
    start_date: date = date(2024, 1, 1),
) -> pd.DataFrame:
    records = []
    for i in range(n):
        event_date = start_date + timedelta(days=int(RNG.randint(0, 365)))
        brand_id = brand_ids[i % len(brand_ids)]
        records.append(
            {
                "id": str(_uuid_from_seed(f"event:{i}")),
                "tenant_id": str(tenant_id),
                "code": f"EVT-{i:04d}",
                "name": f"Speaker Program {i + 1} (Synthetic)",
                "brand_id": str(brand_id),
                "event_date": event_date.isoformat(),
                "format": FORMATS[i % len(FORMATS)],
                "topic_code": TOPICS[i % len(TOPICS)],
                "region_code": REGIONS[i % len(REGIONS)],
                "planned_attendance": int(RNG.randint(10, 80)),
                "status": "COMPLETED",
                "workflow_status": "MEASURED",
                "measurement_eligible": True,
            }
        )
    return pd.DataFrame(records)


def generate_attendance(
    tenant_id: uuid.UUID,
    events_df: pd.DataFrame,
    hcps_df: pd.DataFrame,
    avg_attendees: int = 15,
    treatment_fraction: float = 0.4,
) -> pd.DataFrame:
    """Generate attendance records where only ~40% of HCPs ever attend any event."""
    records = []
    hcp_ids = hcps_df["id"].tolist()
    n_eligible = int(len(hcp_ids) * treatment_fraction)
    eligible_pool = list(RNG.choice(hcp_ids, size=n_eligible, replace=False))

    for _, event in events_df.iterrows():
        n_attend = min(int(RNG.poisson(avg_attendees)), len(eligible_pool))
        attendees = RNG.choice(eligible_pool, size=n_attend, replace=False)
        for hcp_id in attendees:
            records.append(
                {
                    "event_id": event["id"],
                    "hcp_id": hcp_id,
                    "tenant_id": str(tenant_id),
                    "status": "VERIFIED",
                    "attended": True,
                }
            )
    return pd.DataFrame(records)


def generate_rx_data(
    tenant_id: uuid.UUID,
    hcps_df: pd.DataFrame,
    events_df: pd.DataFrame,
    attendance_df: pd.DataFrame,
    pre_months: int = 6,
    post_months: int = 6,
) -> pd.DataFrame:
    """Generate synthetic monthly prescription data with a causal treatment effect.

    Attendees get an uplift of ~2-5 NRx/month post-event on average.
    Controls follow a baseline trend only.
    """
    records = []
    attended_hcps = set(attendance_df["hcp_id"].unique())

    for _, hcp_row in hcps_df.iterrows():
        hcp_id = hcp_row["id"]
        base_nrx = float(RNG.lognormal(2.5, 0.6))
        trend = float(RNG.normal(0.01, 0.005))

        is_attendee = hcp_id in attended_hcps
        treatment_effect = float(RNG.uniform(2, 5)) if is_attendee else 0.0

        for month_offset in range(-pre_months, post_months + 1):
            period = date(2024, 6, 1) + timedelta(days=30 * month_offset)
            noise = float(RNG.normal(0, 1.5))
            nrx = base_nrx + trend * month_offset + noise
            if month_offset > 0 and is_attendee:
                nrx += treatment_effect * np.exp(-0.15 * month_offset)
            nrx = max(0.0, nrx)
            trx = nrx * float(RNG.uniform(1.5, 2.5))

            records.append(
                {
                    "hcp_id": hcp_id,
                    "tenant_id": str(tenant_id),
                    "period": period.isoformat(),
                    "nrx": round(nrx, 1),
                    "trx": round(trx, 1),
                    "is_observed": True,
                    "coverage_factor": 1.0,
                }
            )

    return pd.DataFrame(records)


def generate_costs(
    tenant_id: uuid.UUID, events_df: pd.DataFrame
) -> pd.DataFrame:
    records = []
    categories = ["VENUE", "HONORARIUM", "LOGISTICS", "CATERING", "AV_EQUIPMENT"]
    for _, event in events_df.iterrows():
        n_costs = int(RNG.randint(2, 5))
        for j in range(n_costs):
            records.append(
                {
                    "event_id": event["id"],
                    "tenant_id": str(tenant_id),
                    "category_code": categories[j % len(categories)],
                    "amount": round(float(RNG.uniform(500, 15000)), 2),
                    "currency": "USD",
                }
            )
    return pd.DataFrame(records)


def generate_full_dataset() -> dict[str, pd.DataFrame]:
    """Generate a complete synthetic dataset for demo/training."""
    tenant = generate_tenant()
    tenant_id = tenant["id"]
    brands = generate_brands(tenant_id, n=3)
    brand_ids = [b["id"] for b in brands]

    hcps_df = generate_hcps(tenant_id, n=200)
    events_df = generate_events(tenant_id, brand_ids, n=60)
    attendance_df = generate_attendance(tenant_id, events_df, hcps_df)
    rx_df = generate_rx_data(tenant_id, hcps_df, events_df, attendance_df)
    costs_df = generate_costs(tenant_id, events_df)

    return {
        "tenant": pd.DataFrame([tenant]),
        "brands": pd.DataFrame(brands),
        "hcps": hcps_df,
        "events": events_df,
        "attendance": attendance_df,
        "rx_monthly": rx_df,
        "costs": costs_df,
    }
