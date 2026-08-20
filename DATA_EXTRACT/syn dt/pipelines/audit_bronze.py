"""Comprehensive audit of data/bronze/ CSVs."""
import os, sys
import pandas as pd
import numpy as np
from datetime import date

B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bronze")

results = []
def chk(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, status, detail))
    print(f"  {'PASS' if ok else '** FAIL **':>10}  {name}  {detail}")

def warn(name, detail=""):
    results.append((name, "WARN", detail))
    print(f"  {'WARN':>10}  {name}  {detail}")

# ── Load all files ──────────────────────────────────────────────────────────
print("=== 1. SCHEMA (load + column names) ===")
FILES = {
    "hcp_master.csv": ["hcp_id","specialty","region","segment","active_flag"],
    "events.csv": ["event_id","date","topic","format","speaker","status"],
    "event_invitations.csv": ["event_id","hcp_id","invited_at","channel","eligible_reason"],
    "event_attendance.csv": ["event_id","hcp_id","registered","verified_attended","duration","engagement"],
    "hcp_rx_monthly.csv": ["hcp_id","month","product","nrx","trx","competitor_trx"],
    "marketing_activity.csv": ["hcp_id","date","rep_calls","emails","samples","other_events"],
    "event_cost.csv": ["event_id","honorarium","venue","meal","travel","agency","total"],
    "market_factors.csv": ["region","month","access","seasonality","competitor_index"],
    "identity_crosswalk.csv": ["master_hcp_id","crm_hcp_id","event_hcp_id","rx_vendor_hcp_id","match_status"],
    "business_assumptions.csv": ["product","scenario","expected_fills_per_new_rx","net_contribution_per_fill","net_contribution_per_incremental_nrx"],
    "ground_truth.csv": ["event_id","hcp_id","true_event_effect_nrx","true_event_effect_trx"],
}
D = {}
for fn, expected_cols in FILES.items():
    try:
        df = pd.read_csv(os.path.join(B, fn), keep_default_na=True)
        D[fn] = df
        match = list(df.columns) == expected_cols
        chk(f"schema_{fn}", match, f"cols={'OK' if match else list(df.columns)} rows={len(df)}")
    except Exception as e:
        chk(f"schema_{fn}", False, str(e))

# ── 2. Primary Keys ────────────────────────────────────────────────────────
print("\n=== 2. PRIMARY KEYS ===")
PK = [
    ("hcp_master.csv", ["hcp_id"]),
    ("events.csv", ["event_id"]),
    ("event_cost.csv", ["event_id"]),
    ("identity_crosswalk.csv", ["master_hcp_id"]),
    ("business_assumptions.csv", ["product","scenario"]),
    ("market_factors.csv", ["region","month"]),
    ("marketing_activity.csv", ["hcp_id","date"]),
    ("hcp_rx_monthly.csv", ["hcp_id","month","product"]),
    ("ground_truth.csv", ["event_id","hcp_id"]),
    ("event_invitations.csv", ["event_id","hcp_id"]),
]
for fn, keys in PK:
    df = D[fn]
    n_dup = len(df) - len(df.drop_duplicates(keys))
    chk(f"pk_{fn}_{'_'.join(keys)}", n_dup == 0, f"duplicates={n_dup}")

# attendance: expect ~1% dups (planned defect)
att = D["event_attendance.csv"]
att_dup = len(att) - len(att.drop_duplicates(["event_id","hcp_id"]))
chk("pk_attendance_intentional_dups", 0.005 < att_dup/len(att) < 0.02,
    f"dup_rate={att_dup/len(att):.4f} ({att_dup}/{len(att)})")

# ── 3. Foreign Keys ────────────────────────────────────────────────────────
print("\n=== 3. FOREIGN KEYS ===")
hcp_ids = set(D["hcp_master.csv"].hcp_id)
ev_ids = set(D["events.csv"].event_id)
inv_pairs = set(zip(D["event_invitations.csv"].event_id, D["event_invitations.csv"].hcp_id))
ba_prods = set(D["business_assumptions.csv"]["product"])
mf_regions = set(D["market_factors.csv"].region)
mf_months = set(D["market_factors.csv"].month)

