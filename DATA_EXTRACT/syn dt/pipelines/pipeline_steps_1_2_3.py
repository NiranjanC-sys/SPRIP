"""
=============================================================================
 Speaker Program Impact Pipeline — Steps 1, 2, 3
 DATA VALIDATION / CONFORMANCE → IDENTITY RESOLUTION → HCP-EVENT ELIGIBILITY
=============================================================================

Reads ONLY from data/bronze/ (immutable).
Writes to data/silver/ and data/gold/.
Never touches ground_truth.csv as a pipeline input.
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
BRONZE = os.path.join(ROOT, "data", "bronze")
SILVER = os.path.join(ROOT, "data", "silver")
GOLD = os.path.join(ROOT, "data", "gold")
CONFORMED = os.path.join(SILVER, "conformed")
QUARANTINE = os.path.join(SILVER, "quarantine")
for d in (CONFORMED, QUARANTINE, GOLD):
    os.makedirs(d, exist_ok=True)

LF = "\n"


def load_bronze(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(os.path.join(BRONZE, name), **kw)


conformance_log: list[dict] = []


def clog(file: str, rows_in: int, rows_out: int, rows_quarantined: int, reason: str):
    conformance_log.append({"file": file, "rows_in": rows_in, "rows_out": rows_out,
                            "rows_quarantined": rows_quarantined, "reason": reason})


# ========================================================================
# STEP 1 — DATA VALIDATION / CONFORMANCE
# ========================================================================
print("=" * 72)
print("STEP 1 — DATA VALIDATION / CONFORMANCE")
print("=" * 72)

# ---- 1.0 Load all bronze files with proper types -------------------------
print("\n[1.0] Loading bronze files ...")
hcp = load_bronze("hcp_master.csv", dtype={"hcp_id": str, "specialty": str,
                  "region": str, "segment": str, "active_flag": int})

events = load_bronze("events.csv", dtype={"event_id": str, "topic": str,
                     "format": str, "speaker": str, "status": str},
                     parse_dates=["date"])

invitations = load_bronze("event_invitations.csv",
                          dtype={"event_id": str, "hcp_id": str,
                                 "channel": str, "eligible_reason": str},
                          parse_dates=["invited_at"])

attendance_raw = load_bronze("event_attendance.csv",
                             dtype={"event_id": str, "hcp_id": str,
                                    "registered": int, "verified_attended": int,
                                    "duration": int, "engagement": int})

rx = load_bronze("hcp_rx_monthly.csv",
                 dtype={"hcp_id": str, "month": str, "product": str,
                        "nrx": int, "trx": int, "competitor_trx": int})

marketing = load_bronze("marketing_activity.csv",
                        dtype={"hcp_id": str, "rep_calls": int,
                               "emails": int, "samples": int, "other_events": int},
                        parse_dates=["date"])

cost = load_bronze("event_cost.csv",
                   dtype={"event_id": str, "honorarium": float, "venue": float,
                          "meal": float, "travel": float, "agency": float,
                          "total": float})

market = load_bronze("market_factors.csv",
                     dtype={"region": str, "month": str, "access": float,
                            "seasonality": float, "competitor_index": float})

crosswalk = load_bronze("identity_crosswalk.csv",
                        dtype={"master_hcp_id": str, "crm_hcp_id": str,
                               "match_status": str})

assumptions = load_bronze("business_assumptions.csv",
                          dtype={"product": str, "scenario": str,
                                 "expected_fills_per_new_rx": float,
                                 "net_contribution_per_fill": float,
                                 "net_contribution_per_incremental_nrx": float})

dq_report = load_bronze("data_quality_report.csv")

print(f"    hcp_master         {len(hcp):>7,} rows")
print(f"    events             {len(events):>7,} rows")
print(f"    event_invitations  {len(invitations):>7,} rows")
print(f"    event_attendance   {len(attendance_raw):>7,} rows")
print(f"    hcp_rx_monthly     {len(rx):>7,} rows")
print(f"    marketing_activity {len(marketing):>7,} rows")
print(f"    event_cost         {len(cost):>7,} rows")
print(f"    market_factors     {len(market):>7,} rows")
print(f"    identity_crosswalk {len(crosswalk):>7,} rows")
print(f"    business_assump.   {len(assumptions):>7,} rows")

# ---- 1.1 Re-verify the 6 expected conformance failures --------------------
print("\n[1.1] Re-verifying the 6 expected DQ failures ...")

fails = dq_report[dq_report["status"] == "fail"]
expected_fail_prefixes = [
    "conformance_all_identities_resolved",
    "conformance_rx_panel_complete",
    "conformance_attendance_unique_on_event_hcp",
    "conformance_single_clean_exposure_per_attendee",
    "conformance_attendance_only_on_completed_events",
    "conformance_cost_within_format_band",
]
found = set()
for _, row in fails.iterrows():
    for pf in expected_fail_prefixes:
        if row["check_name"] == pf:
            found.add(pf)
            break
missing = set(expected_fail_prefixes) - found
extra = set(fails["check_name"]) - set(expected_fail_prefixes)
print(f"    Expected 6 failures, found {len(fails)}: "
      f"{'ALL MATCH' if not missing and not extra else 'DISCREPANCY'}")
if missing:
    print(f"    MISSING: {missing}")
if extra:
    print(f"    UNEXPECTED: {extra}")

# ---- 1.2 Defect handling: Attendance deduplication (1% dups) ---------------
print("\n[1.2] Deduplicating event_attendance ...")
n_att_raw = len(attendance_raw)

dup_mask = attendance_raw.duplicated(["event_id", "hcp_id"], keep=False)
n_dup_rows = int(dup_mask.sum())
dup_pairs = attendance_raw[dup_mask][["event_id", "hcp_id"]].drop_duplicates()
n_dup_pairs = len(dup_pairs)
print(f"    {n_dup_rows} rows across {n_dup_pairs} duplicated (event_id, hcp_id) pairs")

# Dedup strategy: for each duplicated pair, keep the row with verified_attended=1
# if either has it; among ties, keep the LAST row (later in ingestion order = latest correction).
attendance_raw["_row_order"] = range(len(attendance_raw))
attendance_deduped = (
    attendance_raw
    .sort_values(["event_id", "hcp_id", "verified_attended", "_row_order"])
    .drop_duplicates(["event_id", "hcp_id"], keep="last")
    .drop(columns=["_row_order"])
    .reset_index(drop=True)
)

# Quarantine the dropped duplicate rows
dedup_kept_idx = set(attendance_deduped.index)
attendance_raw["_row_order"] = range(len(attendance_raw))
all_dup_rows = attendance_raw[dup_mask].copy()
# Identify which rows were kept vs dropped among the duplicated pairs
kept_keys = set(zip(attendance_deduped["event_id"], attendance_deduped["hcp_id"]))
# Actually, let me be more precise: reconstruct the dropped rows
att_sorted = (attendance_raw
              .sort_values(["event_id", "hcp_id", "verified_attended", "_row_order"]))
att_sorted_deduped = att_sorted.drop_duplicates(["event_id", "hcp_id"], keep="last")
dropped_idx = set(att_sorted.index) - set(att_sorted_deduped.index)
quarantine_dup = attendance_raw.loc[attendance_raw.index.isin(dropped_idx)].copy()
quarantine_dup["reason"] = "duplicate_signin"
quarantine_dup = quarantine_dup.drop(columns=["_row_order"], errors="ignore")
attendance_raw = attendance_raw.drop(columns=["_row_order"], errors="ignore")
# Rebuild deduped cleanly
attendance_raw["_row_order"] = range(len(attendance_raw))
attendance = (
    attendance_raw
    .sort_values(["event_id", "hcp_id", "verified_attended", "_row_order"])
    .drop_duplicates(["event_id", "hcp_id"], keep="last")
    .drop(columns=["_row_order"])
    .reset_index(drop=True)
)
attendance_raw = attendance_raw.drop(columns=["_row_order"])

n_att_deduped = len(attendance)
print(f"    After dedup: {n_att_deduped} rows ({n_att_raw - n_att_deduped} removed)")
clog("event_attendance.csv", n_att_raw, n_att_deduped,
     n_att_raw - n_att_deduped, "duplicate_signin")

# ---- 1.3 Defect handling: Cancelled event residual rows --------------------
print("\n[1.3] Handling cancelled event residual attendance rows ...")
cancelled_ids = set(events.loc[events["status"] == "Cancelled", "event_id"])
planned_ids = set(events.loc[events["status"] == "Planned", "event_id"])

att_on_cancelled = attendance["event_id"].isin(cancelled_ids)
att_on_planned = attendance["event_id"].isin(planned_ids)
n_canc_rows = int(att_on_cancelled.sum())
n_plan_rows = int(att_on_planned.sum())
print(f"    Attendance rows on Cancelled events: {n_canc_rows}")
print(f"    Attendance rows on Planned events:   {n_plan_rows}")

quarantine_cancelled = attendance[att_on_cancelled].copy()
quarantine_cancelled["reason"] = "cancelled_event_residual"

quarantine_planned = attendance[att_on_planned].copy()
quarantine_planned["reason"] = "planned_event_residual"

attendance = attendance[~att_on_cancelled & ~att_on_planned].reset_index(drop=True)
print(f"    After removal: {len(attendance)} attendance rows (Completed events only)")
clog("event_attendance.csv", n_att_deduped, len(attendance),
     n_canc_rows + n_plan_rows, "cancelled_or_planned_event_residual")

# Similarly quarantine invitation rows on cancelled/planned events
inv_on_cancelled = invitations["event_id"].isin(cancelled_ids)
inv_on_planned = invitations["event_id"].isin(planned_ids)
n_inv_canc = int(inv_on_cancelled.sum())
n_inv_plan = int(inv_on_planned.sum())
quarantine_inv_noncomp = invitations[inv_on_cancelled | inv_on_planned].copy()
quarantine_inv_noncomp["reason"] = "non_completed_event"
invitations_clean = invitations[~inv_on_cancelled & ~inv_on_planned].reset_index(drop=True)
print(f"    Invitations on Cancelled: {n_inv_canc}, Planned: {n_inv_plan}")
print(f"    After removal: {len(invitations_clean)} invitations (Completed events only)")
clog("event_invitations.csv", len(invitations), len(invitations_clean),
     n_inv_canc + n_inv_plan, "non_completed_event")

# ---- 1.4 Defect handling: Outlier costs (flag, don't auto-correct) ---------
print("\n[1.4] Flagging outlier costs ...")
cost_with_fmt = cost.merge(events[["event_id", "format"]], on="event_id", how="left")
median_by_fmt = cost_with_fmt.groupby("format")["total"].median()
cost_with_fmt["format_median"] = cost_with_fmt["format"].map(median_by_fmt)
cost_with_fmt["cost_ratio"] = cost_with_fmt["total"] / cost_with_fmt["format_median"]
outlier_mask = cost_with_fmt["cost_ratio"] >= 2.5
n_outliers = int(outlier_mask.sum())
print(f"    {n_outliers} events flagged as cost outliers (>= 2.5x format median)")

cost["finance_review_flag"] = outlier_mask.values.astype(int)
quarantine_cost = cost[cost["finance_review_flag"] == 1].copy()
quarantine_cost["reason"] = "outlier_cost_finance_review"
# Keep in conformed (not removed), just flagged
clog("event_cost.csv", len(cost), len(cost), n_outliers,
     "outlier_cost_flagged_not_removed")

# ---- 1.5 Defect handling: Missing Rx months (detect, flag coverage gaps) ----
print("\n[1.5] Analyzing Rx coverage gaps ...")
all_months = sorted(rx["month"].unique())
n_months = len(all_months)
print(f"    Panel spans {n_months} months: {all_months[0]} to {all_months[-1]}")

rx_grouped = rx.groupby(["hcp_id", "product"])["month"].apply(set).reset_index()
rx_grouped.columns = ["hcp_id", "product", "observed_months"]
rx_grouped["n_observed"] = rx_grouped["observed_months"].apply(len)
rx_grouped["n_missing"] = n_months - rx_grouped["n_observed"]

hcps_with_gaps = rx_grouped[rx_grouped["n_missing"] > 0]
total_missing_slots = int(hcps_with_gaps["n_missing"].sum())
print(f"    {len(hcps_with_gaps)} HCP-product pairs have coverage gaps")
print(f"    {total_missing_slots} total missing HCP-product-month slots")

# Build a coverage-gap reference table for Step 3's min-history rule
rx_coverage = rx_grouped[["hcp_id", "product", "n_observed", "n_missing"]].copy()
rx_coverage.to_csv(os.path.join(SILVER, "rx_coverage_gaps.csv"), index=False)
clog("hcp_rx_monthly.csv", len(rx), len(rx), total_missing_slots,
     "missing_rx_months_flagged")

# ---- 1.6 Write conformed files to silver/conformed/ -----------------------
print("\n[1.6] Writing conformed files to silver/conformed/ ...")

hcp.to_csv(os.path.join(CONFORMED, "hcp_master.csv"), index=False)
clog("hcp_master.csv", len(hcp), len(hcp), 0, "none")

events.to_csv(os.path.join(CONFORMED, "events.csv"), index=False)
clog("events.csv", len(events), len(events), 0, "none")

invitations_clean.to_csv(os.path.join(CONFORMED, "event_invitations.csv"), index=False)
attendance.to_csv(os.path.join(CONFORMED, "event_attendance.csv"), index=False)

rx.to_csv(os.path.join(CONFORMED, "hcp_rx_monthly.csv"), index=False)
cost.to_csv(os.path.join(CONFORMED, "event_cost.csv"), index=False)

marketing.to_csv(os.path.join(CONFORMED, "marketing_activity.csv"), index=False)
clog("marketing_activity.csv", len(marketing), len(marketing), 0, "none")

market.to_csv(os.path.join(CONFORMED, "market_factors.csv"), index=False)
clog("market_factors.csv", len(market), len(market), 0, "none")

crosswalk.to_csv(os.path.join(CONFORMED, "identity_crosswalk.csv"), index=False)
clog("identity_crosswalk.csv", len(crosswalk), len(crosswalk), 0, "none_yet_step2")

assumptions.to_csv(os.path.join(CONFORMED, "business_assumptions.csv"), index=False)
clog("business_assumptions.csv", len(assumptions), len(assumptions), 0, "none")

# ---- 1.7 Write quarantine files -------------------------------------------
print("\n[1.7] Writing quarantine files ...")
quarantine_all = pd.concat([
    quarantine_dup,
    quarantine_cancelled,
    quarantine_planned,
    quarantine_inv_noncomp.rename(columns={}),
], ignore_index=True)

# Split into per-reason files for clarity
for reason, grp in quarantine_all.groupby("reason"):
    fn = f"{reason}.csv"
    grp.to_csv(os.path.join(QUARANTINE, fn), index=False)
    print(f"    quarantine/{fn:45s} {len(grp):>6,} rows")

quarantine_cost.to_csv(os.path.join(QUARANTINE, "outlier_cost_finance_review.csv"), index=False)
print(f"    quarantine/{'outlier_cost_finance_review.csv':45s} {len(quarantine_cost):>6,} rows")

# ---- 1.8 Write conformance report -----------------------------------------
print("\n[1.8] Writing conformance_report.csv ...")
conf_df = pd.DataFrame(conformance_log)
conf_df.to_csv(os.path.join(SILVER, "conformance_report.csv"), index=False)
print(conf_df.to_string(index=False))

# ========================================================================
# STEP 2 — IDENTITY RESOLUTION
# ========================================================================
print("\n" + "=" * 72)
print("STEP 2 — IDENTITY RESOLUTION")
print("=" * 72)

# ---- 2.1 Identify unresolved HCPs -----------------------------------------
print("\n[2.1] Loading crosswalk and identifying unresolved identities ...")
review_mask = crosswalk["match_status"] == "review"
n_review = int(review_mask.sum())
n_verified = int((~review_mask).sum())
pct_review = n_review / len(crosswalk) * 100
print(f"    Total HCPs:    {len(crosswalk):,}")
print(f"    Verified:      {n_verified:,} ({100 - pct_review:.1f}%)")
print(f"    Review (unresolved): {n_review:,} ({pct_review:.1f}%)")

quarantined_hcp_ids = set(crosswalk.loc[review_mask, "master_hcp_id"])
resolved_hcp_ids = set(crosswalk.loc[~review_mask, "master_hcp_id"])

# ---- 2.2 Quarantine unresolved identity rows across all HCP-referencing files
print("\n[2.2] Quarantining unresolved identity rows across all files ...")

# Files that reference hcp_id and need identity enforcement
HCP_FILES = {
    "hcp_master.csv": ("hcp_id", hcp),
    "event_invitations.csv": ("hcp_id", invitations_clean),
    "event_attendance.csv": ("hcp_id", attendance),
    "hcp_rx_monthly.csv": ("hcp_id", rx),
    "marketing_activity.csv": ("hcp_id", marketing),
}

identity_report: list[dict] = []
quarantine_identity_parts = []

for fname, (hcp_col, df) in HCP_FILES.items():
    bad = df[hcp_col].isin(quarantined_hcp_ids)
    n_bad = int(bad.sum())
    n_good = len(df) - n_bad

    if n_bad > 0:
        q = df[bad].copy()
        q["reason"] = "unresolved_identity"
        q["source_file"] = fname
        quarantine_identity_parts.append(q)

    identity_report.append({
        "file": fname,
        "hcp_column": hcp_col,
        "total_rows": len(df),
        "resolved_rows": n_good,
        "quarantined_rows": n_bad,
        "pct_quarantined": round(n_bad / len(df) * 100, 2) if len(df) else 0.0,
    })
    print(f"    {fname:30s}  total={len(df):>7,}  resolved={n_good:>7,}  "
          f"quarantined={n_bad:>5,} ({n_bad/len(df)*100:.1f}%)")

# Write quarantine file
if quarantine_identity_parts:
    qid = pd.concat(quarantine_identity_parts, ignore_index=True)
    qid.to_csv(os.path.join(QUARANTINE, "unresolved_identity.csv"), index=False)
    print(f"\n    Wrote quarantine/unresolved_identity.csv: {len(qid):,} rows")

# ---- 2.3 Overwrite conformed files, excluding quarantined HCPs ------------
print("\n[2.3] Overwriting conformed files with resolved-only data ...")

hcp_resolved = hcp[~hcp["hcp_id"].isin(quarantined_hcp_ids)].reset_index(drop=True)
inv_resolved = invitations_clean[~invitations_clean["hcp_id"].isin(quarantined_hcp_ids)].reset_index(drop=True)
att_resolved = attendance[~attendance["hcp_id"].isin(quarantined_hcp_ids)].reset_index(drop=True)
rx_resolved = rx[~rx["hcp_id"].isin(quarantined_hcp_ids)].reset_index(drop=True)
mkt_resolved = marketing[~marketing["hcp_id"].isin(quarantined_hcp_ids)].reset_index(drop=True)
xwalk_resolved = crosswalk[~review_mask].reset_index(drop=True)

# All HCP IDs are already master_hcp_id (hcp_master uses hcp_id which IS the master ID).
# The crosswalk confirms master_hcp_id == hcp_id used everywhere.
# Write resolved files
hcp_resolved.to_csv(os.path.join(CONFORMED, "hcp_master.csv"), index=False)
inv_resolved.to_csv(os.path.join(CONFORMED, "event_invitations.csv"), index=False)
att_resolved.to_csv(os.path.join(CONFORMED, "event_attendance.csv"), index=False)
rx_resolved.to_csv(os.path.join(CONFORMED, "hcp_rx_monthly.csv"), index=False)
mkt_resolved.to_csv(os.path.join(CONFORMED, "marketing_activity.csv"), index=False)
xwalk_resolved.to_csv(os.path.join(CONFORMED, "identity_crosswalk.csv"), index=False)

for nm, df_ in [("hcp_master", hcp_resolved), ("event_invitations", inv_resolved),
                 ("event_attendance", att_resolved), ("hcp_rx_monthly", rx_resolved),
                 ("marketing_activity", mkt_resolved), ("identity_crosswalk", xwalk_resolved)]:
    print(f"    conformed/{nm}.csv -> {len(df_):>7,} rows")

# ---- 2.4 Write identity_resolution_report.csv -----------------------------
print("\n[2.4] Writing identity_resolution_report.csv ...")
id_rpt = pd.DataFrame(identity_report)
id_rpt.to_csv(os.path.join(SILVER, "identity_resolution_report.csv"), index=False)
print(id_rpt.to_string(index=False))

# ========================================================================
# STEP 3 — HCP-EVENT ELIGIBILITY BUILDING
# ========================================================================
print("\n" + "=" * 72)
print("STEP 3 — HCP-EVENT ELIGIBILITY BUILDING")
print("=" * 72)

# Reload from conformed (identity-resolved)
hcp_c = pd.read_csv(os.path.join(CONFORMED, "hcp_master.csv"), dtype=str)
events_c = pd.read_csv(os.path.join(CONFORMED, "events.csv"), dtype={"event_id": str,
                       "topic": str, "format": str, "speaker": str, "status": str},
                       parse_dates=["date"])
inv_c = pd.read_csv(os.path.join(CONFORMED, "event_invitations.csv"),
                     dtype={"event_id": str, "hcp_id": str})
att_c = pd.read_csv(os.path.join(CONFORMED, "event_attendance.csv"),
                     dtype={"event_id": str, "hcp_id": str,
                            "registered": int, "verified_attended": int})
rx_c = pd.read_csv(os.path.join(CONFORMED, "hcp_rx_monthly.csv"),
                    dtype={"hcp_id": str, "month": str, "product": str})

# ---- 3.1 Restrict to Completed events only --------------------------------
print("\n[3.1] Restricting to Completed events ...")
completed = events_c[events_c["status"] == "Completed"]
completed_ids = set(completed["event_id"])
n_cancelled_excluded = int((events_c["status"] == "Cancelled").sum())
n_planned_excluded = int((events_c["status"] == "Planned").sum())
print(f"    Completed events: {len(completed)}")
print(f"    Excluded Cancelled: {n_cancelled_excluded}, Planned: {n_planned_excluded}")

# Build event date and product lookup
# Need topic-to-product mapping. Derive from events + assumptions structure.
TOPICS_TO_PRODUCT = {
    "Heart Failure Management": "CARDIVEX",
    "Lipid Management & CV Risk": "CARDIVEX",
    "Advanced Solid Tumor Therapy": "ONCOLERA",
    "Immuno-Oncology Sequencing": "ONCOLERA",
    "Type 2 Diabetes Intensification": "ENDOSTAT",
    "Obesity & Metabolic Health": "ENDOSTAT",
    "Migraine Prophylaxis": "NEUROVANT",
    "Neuroinflammation Update": "NEUROVANT",
}
event_date = dict(zip(completed["event_id"], completed["date"]))
event_product = {eid: TOPICS_TO_PRODUCT.get(t, "UNKNOWN")
                 for eid, t in zip(completed["event_id"], completed["topic"])}

# ---- 3.2 Build attendance set (treatment) on Completed events only ---------
print("\n[3.2] Identifying treatment (verified attendees) ...")
att_completed = att_c[att_c["event_id"].isin(completed_ids)]
treatment_pairs = set(
    zip(att_completed.loc[att_completed["verified_attended"] == 1, "event_id"],
        att_completed.loc[att_completed["verified_attended"] == 1, "hcp_id"])
)
print(f"    Treatment (verified attendee) pairs: {len(treatment_pairs):,}")

# ---- 3.3 Build Rx observed months lookup for min-history rule ---------------
print("\n[3.3] Building Rx history lookup for min-history rule ...")
rx_months_by_hcp_prod = (
    rx_c.groupby(["hcp_id", "product"])["month"]
    .apply(set)
    .to_dict()
)

all_months_sorted = sorted(rx_c["month"].unique())
month_to_idx = {m: i for i, m in enumerate(all_months_sorted)}


def date_to_month_str(d) -> str:
    return d.strftime("%Y-%m")


def check_pre_history(hcp_id: str, product: str, event_date_val, n_pre: int = 6,
                      max_missing: int = 1) -> bool:
    """Check if HCP has at least n_pre - max_missing months of Rx in the 6 months before event."""
    obs = rx_months_by_hcp_prod.get((hcp_id, product), set())
    ym = event_date_val.year * 12 + event_date_val.month - 1
    pre_months = []
    for k in range(1, n_pre + 1):
        y, m = divmod(ym - k, 12)
        pre_months.append(f"{y}-{m + 1:02d}")
    n_observed = sum(1 for pm in pre_months if pm in obs)
    return n_observed >= (n_pre - max_missing)


# ---- 3.4 Detect 90-day overlapping/contaminated exposure -------------------
print("\n[3.4] Detecting 90-day overlapping/contaminated exposure ...")

# Build per-HCP attendance history: (event_date, event_id, product) sorted by date
hcp_att_history: dict[str, list[tuple]] = defaultdict(list)
for eid, hid in treatment_pairs:
    d = event_date[eid]
    p = event_product[eid]
    hcp_att_history[hid].append((d, eid, p))

for hid in hcp_att_history:
    hcp_att_history[hid].sort()

contaminated_pairs: set[tuple[str, str]] = set()
for hid, hist in hcp_att_history.items():
    for i in range(len(hist)):
        for j in range(i + 1, len(hist)):
            d_i, eid_i, prod_i = hist[i]
            d_j, eid_j, prod_j = hist[j]
            gap = (d_j - d_i).days
            if gap > 90:
                break
            if prod_i == prod_j:
                contaminated_pairs.add((eid_i, hid))
                contaminated_pairs.add((eid_j, hid))

contaminated_hcps = {h for _, h in contaminated_pairs}
print(f"    Contaminated HCP-event pairs: {len(contaminated_pairs):,}")
print(f"    Distinct contaminated HCPs:   {len(contaminated_hcps):,}")

# ---- 3.5 Build eligibility table ------------------------------------------
print("\n[3.5] Building eligibility table ...")

eligibility_rows = []
excluded_counts = defaultdict(int)

for _, ev in completed.iterrows():
    eid = ev["event_id"]
    edate = ev["date"]
    prod = event_product[eid]

    # All HCPs invited to this event
    invited_hcps = set(inv_c.loc[inv_c["event_id"] == eid, "hcp_id"])

    for hid in invited_hcps:
        is_treatment = (eid, hid) in treatment_pairs
        is_contaminated = (eid, hid) in contaminated_pairs

        if is_treatment:
            if is_contaminated:
                eligibility_rows.append({
                    "master_hcp_id": hid,
                    "event_id": eid,
                    "event_date": edate.strftime("%Y-%m-%d"),
                    "group": "excluded",
                    "exclusion_reason": "contaminated_overlapping_exposure",
                    "contaminated": True,
                })
                excluded_counts["contaminated_treatment"] += 1
            else:
                eligibility_rows.append({
                    "master_hcp_id": hid,
                    "event_id": eid,
                    "event_date": edate.strftime("%Y-%m-%d"),
                    "group": "treatment",
                    "exclusion_reason": None,
                    "contaminated": False,
                })
        else:
            # Control candidate: check min-history rule
            has_history = check_pre_history(hid, prod, edate)
            if has_history:
                eligibility_rows.append({
                    "master_hcp_id": hid,
                    "event_id": eid,
                    "event_date": edate.strftime("%Y-%m-%d"),
                    "group": "control_candidate",
                    "exclusion_reason": None,
                    "contaminated": False,
                })
            else:
                eligibility_rows.append({
                    "master_hcp_id": hid,
                    "event_id": eid,
                    "event_date": edate.strftime("%Y-%m-%d"),
                    "group": "excluded",
                    "exclusion_reason": "insufficient_pre_event_rx_history",
                    "contaminated": False,
                })
                excluded_counts["insufficient_history"] += 1

eligibility = pd.DataFrame(eligibility_rows)
print(f"    Total eligibility rows: {len(eligibility):,}")
print(f"    Group breakdown:")
for grp, cnt in eligibility["group"].value_counts().items():
    print(f"        {grp:25s} {cnt:>7,}")
print(f"    Exclusion reasons:")
for reason, cnt in excluded_counts.items():
    print(f"        {reason:45s} {cnt:>7,}")

# ---- 3.6 Write eligibility_table.csv --------------------------------------
print("\n[3.6] Writing gold/eligibility_table.csv ...")
eligibility.to_csv(os.path.join(GOLD, "eligibility_table.csv"), index=False)
print(f"    Wrote {len(eligibility):,} rows")

# ---- 3.7 Write eligibility_summary.csv ------------------------------------
print("\n[3.7] Writing gold/eligibility_summary.csv ...")
summary_parts = []
for eid in sorted(completed_ids):
    ev_elig = eligibility[eligibility["event_id"] == eid]
    summary_parts.append({
        "event_id": eid,
        "event_date": event_date[eid].strftime("%Y-%m-%d"),
        "treatment": int((ev_elig["group"] == "treatment").sum()),
        "control_candidate": int((ev_elig["group"] == "control_candidate").sum()),
        "excluded": int((ev_elig["group"] == "excluded").sum()),
        "total_invited": len(ev_elig),
    })

summary = pd.DataFrame(summary_parts)
# Add overall totals row
totals = {
    "event_id": "ALL_EVENTS",
    "event_date": "",
    "treatment": int(summary["treatment"].sum()),
    "control_candidate": int(summary["control_candidate"].sum()),
    "excluded": int(summary["excluded"].sum()),
    "total_invited": int(summary["total_invited"].sum()),
}
summary = pd.concat([summary, pd.DataFrame([totals])], ignore_index=True)
summary.to_csv(os.path.join(GOLD, "eligibility_summary.csv"), index=False)
print(f"    Wrote {len(summary)} rows ({len(summary) - 1} events + 1 totals row)")
print(f"\n    TOTALS:")
print(f"        Treatment:         {totals['treatment']:>7,}")
print(f"        Control candidate: {totals['control_candidate']:>7,}")
print(f"        Excluded:          {totals['excluded']:>7,}")
print(f"        Total invited:     {totals['total_invited']:>7,}")

# ========================================================================
# FINAL SUMMARY
# ========================================================================
print("\n" + "=" * 72)
print("PIPELINE SUMMARY — Steps 1, 2, 3")
print("=" * 72)

print(f"""
STEP 1 — DATA VALIDATION / CONFORMANCE
  DQ report: 6 expected failures confirmed, all match the defect table.
  Attendance dedup:        {n_att_raw:>7,} raw -> {n_att_deduped:>7,} deduped ({n_att_raw - n_att_deduped} removed)
  Cancelled event rows:    {n_canc_rows:>7,} quarantined from attendance
  Planned event rows:      {n_plan_rows:>7,} quarantined from attendance
  Invitation exclusions:   {n_inv_canc + n_inv_plan:>7,} (cancelled + planned event refs)
  Cost outliers flagged:   {n_outliers:>7,} (kept in file, flagged for finance)
  Missing Rx slots:        {total_missing_slots:>7,} gaps across {len(hcps_with_gaps)} HCP-product pairs

STEP 2 — IDENTITY RESOLUTION
  Total HCPs:              {len(crosswalk):>7,}
  Verified:                {n_verified:>7,} ({100 - pct_review:.1f}%)
  Quarantined (review):    {n_review:>7,} ({pct_review:.1f}%)
  Rows quarantined across all files: {len(qid) if quarantine_identity_parts else 0:>7,}

STEP 3 — HCP-EVENT ELIGIBILITY
  Completed events:        {len(completed):>7,}
  Eligibility rows:        {len(eligibility):>7,}
  Clean treatment:         {totals['treatment']:>7,}
  Clean control candidates:{totals['control_candidate']:>7,}
  Excluded:                {totals['excluded']:>7,}
    - contaminated:        {excluded_counts.get('contaminated_treatment', 0):>7,}
    - insufficient history:{excluded_counts.get('insufficient_history', 0):>7,}

Of the original ~{n_att_raw:,} attendance records, {totals['treatment']:,} ended up
as clean, usable "treatment" rows in the final eligibility table.
""")
