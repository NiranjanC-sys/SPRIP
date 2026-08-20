"""
=============================================================================
 Feature Engineering — Pre-event HCP-level features for propensity modeling
 Reads: data/silver/conformed/, data/gold/eligibility_table.csv
 Writes: data/gold/hcp_event_features.csv
=============================================================================
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = os.path.join(ROOT, "data", "silver", "conformed")
GOLD = os.path.join(ROOT, "data", "gold")

# ---- Topic-to-product and specialty-topic-match mappings --------------------

TOPIC_PRODUCT = {
    "Heart Failure Management": "CARDIVEX",
    "Lipid Management & CV Risk": "CARDIVEX",
    "Advanced Solid Tumor Therapy": "ONCOLERA",
    "Immuno-Oncology Sequencing": "ONCOLERA",
    "Type 2 Diabetes Intensification": "ENDOSTAT",
    "Obesity & Metabolic Health": "ENDOSTAT",
    "Migraine Prophylaxis": "NEUROVANT",
    "Neuroinflammation Update": "NEUROVANT",
}

TOPIC_SPECIALTY_MATCH = {
    "Heart Failure Management": {"Cardiology", "Primary Care", "Endocrinology"},
    "Lipid Management & CV Risk": {"Cardiology", "Primary Care", "Endocrinology"},
    "Advanced Solid Tumor Therapy": {"Oncology", "Gastroenterology"},
    "Immuno-Oncology Sequencing": {"Oncology", "Gastroenterology", "Dermatology"},
    "Type 2 Diabetes Intensification": {"Endocrinology", "Primary Care", "Cardiology"},
    "Obesity & Metabolic Health": {"Endocrinology", "Primary Care", "Cardiology", "Gastroenterology"},
    "Migraine Prophylaxis": {"Neurology", "Primary Care", "Psychiatry"},
    "Neuroinflammation Update": {"Neurology", "Psychiatry"},
}


def month_offset(base_ym: str, delta: int) -> str:
    y, m = int(base_ym[:4]), int(base_ym[5:7])
    total = y * 12 + (m - 1) + delta
    ny, nm = divmod(total, 12)
    return f"{ny}-{nm + 1:02d}"


def main():
    print("=" * 68)
    print("FEATURE ENGINEERING")
    print("=" * 68)

    # ---- Load ---------------------------------------------------------------
    print("\nLoading inputs ...")
    elig = pd.read_csv(os.path.join(GOLD, "eligibility_table.csv"), dtype=str)
    hcp = pd.read_csv(os.path.join(SILVER, "hcp_master.csv"), dtype=str)
    events = pd.read_csv(os.path.join(SILVER, "events.csv"),
                         dtype={"event_id": str, "topic": str, "format": str,
                                "speaker": str, "status": str})
    events["date"] = pd.to_datetime(events["date"])
    rx = pd.read_csv(os.path.join(SILVER, "hcp_rx_monthly.csv"),
                     dtype={"hcp_id": str, "month": str, "product": str,
                            "nrx": int, "trx": int, "competitor_trx": int})
    mkt = pd.read_csv(os.path.join(SILVER, "marketing_activity.csv"),
                      dtype={"hcp_id": str, "rep_calls": int, "emails": int,
                             "samples": int, "other_events": int})
    mkt["date"] = pd.to_datetime(mkt["date"])
    mkt["month"] = mkt["date"].dt.strftime("%Y-%m")
    mf = pd.read_csv(os.path.join(SILVER, "market_factors.csv"),
                     dtype={"region": str, "month": str})
    att = pd.read_csv(os.path.join(SILVER, "event_attendance.csv"),
                      dtype={"event_id": str, "hcp_id": str,
                             "verified_attended": int})

    # ---- Filter to non-excluded pairs ----------------------------------------
    pairs = elig[elig["group"].isin(["treatment", "control_candidate"])].copy()
    pairs["event_date"] = pd.to_datetime(pairs["event_date"])
    print(f"    Non-excluded HCP-event pairs to featurize: {len(pairs):,}")

    # ---- Build lookup structures for performance ----------------------------
    event_info = events.set_index("event_id")[["date", "topic", "format"]].to_dict("index")
    hcp_info = hcp.set_index("hcp_id")[["specialty", "region", "segment"]].to_dict("index")

    # Rx: group by (hcp_id, product, month) for fast lookup
    rx_idx = rx.set_index(["hcp_id", "product", "month"])

    # Marketing: group by (hcp_id, month)
    mkt_by = mkt.groupby(["hcp_id", "month"])[["rep_calls", "emails", "samples"]].sum()

    # Market factors: group by (region, month)
    mf_by = mf.set_index(["region", "month"])

    # Prior attendance: for each HCP, sorted list of event dates they attended
    att_verified = att[att["verified_attended"] == 1][["event_id", "hcp_id"]].copy()
    att_verified = att_verified.merge(events[["event_id", "date"]], on="event_id")
    prior_att = att_verified.groupby("hcp_id").apply(
        lambda g: sorted(g["date"].tolist()), include_groups=False
    ).to_dict()

    # ---- Feature computation ------------------------------------------------
    print("    Computing features ...")

    rows = []
    for _, p in pairs.iterrows():
        hid = p["master_hcp_id"]
        eid = p["event_id"]
        edate = p["event_date"]
        grp = p["group"]

        ei = event_info.get(eid, {})
        hi = hcp_info.get(hid, {})
        topic = ei.get("topic", "")
        product = TOPIC_PRODUCT.get(topic, "")
        spec = hi.get("specialty", "")
        reg = hi.get("region", "")
        seg = hi.get("segment", "")
        event_month = edate.strftime("%Y-%m")

        # Pre-event months: 6m = months -6..-1, 3m = months -3..-1
        months_6 = [month_offset(event_month, -k) for k in range(1, 7)]
        months_3 = months_6[:3]

        # ---- Rx features (product-specific) ---------------------------------
        nrx_6, trx_6, comp_6 = [], [], []
        for m in months_6:
            try:
                r = rx_idx.loc[(hid, product, m)]
                nrx_6.append(r["nrx"])
                trx_6.append(r["trx"])
                comp_6.append(r["competitor_trx"])
            except KeyError:
                pass

        nrx_3 = nrx_6[:3]
        trx_3 = trx_6[:3]

        avg_nrx_6m = float(np.mean(nrx_6)) if nrx_6 else np.nan
        avg_nrx_3m = float(np.mean(nrx_3)) if nrx_3 else np.nan
        avg_trx_6m = float(np.mean(trx_6)) if trx_6 else np.nan
        avg_trx_3m = float(np.mean(trx_3)) if trx_3 else np.nan
        competitor_trx_avg = float(np.mean(comp_6)) if comp_6 else np.nan

        # NRx trend: slope over the 6-month window (positive = rising)
        if len(nrx_6) >= 3:
            # nrx_6 is ordered newest-first (month -1, -2, ... -6)
            # reverse for chronological order
            y = np.array(nrx_6[::-1], dtype=float)
            x = np.arange(len(y), dtype=float)
            nrx_trend = float(np.polyfit(x, y, 1)[0])
        else:
            nrx_trend = np.nan

        # ---- Marketing features (3 months before event) --------------------
        rep_3, email_3, samp_3 = 0, 0, 0
        for m in months_3:
            try:
                mk = mkt_by.loc[(hid, m)]
                rep_3 += int(mk["rep_calls"])
                email_3 += int(mk["emails"])
                samp_3 += int(mk["samples"])
            except KeyError:
                pass

        # ---- Prior event attendance count -----------------------------------
        hcp_dates = prior_att.get(hid, [])
        prior_event_count = sum(1 for d in hcp_dates if d < edate)

        # ---- Specialty-topic match ------------------------------------------
        match_specs = TOPIC_SPECIALTY_MATCH.get(topic, set())
        specialty_topic_match = 1 if spec in match_specs else 0

        # ---- Market factors for HCP region + event month --------------------
        try:
            mfr = mf_by.loc[(reg, event_month)]
            access_index = float(mfr["access"])
            seasonality_index = float(mfr["seasonality"])
            competitor_index_mf = float(mfr["competitor_index"])
        except KeyError:
            access_index = np.nan
            seasonality_index = np.nan
            competitor_index_mf = np.nan

        rows.append({
            "master_hcp_id": hid,
            "event_id": eid,
            "group": grp,
            "avg_nrx_3m": round(avg_nrx_3m, 4) if not np.isnan(avg_nrx_3m) else np.nan,
            "avg_nrx_6m": round(avg_nrx_6m, 4) if not np.isnan(avg_nrx_6m) else np.nan,
            "avg_trx_3m": round(avg_trx_3m, 4) if not np.isnan(avg_trx_3m) else np.nan,
            "avg_trx_6m": round(avg_trx_6m, 4) if not np.isnan(avg_trx_6m) else np.nan,
            "nrx_trend": round(nrx_trend, 4) if not np.isnan(nrx_trend) else np.nan,
            "competitor_trx_avg": round(competitor_trx_avg, 4) if not np.isnan(competitor_trx_avg) else np.nan,
            "rep_calls_3m": rep_3,
            "emails_3m": email_3,
            "samples_3m": samp_3,
            "prior_event_count": prior_event_count,
            "specialty_topic_match": specialty_topic_match,
            "access_index": round(access_index, 4) if not np.isnan(access_index) else np.nan,
            "seasonality_index": round(seasonality_index, 4) if not np.isnan(seasonality_index) else np.nan,
            "competitor_index": round(competitor_index_mf, 4) if not np.isnan(competitor_index_mf) else np.nan,
            "segment": seg,
            "specialty": spec,
            "region": reg,
        })

    features = pd.DataFrame(rows)

    # ---- Write output -------------------------------------------------------
    out_path = os.path.join(GOLD, "hcp_event_features.csv")
    features.to_csv(out_path, index=False)

    # ---- Summary ------------------------------------------------------------
    print(f"\n{'='*68}")
    print(f"FEATURE ENGINEERING COMPLETE")
    print(f"{'='*68}")
    print(f"    Output:  {out_path}")
    print(f"    Rows:    {len(features):,}")
    print(f"    Columns: {features.shape[1]}")
    print(f"\n    Group breakdown:")
    for g, c in features["group"].value_counts().items():
        print(f"        {g:25s} {c:>7,}")
    print(f"\n    Null counts per feature:")
    nulls = features.isnull().sum()
    for col in nulls.index:
        n = int(nulls[col])
        if n > 0:
            print(f"        {col:30s} {n:>6,} ({n/len(features)*100:.1f}%)")
    if nulls.sum() == 0:
        print(f"        (none)")
    print(f"\n    Feature ranges:")
    num_cols = [c for c in features.columns
                if c not in ("master_hcp_id", "event_id", "group",
                             "segment", "specialty", "region")]
    for c in num_cols:
        s = features[c].dropna()
        if len(s) > 0:
            print(f"        {c:30s} min={s.min():>8.2f}  mean={s.mean():>8.2f}  max={s.max():>8.2f}")


if __name__ == "__main__":
    main()