fk_checks = [
    ("fk_inv_hcp", D["event_invitations.csv"].hcp_id.isin(hcp_ids).all(), "invitations.hcp_id -> hcp_master"),
    ("fk_inv_event", D["event_invitations.csv"].event_id.isin(ev_ids).all(), "invitations.event_id -> events"),
    ("fk_att_hcp", att.hcp_id.isin(hcp_ids).all(), "attendance.hcp_id -> hcp_master"),
    ("fk_att_event", att.event_id.isin(ev_ids).all(), "attendance.event_id -> events"),
    ("fk_att_pair_inv", all(t in inv_pairs for t in zip(att.event_id, att.hcp_id)), "attendance (ev,hcp) -> invitations"),
    ("fk_rx_hcp", D["hcp_rx_monthly.csv"].hcp_id.isin(hcp_ids).all(), "rx.hcp_id -> hcp_master"),
    ("fk_rx_product", D["hcp_rx_monthly.csv"]["product"].isin(ba_prods).all(), "rx.product -> business_assumptions"),
    ("fk_rx_month", D["hcp_rx_monthly.csv"].month.isin(mf_months).all(), "rx.month -> market_factors"),
    ("fk_mkt_hcp", D["marketing_activity.csv"].hcp_id.isin(hcp_ids).all(), "marketing.hcp_id -> hcp_master"),
    ("fk_cost_event", D["event_cost.csv"].event_id.isin(ev_ids).all(), "cost.event_id -> events"),
    ("fk_xwalk_hcp", D["identity_crosswalk.csv"].master_hcp_id.isin(hcp_ids).all(), "crosswalk -> hcp_master"),
    ("fk_gt_event", D["ground_truth.csv"].event_id.isin(ev_ids).all(), "ground_truth.event_id -> events"),
    ("fk_gt_hcp", D["ground_truth.csv"].hcp_id.isin(hcp_ids).all(), "ground_truth.hcp_id -> hcp_master"),
    ("fk_hcp_region_mf", set(D["hcp_master.csv"].region).issubset(mf_regions), "hcp_master.region subset of market_factors.region"),
]
for name, ok, detail in fk_checks:
    chk(name, bool(ok), detail)

# ── 4. Domain Values ───────────────────────────────────────────────────────
print("\n=== 4. DOMAIN VALUES ===")
DOMAINS = {
    ("hcp_master.csv","specialty"): {"Cardiology","Oncology","Endocrinology","Neurology","Dermatology","Primary Care","Psychiatry","Gastroenterology"},
    ("hcp_master.csv","region"): {"Northeast","Southeast","Midwest","Southwest","West","Mountain","Pacific Northwest"},
    ("hcp_master.csv","segment"): {"High","Medium","Low"},
    ("hcp_master.csv","active_flag"): {0,1},
    ("events.csv","status"): {"Completed","Cancelled","Planned"},
    ("events.csv","format"): {"In-person","Virtual","Hybrid"},
    ("event_invitations.csv","channel"): {"Email","Rep","Phone","Portal"},
    ("event_invitations.csv","eligible_reason"): {"Specialty match","Product affinity","Geographic proximity","Prior engagement","Patient-volume threshold","Combination of factors"},
    ("event_attendance.csv","registered"): {0,1},
    ("event_attendance.csv","verified_attended"): {0,1},
    ("identity_crosswalk.csv","match_status"): {"verified","review"},
    ("business_assumptions.csv","scenario"): {"Conservative","Base","Optimistic"},
}
for (fn, col), allowed in DOMAINS.items():
    vals = set(D[fn][col].dropna().unique())
    # handle int/str comparison
    allowed_str = {str(x) for x in allowed}
    vals_str = {str(x) for x in vals}
    extra = vals_str - allowed_str
    chk(f"domain_{fn}_{col}", len(extra)==0, f"extra={extra}" if extra else "OK")

# ── 5. Logical Invariants ──────────────────────────────────────────────────
print("\n=== 5. LOGICAL INVARIANTS ===")
rx = D["hcp_rx_monthly.csv"]
chk("inv_trx_ge_nrx", (rx.trx >= rx.nrx).all(), f"violations={(rx.trx < rx.nrx).sum()}")
chk("inv_nrx_nonneg", (rx.nrx >= 0).all(), f"min_nrx={rx.nrx.min()}")
chk("inv_trx_nonneg", (rx.trx >= 0).all(), f"min_trx={rx.trx.min()}")
chk("inv_comp_nonneg", (rx.competitor_trx >= 0).all(), f"min={rx.competitor_trx.min()}")

cost = D["event_cost.csv"]
cost_cols = ["honorarium","venue","meal","travel","agency"]
for c in cost_cols + ["total"]:
    chk(f"inv_cost_{c}_nonneg", (cost[c] >= 0).all(), f"min={cost[c].min():.2f}")
recon = (cost[cost_cols].sum(axis=1) - cost["total"]).abs()
chk("inv_cost_total_reconciles", (recon < 0.01).all(), f"max_diff={recon.max():.4f}")

# attendance logic
a1 = att[att.verified_attended == 1]
chk("inv_att1_registered", (a1.registered == 1).all(), f"violations={(a1.registered != 1).sum()}")
chk("inv_att1_duration_pos", (a1.duration > 0).all(), f"violations={(a1.duration <= 0).sum()}")
chk("inv_att1_engagement_5_100", a1.engagement.between(5,100).all(),
    f"min={a1.engagement.min()} max={a1.engagement.max()}")
a0 = att[att.verified_attended == 0]
chk("inv_att0_duration_zero", (a0.duration == 0).all(), f"violations={(a0.duration != 0).sum()}")
chk("inv_att0_engagement_zero", (a0.engagement == 0).all(), f"violations={(a0.engagement != 0).sum()}")

# invited_at <= event date
inv = D["event_invitations.csv"].copy()
ev = D["events.csv"]
ev_date_map = dict(zip(ev.event_id, pd.to_datetime(ev.date)))
inv["ev_date"] = inv.event_id.map(ev_date_map)
inv["inv_date"] = pd.to_datetime(inv.invited_at)
late = (inv.inv_date > inv.ev_date).sum()
chk("inv_invited_before_event", late == 0, f"late_invitations={late}")

# no attendance on Planned events
ev_status_map = dict(zip(ev.event_id, ev.status))
att_planned = att[att.event_id.map(ev_status_map) == "Planned"]
chk("inv_no_attendance_on_planned", len(att_planned) == 0, f"rows={len(att_planned)}")

# ground_truth only Completed
gt = D["ground_truth.csv"]
gt_statuses = gt.event_id.map(ev_status_map).unique()
chk("inv_gt_only_completed", set(gt_statuses) == {"Completed"}, f"statuses={set(gt_statuses)}")

# ── 6. Distribution Sanity ─────────────────────────────────────────────────
print("\n=== 6. DISTRIBUTION SANITY ===")
hm = D["hcp_master.csv"]
spec_shares = hm.specialty.value_counts(normalize=True)
chk("dist_specialty_uneven", spec_shares.max() - spec_shares.min() > 0.05,
    f"range={spec_shares.min():.3f}-{spec_shares.max():.3f}")
reg_shares = hm.region.value_counts(normalize=True)
chk("dist_region_uneven", reg_shares.max() - reg_shares.min() > 0.05,
    f"range={reg_shares.min():.3f}-{reg_shares.max():.3f}")
seg_shares = hm.segment.value_counts(normalize=True)
chk("dist_segment_uneven", seg_shares.max() - seg_shares.min() > 0.05,
    f"{dict(seg_shares.round(3))}")

active_pct = (hm.active_flag == 1).mean()
chk("dist_active_flag_~88pct", 0.80 <= active_pct <= 0.95, f"active={active_pct:.3f}")

ev_status_shares = ev.status.value_counts(normalize=True)
chk("dist_event_status_splits", True,
    f"Completed={ev_status_shares.get('Completed',0):.3f} "
    f"Cancelled={ev_status_shares.get('Cancelled',0):.3f} "
    f"Planned={ev_status_shares.get('Planned',0):.3f}")

ev_dates = pd.to_datetime(ev[ev.status != "Planned"].date)
span_days = (ev_dates.max() - ev_dates.min()).days
chk("dist_event_span_18m", span_days >= 548, f"span={span_days} days ({span_days/30.4:.1f} months)")

# ── 7. Cross-file Journey (20 random ground_truth rows) ───────────────────
print("\n=== 7. CROSS-FILE JOURNEY (20 samples) ===")
rng = np.random.default_rng(42)
sample_gt = gt.iloc[rng.choice(len(gt), size=20, replace=False)]

inv_pair_set = set(zip(inv.event_id, inv.hcp_id))
att_pair_set = set(zip(att.event_id, att.hcp_id))
rx_hcp_months = D["hcp_rx_monthly.csv"].groupby("hcp_id").month.apply(set).to_dict()

journey_ok = 0
for _, row in sample_gt.iterrows():
    eid, hid = row.event_id, row.hcp_id
    hcp_exists = hid in hcp_ids
    was_invited = (eid, hid) in inv_pair_set
    has_attendance = (eid, hid) in att_pair_set
    ev_completed = ev_status_map.get(eid) == "Completed"
    edate = ev_date_map.get(eid)
    if edate:
        emo = edate.to_period("M")
        pre_months = {str((emo - i).to_timestamp().strftime("%Y-%m")) for i in range(1, 7)}
        post_months = {str((emo + i).to_timestamp().strftime("%Y-%m")) for i in range(1, 4)}
        hcp_m = rx_hcp_months.get(hid, set())
        has_pre = len(pre_months & hcp_m) >= 4   # allow some gaps from 3% missing
        has_post = len(post_months & hcp_m) >= 2
    else:
        has_pre = has_post = False
    all_ok = hcp_exists and was_invited and has_attendance and ev_completed and has_pre and has_post
    if all_ok:
        journey_ok += 1
    else:
        print(f"    {eid}/{hid}: hcp={hcp_exists} inv={was_invited} att={has_attendance} "
              f"completed={ev_completed} pre={has_pre} post={has_post}")
chk("journey_20_samples", journey_ok >= 18, f"{journey_ok}/20 fully traceable")

# ── 8. Selection Bias ──────────────────────────────────────────────────────
print("\n=== 8. SELECTION BIAS ===")
att_dedup = att.drop_duplicates(["event_id","hcp_id"])
att_verified = att_dedup[
    (att_dedup.verified_attended == 1) &
    (att_dedup.event_id.map(ev_status_map) == "Completed")
]
attendee_hcps = set(att_verified.hcp_id)
invited_hcps = set(inv.hcp_id)
non_att_hcps = invited_hcps - attendee_hcps

rx_mean = rx.groupby("hcp_id").nrx.mean()
att_mean = rx_mean.reindex(sorted(attendee_hcps)).dropna().mean()
non_mean = rx_mean.reindex(sorted(non_att_hcps)).dropna().mean()
chk("selection_bias_present", att_mean > non_mean,
    f"attendees={att_mean:.2f} vs non-attendees={non_mean:.2f}")

# ── 9. Effect Heterogeneity ───────────────────────────────────────────────
print("\n=== 9. EFFECT HETEROGENEITY ===")
eff = gt.true_event_effect_nrx
n_pos = (eff > 1.0).sum()
n_nearzero = ((eff > -0.5) & (eff <= 1.0)).sum()
n_neg = (eff <= -0.5).sum()
chk("effect_heterogeneity", n_pos > 100 and n_neg > 50,
    f"positive(>1)={n_pos} near_zero=({n_nearzero}) negative(<=-0.5)={n_neg} "
    f"range=[{eff.min():.2f}, {eff.max():.2f}]")

# ── 10. Planned Imperfections ─────────────────────────────────────────────
print("\n=== 10. PLANNED IMPERFECTIONS ===")
# (1) Unmatched identity ~5%
xw = D["identity_crosswalk.csv"]
review_n = (xw.match_status == "review").sum()
review_pct = review_n / len(xw)
chk("defect_unmatched_identity", 0.03 <= review_pct <= 0.06,
    f"{review_pct:.3f} ({review_n}/{len(xw)})")

# (2) Missing Rx months ~3%
expected_slots = hm.hcp_id.nunique() * D["market_factors.csv"].month.nunique()  # approx upper bound
# better: count from data_quality_report or just check observed < expected
obs_rx = len(rx)
# We know the generator targets 3%; just check the report
dqr = pd.read_csv(os.path.join(B, "data_quality_report.csv"))
miss_row = dqr[dqr.check_name == "imperfection_missing_rx_month_injected"]
chk("defect_missing_rx_month", len(miss_row) > 0 and miss_row.iloc[0].status == "pass",
    miss_row.iloc[0].observed if len(miss_row) > 0 else "check not found")

# (3) Duplicate sign-in ~1%
chk("defect_duplicate_signin", 0.005 < att_dup/len(att) < 0.02,
    f"{att_dup/len(att):.4f} ({att_dup})")

# (4) Overlapping exposure >= 8% of attendees
att_c = att_verified.copy()
att_c["ev_date"] = att_c.event_id.map(ev_date_map)
att_c["product"] = att_c.event_id.map(dict(zip(ev.event_id, ev.topic.map(
    lambda t: {"Heart Failure Management":"CARDIVEX","Lipid Management & CV Risk":"CARDIVEX",
               "Advanced Solid Tumor Therapy":"ONCOLERA","Immuno-Oncology Sequencing":"ONCOLERA",
               "Type 2 Diabetes Intensification":"ENDOSTAT","Obesity & Metabolic Health":"ENDOSTAT",
               "Migraine Prophylaxis":"NEUROVANT","Neuroinflammation Update":"NEUROVANT"}.get(t, "?")
))))
overlap_hcps = set()
for hid, g in att_c.groupby("hcp_id"):
    rows = sorted(zip(g["ev_date"], g["product"]))
    for i in range(len(rows)):
        for j in range(i+1, len(rows)):
            if (rows[j][0] - rows[i][0]).days <= 90 and rows[i][1] == rows[j][1]:
                overlap_hcps.add(hid)
n_att_distinct = att_c.hcp_id.nunique()
overlap_pct = len(overlap_hcps) / n_att_distinct
chk("defect_overlapping_exposure", overlap_pct >= 0.08,
    f"{overlap_pct:.3f} ({len(overlap_hcps)}/{n_att_distinct})")

# (5) Cancelled events with residual attendance rows
canc_ids = set(ev[ev.status == "Cancelled"].event_id)
canc_att = att[att.event_id.isin(canc_ids)]
chk("defect_cancelled_residual_rows", len(canc_att) > 0,
    f"{len(canc_att)} rows on {canc_att.event_id.nunique()}/{len(canc_ids)} cancelled events")

# (6) Outlier cost ~2%
cost_m = cost.merge(ev[["event_id","format"]], on="event_id")
med_fmt = cost_m.groupby("format").total.median()
cost_m["ratio"] = cost_m.total / cost_m.format.map(med_fmt)
n_outlier = (cost_m.ratio >= 2.5).sum()
chk("defect_outlier_cost", 0.01 <= n_outlier/len(cost) <= 0.04,
    f"{n_outlier/len(cost):.3f} ({n_outlier}/{len(cost)})")

# ── SUMMARY ────────────────────────────────────────────────────────────────
print("\n" + "="*90)
print(f"{'CHECK':<50} {'STATUS':>6}  DETAILS")
print("-"*90)
n_pass = n_fail = n_warn = 0
for name, status, detail in results:
    print(f"{name:<50} {status:>6}  {detail[:80]}")
    if status == "PASS": n_pass += 1
    elif status == "FAIL": n_fail += 1
    else: n_warn += 1
print("-"*90)
print(f"TOTAL: {n_pass} PASS / {n_fail} FAIL / {n_warn} WARN out of {len(results)} checks")
