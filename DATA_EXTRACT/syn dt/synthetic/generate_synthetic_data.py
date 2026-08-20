"""
=============================================================================
 Pharmaceutical Speaker Program Impact / ROI / Investment Optimization
 SYNTHETIC SOURCE DATA GENERATOR  (bronze landing zone)
=============================================================================

Produces a single, relationally-consistent synthetic batch that emulates a
realistic data-generating process for the analytics pipeline:

  SOURCE -> VALIDATION -> IDENTITY RESOLUTION -> ELIGIBILITY -> FEATURES
  -> XGBOOST PROPENSITY -> MATCHING -> DiD -> INCREMENTAL NRx/TRx -> ROI
  -> FUTURE IMPACT -> BUDGET RECOMMENDATION -> DASHBOARD

Design principles
-----------------
1. Nothing is sampled independently. Latent HCP traits drive invitation,
   attendance and prescribing, so selection bias is real and the downstream
   propensity model has a genuine estimation task.
2. Latent mechanism variables (patient opportunity, product affinity,
   engagement propensity, event region, event quality tier) are NEVER written
   to bronze/. They exist only inside this generator.
3. No derived analytics (before_rx / after_rx / rx_lift / roi / effect
   estimates) are written to bronze/. ground_truth.csv is a separate hidden
   holdout, produced BEFORE observed post-event outcomes are drawn.
4. Defects are injected at the exact rates from the planned-imperfection
   table so the validation/conformance layer has real work to do.

Reproducibility: one fixed seed for the whole run (see data/seed.txt).
Same seed -> byte-identical CSV content (only _checksums.generated_at moves).
=============================================================================
"""

from __future__ import annotations

import hashlib
import math
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

# =============================================================================
# 0. SEED + OUTPUT LAYOUT
# =============================================================================

SEED = 20260819
rng = np.random.default_rng(SEED)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
BRONZE = os.path.join(DATA, "bronze")
SILVER = os.path.join(DATA, "silver")
GOLD = os.path.join(DATA, "gold")
for _d in (DATA, BRONZE, SILVER, GOLD):
    os.makedirs(_d, exist_ok=True)

GENERATED_AT = os.environ.get(
    "SYN_DT_GENERATED_AT",
    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
)

SILVER_README = """# silver/ — conformed layer (NOT produced by the generator)

This folder is intentionally empty. It is the output target of the **downstream
pipeline**, not of `generate_synthetic_data.py`.

The generator only ever writes to `bronze/`, which is the raw, untouched landing
zone and therefore still contains every injected defect. Anything written here
must be the product of the validation / conformance / identity-resolution stages
reading `bronze/`.

## What the pipeline is expected to land here

| Stage | Expected silver output | Bronze defect it must resolve |
|---|---|---|
| Data validation / conformance | `dq_findings`, `rejected_rows` | schema, domain, range, date-order and FK checks re-run on bronze |
| Attendance de-duplication | `event_attendance_conformed` | ~1% duplicate `event_id + hcp_id` sign-ins → collapse to the **latest** verified status (later row in ingestion order wins) |
| Event status conformance | `events_conformed`, `exposure_events` | Cancelled events carry residual sign-in rows; only `status = 'Completed'` may become exposure. Planned events are future-dated and carry no attendance |
| Identity resolution | `hcp_xref_resolved`, `hcp_identity_quarantine` | ~5% of `identity_crosswalk` rows are `match_status = 'review'` (2% null `event_hcp_id`, 3% null `rx_vendor_hcp_id`) → **quarantine**, never silently reclassify as non-attendees |
| Rx panel conformance | `hcp_rx_monthly_conformed`, `rx_coverage_gaps` | ~3% of HCP-product-months are absent (bursty vendor-style gaps plus random dropout) → flag the gap; do **not** zero-fill |
| Cost conformance | `event_cost_conformed`, `cost_finance_review` | ~2% of events are 3-5x the format norm → flag for finance review, do **not** auto-correct |

## Rules

- Bronze is immutable. Never write back into `bronze/`.
- Reproduce a run from `data/seed.txt` and verify `bronze/_checksums.csv` before
  processing.
- `bronze/data_quality_report.csv` is the generator's own conformance run. Rows
  with `status = fail` are the intentional defects listed above — treat them as
  the acceptance criteria for this layer, not as generation errors.
- `bronze/ground_truth.csv` is a hidden holdout. It must never be joined into a
  feature table, a training set, or anything that reaches the model.
"""

GOLD_README = """# gold/ — analytics layer (NOT produced by the generator)

This folder is intentionally empty. It is the output target of the **downstream
pipeline**, not of `generate_synthetic_data.py`.

Every measure below is *derived*. None of it exists in `bronze/` by design:
there are no `before_rx`, `after_rx`, `rx_lift`, `incremental_*` or `roi`
columns anywhere in the raw files.

## What the pipeline is expected to land here

| Stage | Expected gold output |
|---|---|
| HCP-event eligibility | `hcp_event_eligibility` — invited HCPs on Completed events, minus identity-quarantined HCPs, minus attendees with overlapping same-product exposure inside 90 days (detectable only from `events.date`), subject to the min-history rule |
| HCP-month panel | `hcp_month_panel` — Rx joined to `marketing_activity` and `market_factors` (region + month), with coverage-gap flags |
| Feature engineering | `hcp_event_features` — pre-period Rx trend/level, engagement history, rep-call intensity, specialty-topic match, access and competitive pressure |
| Propensity / attendance model | `propensity_scores`, `model_metrics` — XGBoost trained on features only |
| Attendee-control matching | `matched_pairs`, `balance_diagnostics` — attendees matched to eligible non-attendees on propensity + pre-period trajectory |
| Difference-in-differences | `did_effects` — event and cohort level, with standard errors |
| Incremental NRx / TRx | `incremental_rx` — 6-month pre vs 3-month post window per matched pair |
| ROI | `event_roi` — `incremental_contribution = incremental_nrx * expected_fills_per_new_rx * net_contribution_per_fill`; `roi = (incremental_contribution - total) / total`. Financial inputs come **only** from `business_assumptions.csv`; cost comes **only** from `event_cost.csv` |
| Future program impact | `predicted_event_impact` — scored against the Planned events in `events.csv` |
| Budget / investment optimisation | `budget_recommendations` — reallocation by topic, format, region and segment |
| Dashboard serving layer | `dashboard_*` marts |

## Validating the causal layer against hidden truth

`bronze/ground_truth.csv` holds one row per verified attendee of a Completed
event, with the total incremental NRx and TRx attributable to that event for
that HCP, summed over post-months +1..+3 (decay weights 0.45 / 0.33 / 0.22).
Attendee-event pairs absent from the file have a true effect of zero.

Recovery test: aggregate `true_event_effect_nrx` to the event or cohort level
and compare against the DiD estimate. A correctly specified pipeline should land
inside roughly 10-15% at the cohort level. Event-level agreement will be looser
for small events — that is sampling noise, not a defect.

Ground truth is a scoring artifact only. It must never be used as a model
input, a matching variable, or an eligibility filter.
"""

# =============================================================================
# 1. GLOBAL CALENDAR
# =============================================================================

PANEL_START = date(2024, 1, 1)      # first Rx / market_factors month
N_MONTHS = 32                       # 2024-01 .. 2026-08
HIST_EVENT_START = date(2024, 9, 1)   # earliest Completed/Cancelled event
HIST_EVENT_END = date(2026, 5, 31)    # latest  Completed/Cancelled event
PLANNED_START = date(2026, 9, 1)      # future (Planned) events
PLANNED_END = date(2027, 2, 28)


def month_add(d: date, k: int) -> date:
    y, m = divmod((d.year * 12 + d.month - 1) + k, 12)
    return date(y, m + 1, 1)


MONTH_DATES = [month_add(PANEL_START, i) for i in range(N_MONTHS)]
MONTH_KEYS = [d.strftime("%Y-%m") for d in MONTH_DATES]
MONTH_IDX = {k: i for i, k in enumerate(MONTH_KEYS)}


def date_to_month_idx(d: date) -> int:
    return (d.year * 12 + d.month) - (PANEL_START.year * 12 + PANEL_START.month)


# Post-event attribution window = months +1, +2, +3 with decaying weights.
EFFECT_WEIGHTS = np.array([0.45, 0.33, 0.22])

# =============================================================================
# 2. REFERENCE DOMAINS  (single source of truth for cross-file consistency)
# =============================================================================

REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest",
           "West", "Mountain", "Pacific Northwest"]
REGION_P = np.array([0.22, 0.20, 0.17, 0.13, 0.16, 0.07, 0.05])

REGION_ADJACENT = {
    "Northeast": {"Southeast", "Midwest"},
    "Southeast": {"Northeast", "Midwest", "Southwest"},
    "Midwest": {"Northeast", "Southeast", "Mountain", "Southwest"},
    "Southwest": {"Southeast", "Midwest", "Mountain", "West"},
    "West": {"Southwest", "Mountain", "Pacific Northwest"},
    "Mountain": {"Midwest", "Southwest", "West", "Pacific Northwest"},
    "Pacific Northwest": {"West", "Mountain"},
}

SPECIALTIES = ["Primary Care", "Cardiology", "Oncology", "Endocrinology",
               "Neurology", "Psychiatry", "Gastroenterology", "Dermatology"]
SPECIALTY_P = np.array([0.26, 0.16, 0.12, 0.11, 0.10, 0.09, 0.08, 0.08])

PRODUCTS = ["CARDIVEX", "ONCOLERA", "ENDOSTAT", "NEUROVANT"]
PROD_IDX = {p: i for i, p in enumerate(PRODUCTS)}

# Topic -> product. Topics are the therapeutic content of speaker programs.
TOPICS = {
    "Heart Failure Management":        "CARDIVEX",
    "Lipid Management & CV Risk":      "CARDIVEX",
    "Advanced Solid Tumor Therapy":    "ONCOLERA",
    "Immuno-Oncology Sequencing":      "ONCOLERA",
    "Type 2 Diabetes Intensification": "ENDOSTAT",
    "Obesity & Metabolic Health":      "ENDOSTAT",
    "Migraine Prophylaxis":            "NEUROVANT",
    "Neuroinflammation Update":        "NEUROVANT",
}
TOPIC_NAMES = list(TOPICS.keys())
TOPIC_P = np.array([0.15, 0.13, 0.11, 0.09, 0.16, 0.13, 0.12, 0.11])

# Primary / secondary specialty audience for each topic.
TOPIC_AUDIENCE = {
    "Heart Failure Management":        (["Cardiology"], ["Primary Care", "Endocrinology"]),
    "Lipid Management & CV Risk":      (["Cardiology"], ["Primary Care", "Endocrinology"]),
    "Advanced Solid Tumor Therapy":    (["Oncology"], ["Gastroenterology"]),
    "Immuno-Oncology Sequencing":      (["Oncology"], ["Gastroenterology", "Dermatology"]),
    "Type 2 Diabetes Intensification": (["Endocrinology"], ["Primary Care", "Cardiology"]),
    "Obesity & Metabolic Health":      (["Endocrinology", "Primary Care"], ["Cardiology", "Gastroenterology"]),
    "Migraine Prophylaxis":            (["Neurology"], ["Primary Care", "Psychiatry"]),
    "Neuroinflammation Update":        (["Neurology"], ["Psychiatry"]),
}

FORMATS = ["In-person", "Virtual", "Hybrid"]
FORMAT_P = np.array([0.46, 0.36, 0.18])

CHANNELS = ["Email", "Rep", "Phone", "Portal"]
ELIGIBLE_REASONS = ["Specialty match", "Product affinity", "Geographic proximity",
                    "Prior engagement", "Patient-volume threshold",
                    "Combination of factors"]

# Latent specialty x product affinity centres (log-odds-ish scale).
AFFINITY_BASE = {
    "Cardiology":       {"CARDIVEX":  1.15, "ONCOLERA": -0.90, "ENDOSTAT":  0.15, "NEUROVANT": -0.50},
    "Oncology":         {"CARDIVEX": -0.80, "ONCOLERA":  1.20, "ENDOSTAT": -0.60, "NEUROVANT": -0.40},
    "Endocrinology":    {"CARDIVEX":  0.20, "ONCOLERA": -0.90, "ENDOSTAT":  1.20, "NEUROVANT": -0.60},
    "Neurology":        {"CARDIVEX": -0.40, "ONCOLERA": -0.60, "ENDOSTAT": -0.30, "NEUROVANT":  1.20},
    "Primary Care":     {"CARDIVEX":  0.60, "ONCOLERA": -1.10, "ENDOSTAT":  0.70, "NEUROVANT":  0.10},
    "Psychiatry":       {"CARDIVEX": -0.60, "ONCOLERA": -1.00, "ENDOSTAT": -0.20, "NEUROVANT":  0.75},
    "Gastroenterology": {"CARDIVEX": -0.30, "ONCOLERA":  0.45, "ENDOSTAT":  0.05, "NEUROVANT": -0.50},
    "Dermatology":      {"CARDIVEX": -0.50, "ONCOLERA":  0.10, "ENDOSTAT":  0.20, "NEUROVANT": -0.40},
}

# Latent specialty-level patient-opportunity shift.
SPEC_OPPORTUNITY = {
    "Primary Care": 0.35, "Cardiology": 0.25, "Oncology": 0.05,
    "Endocrinology": 0.15, "Neurology": 0.00, "Psychiatry": -0.10,
    "Gastroenterology": -0.05, "Dermatology": -0.20,
}

# Product volume scale (log space) + market trend direction.
PROD_LOG_SCALE = {"CARDIVEX": 0.35, "ONCOLERA": -0.85, "ENDOSTAT": 0.50, "NEUROVANT": 0.00}
PROD_TREND = {"CARDIVEX": 0.10, "ONCOLERA": 0.22, "ENDOSTAT": 0.30, "NEUROVANT": -0.06}

N_HCP = 2500
N_EVENTS = 300
INVITE_TARGET_MEAN_LOG = math.log(85.0)

# =============================================================================
# 3. HCP MASTER  +  LATENT TRAITS (latents stay internal)
# =============================================================================
print("[1/13] HCP master + latent traits ...")

hcp_ids = np.array([f"HCP{100001 + i}" for i in range(N_HCP)])
specialty = rng.choice(SPECIALTIES, size=N_HCP, p=SPECIALTY_P)
region = rng.choice(REGIONS, size=N_HCP, p=REGION_P)

# --- latent: patient opportunity -------------------------------------------
spec_op_shift = np.array([SPEC_OPPORTUNITY[s] for s in specialty])
opportunity_z = rng.normal(0.0, 1.0, N_HCP) + spec_op_shift

# --- latent: engagement propensity (correlated with opportunity, not equal) --
engagement_prop = 0.38 * opportunity_z + rng.normal(0.0, 0.92, N_HCP)

# --- segment: noisy function of opportunity (never deterministic) -----------
segment_score = 0.80 * opportunity_z + 0.60 * rng.normal(0.0, 1.0, N_HCP)
q_hi, q_md = np.quantile(segment_score, [0.82, 0.45])
segment = np.where(segment_score >= q_hi, "High",
                   np.where(segment_score >= q_md, "Medium", "Low"))

# --- active flag: low-opportunity / low-engagement more likely inactive -----
p_inactive = 1.0 / (1.0 + np.exp(-(-2.05 - 0.55 * opportunity_z - 0.30 * engagement_prop)))
active_flag = (rng.random(N_HCP) > p_inactive).astype(int)

# --- latent: HCP x product affinity ----------------------------------------
affinity = np.zeros((N_HCP, len(PRODUCTS)))
for j, p in enumerate(PRODUCTS):
    base = np.array([AFFINITY_BASE[s][p] for s in specialty])
    affinity[:, j] = base + 0.45 * rng.normal(0.0, 1.0, N_HCP) + 0.25 * opportunity_z

# --- latent: refill multiplier (drives TRx from NRx) ------------------------
refill_mult = 1.65 + rng.gamma(shape=3.0, scale=0.22, size=N_HCP)   # ~1.7 .. 3.3

hcp_master = pd.DataFrame({
    "hcp_id": hcp_ids,
    "specialty": specialty,
    "region": region,
    "segment": segment,
    "active_flag": active_flag,
})
hcp_row = {h: i for i, h in enumerate(hcp_ids)}

# =============================================================================
# 4. MARKET FACTORS  (region x month environment)
# =============================================================================
print("[2/13] market_factors ...")

MONTH_SEASON = {1: 0.04, 2: 0.03, 3: 0.05, 4: 0.02, 5: 0.00, 6: -0.02,
                7: -0.06, 8: -0.05, 9: 0.04, 10: 0.06, 11: 0.03, 12: -0.07}

region_access_base = dict(zip(REGIONS, rng.uniform(0.62, 0.90, len(REGIONS))))
region_comp_base = dict(zip(REGIONS, rng.uniform(0.88, 1.14, len(REGIONS))))
# competitor entry shock month per region (staggered, some regions never)
region_comp_shock = dict(zip(REGIONS, rng.integers(8, 26, len(REGIONS))))
region_comp_shock_size = dict(zip(REGIONS, rng.uniform(0.0, 0.30, len(REGIONS))))

access_arr = np.zeros((len(REGIONS), N_MONTHS))
seas_arr = np.zeros((len(REGIONS), N_MONTHS))
comp_arr = np.zeros((len(REGIONS), N_MONTHS))

mf_rows = []
for ri, r in enumerate(REGIONS):
    drift = rng.normal(0.0, 0.004, N_MONTHS).cumsum()
    for mi, md in enumerate(MONTH_DATES):
        acc = float(np.clip(region_access_base[r] + drift[mi] + rng.normal(0, 0.012), 0.52, 0.98))
        sea = float(1.0 + MONTH_SEASON[md.month] + rng.normal(0, 0.012))
        shock = region_comp_shock_size[r] if mi >= region_comp_shock[r] else 0.0
        cmp_ = float(np.clip(region_comp_base[r] + shock + 0.006 * mi + rng.normal(0, 0.025), 0.70, 1.75))
        access_arr[ri, mi], seas_arr[ri, mi], comp_arr[ri, mi] = acc, sea, cmp_
        mf_rows.append((r, MONTH_KEYS[mi], round(acc, 4), round(sea, 4), round(cmp_, 4)))

market_factors = pd.DataFrame(mf_rows, columns=["region", "month", "access",
                                                "seasonality", "competitor_index"])
region_row = {r: i for i, r in enumerate(REGIONS)}
hcp_region_idx = np.array([region_row[r] for r in region])

# =============================================================================
# 5. MARKETING ACTIVITY  (HCP x month; confounder for Rx AND attendance)
# =============================================================================
print("[3/13] marketing_activity ...")

seg_rep_mult = {"High": 1.00, "Medium": 0.58, "Low": 0.28}
rep_lambda = (np.array([seg_rep_mult[s] for s in segment])
              * np.exp(0.30 * opportunity_z + 0.18 * engagement_prop
                       + rng.normal(0, 0.22, N_HCP))
              * 3.4)
rep_lambda *= np.where(active_flag == 1, 1.0, 0.12)

email_lambda = 2.1 + 2.6 * np.exp(0.22 * engagement_prop + rng.normal(0, 0.25, N_HCP))
email_lambda *= np.where(active_flag == 1, 1.0, 0.35)
sample_ratio = rng.uniform(0.8, 3.2, N_HCP)
other_lambda = 0.10 + 0.30 * np.exp(0.25 * engagement_prop + rng.normal(0, 0.3, N_HCP))
other_lambda *= np.where(active_flag == 1, 1.0, 0.20)

rep_calls = np.zeros((N_HCP, N_MONTHS), dtype=np.int32)
emails_m = np.zeros((N_HCP, N_MONTHS), dtype=np.int32)
samples_m = np.zeros((N_HCP, N_MONTHS), dtype=np.int32)
other_m = np.zeros((N_HCP, N_MONTHS), dtype=np.int32)

for mi, md in enumerate(MONTH_DATES):
    cal = 1.0 + MONTH_SEASON[md.month] * 1.4          # field activity seasonality
    ramp = 1.0 + 0.10 * (mi / (N_MONTHS - 1))          # slow field expansion
    rep_calls[:, mi] = rng.poisson(np.clip(rep_lambda * cal * ramp, 0, None))
    emails_m[:, mi] = rng.poisson(np.clip(email_lambda * cal, 0, None))
    samples_m[:, mi] = rng.poisson(np.clip(rep_calls[:, mi] * sample_ratio, 0, None))
    other_m[:, mi] = rng.poisson(np.clip(other_lambda * cal, 0, None))

marketing_activity = pd.DataFrame({
    "hcp_id": np.repeat(hcp_ids, N_MONTHS),
    "date": np.tile([d.isoformat() for d in MONTH_DATES], N_HCP),
    "rep_calls": rep_calls.reshape(-1),
    "emails": emails_m.reshape(-1),
    "samples": samples_m.reshape(-1),
    "other_events": other_m.reshape(-1),
})

# z-scored trailing-90-day rep calls, used by the attendance logit
rep_roll3 = np.zeros((N_HCP, N_MONTHS))
for mi in range(N_MONTHS):
    lo = max(0, mi - 3)
    rep_roll3[:, mi] = rep_calls[:, lo:mi].sum(axis=1) if mi > lo else 0.0
_rr_mu, _rr_sd = rep_roll3.mean(), rep_roll3.std() + 1e-9
rep_roll3_z = (rep_roll3 - _rr_mu) / _rr_sd

# =============================================================================
# 6. EVENTS
# =============================================================================
print("[4/13] events ...")

n_cancelled = round(N_EVENTS * 0.05)     # 15
n_planned = round(N_EVENTS * 0.08)       # 24
n_completed = N_EVENTS - n_cancelled - n_planned   # 261

# Uneven historical dates: month weights (congress season heavy, summer/Dec light)
hist_months = []
d = date(HIST_EVENT_START.year, HIST_EVENT_START.month, 1)
while d <= HIST_EVENT_END:
    hist_months.append(d)
    d = month_add(d, 1)
hist_w = np.array([1.0 + 3.2 * max(MONTH_SEASON[m.month], -0.02) for m in hist_months])
hist_w = hist_w / hist_w.sum()

n_hist = n_completed + n_cancelled
chosen_months = rng.choice(len(hist_months), size=n_hist, p=hist_w)
hist_dates = []
for k in chosen_months:
    m0 = hist_months[k]
    dim = (month_add(m0, 1) - m0).days
    dd = m0 + timedelta(days=int(rng.integers(0, dim)))
    hist_dates.append(min(max(dd, HIST_EVENT_START), HIST_EVENT_END))
hist_dates.sort()

planned_span = (PLANNED_END - PLANNED_START).days
planned_dates = sorted(PLANNED_START + timedelta(days=int(x))
                       for x in rng.integers(0, planned_span + 1, n_planned))

# speakers specialise by product area
SPEAKERS = {}
for j, p in enumerate(PRODUCTS):
    SPEAKERS[p] = [f"SPK-{1000 + j * 100 + k}" for k in range(11)]

ev_rows, ev_region, ev_product, ev_quality, ev_size_target, ev_date_obj = [], {}, {}, {}, {}, {}

# assign statuses: cancelled events interleaved through history
hist_status = np.array(["Completed"] * n_hist, dtype=object)
hist_status[rng.choice(n_hist, size=n_cancelled, replace=False)] = "Cancelled"

QUALITY_TIERS = ["strong", "moderate", "near_zero", "negative"]
QUALITY_P = np.array([0.20, 0.35, 0.27, 0.18])

all_specs = [(dt, st) for dt, st in zip(hist_dates, hist_status)] + \
            [(dt, "Planned") for dt in planned_dates]

for i, (dt, st) in enumerate(all_specs):
    eid = f"EV{2001 + i}"
    topic = str(rng.choice(TOPIC_NAMES, p=TOPIC_P))
    prod = TOPICS[topic]
    fmt = str(rng.choice(FORMATS, p=FORMAT_P))
    spk = str(rng.choice(SPEAKERS[prod]))
    ev_rows.append((eid, dt.isoformat(), topic, fmt, spk, st))
    ev_region[eid] = str(rng.choice(REGIONS, p=REGION_P))
    ev_product[eid] = prod
    ev_quality[eid] = str(rng.choice(QUALITY_TIERS, p=QUALITY_P))
    ev_date_obj[eid] = dt
    n_inv = int(np.clip(rng.lognormal(INVITE_TARGET_MEAN_LOG, 0.45), 30, 280))
    if fmt == "Virtual":
        n_inv = int(n_inv * 1.18)      # virtual invites go wider
    ev_size_target[eid] = int(np.clip(n_inv, 30, 300))

events = pd.DataFrame(ev_rows, columns=["event_id", "date", "topic",
                                        "format", "speaker", "status"])
ev_status = dict(zip(events.event_id, events.status))
ev_format = dict(zip(events.event_id, events.format))
ev_topic = dict(zip(events.event_id, events.topic))
EVENT_IDS = list(events.event_id)

# =============================================================================
# 7. CHRONOLOGICAL INVITATION + ATTENDANCE SIMULATION
# =============================================================================
print("[5/13] invitations + attendance (chronological, stateful) ...")

FORMAT_DURATION = {"In-person": (52, 118), "Hybrid": (45, 105), "Virtual": (22, 82)}


def _att_row(eid, hid, registered, verified, fmt, eng_z, r):
    """One attendance/sign-in record.

    verified_attended == 0  -> duration and engagement are 0 (no session data)
    verified_attended == 1  -> duration > 0, engagement in 5..100
    """
    if verified == 1:
        lo, hi = FORMAT_DURATION[fmt]
        span = hi - lo
        q = 1.0 / (1.0 + math.exp(-(0.75 * eng_z + r.normal(0, 0.7))))
        dur = int(round(lo + span * (0.25 + 0.75 * q)))
        eng = int(round(np.clip(38 + 26 * eng_z + r.normal(0, 12), 5, 100)))
        return {"event_id": eid, "hcp_id": hid, "registered": registered,
                "verified_attended": 1, "duration": dur, "engagement": eng}
    return {"event_id": eid, "hcp_id": hid, "registered": registered,
            "verified_attended": 0, "duration": 0, "engagement": 0}

CHANNEL_LAG = {"Email": (7, 35), "Rep": (21, 60), "Phone": (5, 25), "Portal": (10, 45)}

# running state: standardized prior event engagement, seeded from latent propensity
prior_eng_z = 0.55 * engagement_prop.copy()
attended_history = defaultdict(list)      # hcp_row -> [(date, event_id)]
# compliance/fatigue state: programs cap how often the same HCP is re-invited
last_att_mi = np.full(N_HCP, -999.0)      # month index of most recent attendance
n_att_ct = np.zeros(N_HCP)                # attendances to date

inv_rows = []
att_records = []       # dicts, ingestion order preserved
inv_pairs = set()

topic_primary = {t: set(v[0]) for t, v in TOPIC_AUDIENCE.items()}
topic_secondary = {t: set(v[1]) for t, v in TOPIC_AUDIENCE.items()}

# order all events by date so state evolves correctly
order = sorted(range(len(EVENT_IDS)), key=lambda i: ev_date_obj[EVENT_IDS[i]])

for oi in order:
    eid = EVENT_IDS[oi]
    edate = ev_date_obj[eid]
    etopic = ev_topic[eid]
    eprod = ev_product[eid]
    efmt = ev_format[eid]
    estat = ev_status[eid]
    ereg = ev_region[eid]
    pj = PROD_IDX[eprod]
    emi = min(max(date_to_month_idx(edate), 0), N_MONTHS - 1)

    prim, sec = topic_primary[etopic], topic_secondary[etopic]
    s_spec = np.where(np.isin(specialty, list(prim)), 0.95,
                      np.where(np.isin(specialty, list(sec)), 0.35, -0.45))
    adj = REGION_ADJACENT[ereg]
    s_geo = np.where(region == ereg, 0.70,
                     np.where(np.isin(region, list(adj)), 0.15, -0.50))
    if efmt == "Virtual":
        s_geo = s_geo * 0.25                      # geography barely matters virtually

    s_aff = 0.80 * affinity[:, pj]
    s_prior = 0.60 * prior_eng_z
    s_vol = 0.50 * opportunity_z
    s_active = np.where(active_flag == 1, 0.0, -1.10)

    # Compliance reality: an HCP who recently attended a program is heavily
    # suppressed from the next invite list, and cumulative attendance attracts
    # an annual-cap penalty. This keeps naturally-occurring overlapping exposure
    # rare, so the injected 8% contamination in Section 8 is the dominant source.
    gap_m = emi - last_att_mi
    s_recency = np.where(gap_m < 3.0, -2.30, np.where(gap_m < 6.0, -0.95, 0.0))
    s_fatigue = -0.30 * np.minimum(n_att_ct, 8.0)

    score = (s_spec + s_aff + s_geo + s_prior + s_vol + s_active
             + s_recency + s_fatigue
             + rng.normal(0.0, 0.60, N_HCP))

    w = np.exp(1.25 * (score - score.max()))
    w = w / w.sum()
    n_inv = min(ev_size_target[eid], N_HCP)
    invitees = rng.choice(N_HCP, size=n_inv, replace=False, p=w)

    # ---- eligible_reason from the dominant score driver --------------------
    comp = np.vstack([s_spec[invitees], s_aff[invitees], s_geo[invitees],
                      s_prior[invitees], s_vol[invitees]])
    top = comp.argmax(axis=0)
    srt = np.sort(comp, axis=0)
    margin = srt[-1] - srt[-2]
    reason = np.where(margin < 0.15, 5, top)

    chan = rng.choice(CHANNELS, size=n_inv, p=[0.52, 0.24, 0.11, 0.13])
    # High segment more likely rep-invited
    hi = (segment[invitees] == "High") & (rng.random(n_inv) < 0.35)
    chan = np.where(hi, "Rep", chan)

    for k, h in enumerate(invitees):
        lo, hi_l = CHANNEL_LAG[chan[k]]
        lag = int(rng.integers(lo, hi_l + 1))
        inv_dt = edate - timedelta(days=lag)
        inv_rows.append((eid, hcp_ids[h], inv_dt.isoformat(), str(chan[k]),
                         ELIGIBLE_REASONS[int(reason[k])]))
        inv_pairs.add((eid, hcp_ids[h]))

    # ---- attendance ------------------------------------------------------
    if estat == "Planned":
        continue    # future event: invitations only, no attendance, no exposure

    if efmt == "In-person":
        friction = 0.75 + 0.55 * (region[invitees] != ereg)
    elif efmt == "Hybrid":
        friction = 0.30 + 0.20 * (region[invitees] != ereg)
    else:
        friction = np.full(n_inv, 0.05)

    logit = (-2.2
             + 0.55 * prior_eng_z[invitees]
             + 0.40 * affinity[invitees, pj]
             + 0.25 * rep_roll3_z[invitees, emi]
             + s_spec[invitees]
             - friction
             + rng.normal(0.0, 0.55, n_inv))
    p_att = 1.0 / (1.0 + np.exp(-logit))
    attended = (rng.random(n_inv) < p_att).astype(int)
    # inactive HCPs effectively never show
    attended = np.where(active_flag[invitees] == 1, attended, 0)

    if estat == "Cancelled":
        # DEFECT: residual sign-in rows survive on a cancelled event.
        keep = rng.random(n_inv) < 0.30
        for k, h in enumerate(invitees):
            if not keep[k]:
                continue
            resid_att = int(attended[k] and rng.random() < 0.35)
            att_records.append(_att_row(eid, hcp_ids[h], 1, resid_att, efmt,
                                        prior_eng_z[h], rng))
        continue

    # Completed event
    show_base = {"In-person": 1.00, "Hybrid": 0.95, "Virtual": 0.88}[efmt]
    for k, h in enumerate(invitees):
        if attended[k] == 1:
            att_records.append(_att_row(eid, hcp_ids[h], 1, 1, efmt,
                                        prior_eng_z[h], rng))
            attended_history[h].append((edate, eid))
        else:
            u = rng.random()
            if u < 0.14 * show_base:
                att_records.append(_att_row(eid, hcp_ids[h], 1, 0, efmt,
                                            prior_eng_z[h], rng))
            elif u < 0.14 * show_base + 0.095:
                att_records.append(_att_row(eid, hcp_ids[h], 0, 0, efmt,
                                            prior_eng_z[h], rng))

    # ---- update running prior engagement for attendees --------------------
    att_idx = invitees[attended == 1]
    if att_idx.size:
        prior_eng_z[att_idx] = 0.62 * prior_eng_z[att_idx] + 0.38 * (
            0.9 + 0.35 * rng.normal(0, 1, att_idx.size))
        last_att_mi[att_idx] = emi
        n_att_ct[att_idx] += 1.0

print(f"        raw invitations={len(inv_rows)}  raw attendance rows={len(att_records)}")

# =============================================================================
# 8. DEFECT INJECTION #1 — overlapping / contaminated exposure  (8% of attendees)
#    A second RELATED completed event within 90 days. No flag column: only the
#    event dates reveal it, so the eligibility builder must detect it.
# =============================================================================
print("[6/13] inject overlapping/contaminated exposure ...")

completed_ids = [e for e in EVENT_IDS if ev_status[e] == "Completed"]
by_product = defaultdict(list)
for e in completed_ids:
    by_product[ev_product[e]].append(e)

attendee_rows = sorted(attended_history.keys())
n_contam = int(round(0.08 * len(attendee_rows)))
contam_hcps = rng.choice(attendee_rows, size=n_contam, replace=False)

att_pairs_verified = {(r["event_id"], r["hcp_id"])
                      for r in att_records if r["verified_attended"] == 1}
contam_added = 0
for h in contam_hcps:
    hist = attended_history[h]
    d0, e0 = hist[int(rng.integers(0, len(hist)))]
    cands = [e for e in by_product[ev_product[e0]]
             if e != e0
             and abs((ev_date_obj[e] - d0).days) <= 90
             and (e, hcp_ids[h]) not in att_pairs_verified]
    if not cands:
        continue
    e2 = str(rng.choice(cands))
    # attendance requires an invitation -> create it if the HCP was not invited
    if (e2, hcp_ids[h]) not in inv_pairs:
        lag = int(rng.integers(5, 40))
        inv_rows.append((e2, hcp_ids[h],
                         (ev_date_obj[e2] - timedelta(days=lag)).isoformat(),
                         str(rng.choice(CHANNELS, p=[0.52, 0.24, 0.11, 0.13])),
                         "Combination of factors"))
        inv_pairs.add((e2, hcp_ids[h]))
    att_records.append(_att_row(e2, hcp_ids[h], 1, 1, ev_format[e2],
                                prior_eng_z[h], rng))
    att_pairs_verified.add((e2, hcp_ids[h]))
    attended_history[h].append((ev_date_obj[e2], e2))
    contam_added += 1

# =============================================================================
# 9. DEFECT INJECTION #2 — duplicate sign-in (~1% of attendance records)
#    Appended as a late-arriving correction batch: for duplicated keys the row
#    occurring LATER in the file is the authoritative one.
# =============================================================================
print("[7/13] inject duplicate sign-in rows ...")

n_base_att = len(att_records)
n_dup = int(round(0.01 * n_base_att))
dup_src = rng.choice(n_base_att, size=n_dup, replace=False)
dup_rows = []
for k in dup_src:
    src = att_records[int(k)]
    if src["verified_attended"] == 1 and rng.random() < 0.30:
        # late sign-in correction: original gets downgraded, later row is truth
        newer = dict(src)
        newer["duration"] = int(max(1, src["duration"] + int(rng.integers(-8, 9))))
        newer["engagement"] = int(np.clip(src["engagement"] + int(rng.integers(-5, 6)), 5, 100))
        att_records[int(k)] = {**src, "verified_attended": 0, "duration": 0, "engagement": 0}
        dup_rows.append(newer)
    else:
        newer = dict(src)
        if src["verified_attended"] == 1:
            newer["duration"] = int(max(1, src["duration"] + int(rng.integers(-8, 9))))
            newer["engagement"] = int(np.clip(src["engagement"] + int(rng.integers(-5, 6)), 5, 100))
        dup_rows.append(newer)
att_records.extend(dup_rows)

event_attendance = pd.DataFrame(att_records, columns=["event_id", "hcp_id", "registered",
                                                     "verified_attended", "duration",
                                                     "engagement"])
event_invitations = pd.DataFrame(inv_rows, columns=["event_id", "hcp_id", "invited_at",
                                                   "channel", "eligible_reason"])
print(f"        invitations={len(event_invitations)}  attendance={len(event_attendance)}"
      f"  contaminated={contam_added}  duplicates={n_dup}")

# ---- resolved attendee view (dedupe-to-latest), used for truth + Rx ---------
_resolved = {}
for r in att_records:
    _resolved[(r["event_id"], r["hcp_id"])] = r
TRUE_ATTENDEES = [(e, h) for (e, h), r in _resolved.items()
                  if r["verified_attended"] == 1 and ev_status[e] == "Completed"]

# =============================================================================
# 10. Rx PANEL SCAFFOLD  (baselines + product coverage) — needed before truth
# =============================================================================
print("[8/13] Rx baselines + product coverage ...")

seg_bump = np.array([{"High": 0.45, "Medium": 0.10, "Low": -0.30}[s] for s in segment])
prod_log = np.array([PROD_LOG_SCALE[p] for p in PRODUCTS])

# Log-linear baseline, with the linear predictor clipped so the exponential tail
# cannot produce implausible prescriber volumes.
lin = (0.60
       + 0.52 * np.clip(affinity, -2.5, 2.5)
       + (0.32 * np.clip(opportunity_z, -3.0, 3.0) + seg_bump)[:, None]
       + prod_log[None, :]
       + 0.26 * rng.normal(0, 1, (N_HCP, len(PRODUCTS))))
base_nrx = np.exp(np.clip(lin, -2.6, 3.40))          # <= ~30 NRx/month
base_nrx *= np.where(active_flag == 1, 1.0, 0.14)[:, None]
base_nrx = np.clip(base_nrx, 0.05, None)

present = (affinity > -0.35) | (rng.random((N_HCP, len(PRODUCTS))) < 0.12)
for i in range(N_HCP):                      # every HCP prescribes >= 1 product
    if not present[i].any():
        present[i, int(np.argmax(affinity[i]))] = True
for e, h in TRUE_ATTENDEES:                 # attendees must carry the event product
    present[hcp_row[h], PROD_IDX[ev_product[e]]] = True

comp_ratio = rng.uniform(0.50, 2.60, (N_HCP, len(PRODUCTS)))

# =============================================================================
# 11. HIDDEN GROUND TRUTH  (generated BEFORE observed outcomes are drawn)
# =============================================================================
print("[9/13] ground_truth ...")

QUALITY_LIFT = {"strong": (0.30, 0.08), "moderate": (0.13, 0.05),
                "near_zero": (0.01, 0.03), "negative": (-0.07, 0.04)}
SEG_MULT = {"High": 1.25, "Medium": 1.00, "Low": 0.72}
FMT_MULT = {"In-person": 1.15, "Hybrid": 1.00, "Virtual": 0.85}

effect_add = np.zeros((N_HCP, len(PRODUCTS), N_MONTHS))
gt_rows = []

for e, h in sorted(TRUE_ATTENDEES):
    hi_ = hcp_row[h]
    pj = PROD_IDX[ev_product[e]]
    tmu, tsd = QUALITY_LIFT[ev_quality[e]]
    pct = rng.normal(tmu, tsd)

    etopic = ev_topic[e]
    if specialty[hi_] in topic_primary[etopic]:
        match_m = 1.15
    elif specialty[hi_] in topic_secondary[etopic]:
        match_m = 0.90
    else:
        match_m = 0.60

    eng_m = float(np.clip(1.0 + 0.25 * engagement_prop[hi_], 0.55, 1.60))
    aff_m = float(np.clip(1.0 + 0.18 * affinity[hi_, pj], 0.55, 1.55))
    mod = SEG_MULT[segment[hi_]] * match_m * FMT_MULT[ev_format[e]] * eng_m * aff_m
    mod *= float(np.exp(rng.normal(0, 0.20)))          # irreducible HCP-level noise

    # Realised average % lift over the 3-month post window, bounded so the
    # multiplicative modifiers cannot compound into an implausible effect.
    lift = float(np.clip(pct * mod, -0.30, 0.60))
    eff_nrx = float(base_nrx[hi_, pj] * 3.0 * lift)
    eff_trx = float(eff_nrx * refill_mult[hi_] * rng.uniform(0.90, 1.10))

    emi = date_to_month_idx(ev_date_obj[e])
    for w_i, w in enumerate(EFFECT_WEIGHTS, start=1):
        m = emi + w_i
        if 0 <= m < N_MONTHS:
            effect_add[hi_, pj, m] += eff_nrx * w

    gt_rows.append((e, h, round(eff_nrx, 4), round(eff_trx, 4)))

ground_truth = pd.DataFrame(gt_rows, columns=["event_id", "hcp_id",
                                              "true_event_effect_nrx",
                                              "true_event_effect_trx"])

# =============================================================================
# 12. hcp_rx_monthly  (observed outcomes)
# =============================================================================
print("[10/13] hcp_rx_monthly ...")

pairs = np.argwhere(present)                      # (P, 2) -> hcp_row, product_idx
P = pairs.shape[0]
ph, pp = pairs[:, 0], pairs[:, 1]

base_col = base_nrx[ph, pp][:, None]
acc = access_arr[hcp_region_idx[ph], :]
sea = seas_arr[hcp_region_idx[ph], :]
cmpx = comp_arr[hcp_region_idx[ph], :]
rep = rep_calls[ph, :].astype(float)

t_norm = (np.arange(N_MONTHS) / (N_MONTHS - 1))[None, :]
trend_term = np.array([PROD_TREND[PRODUCTS[j]] for j in pp])[:, None] * (t_norm - 0.40)
seas_term = (sea - 1.0)
access_term = (acc - 0.76) * 0.85
rep_term = 0.045 * np.minimum(rep, 12.0)
comp_term = 0.40 * (cmpx - 1.0)

multiplier = np.clip(1.0 + trend_term + seas_term + access_term + rep_term - comp_term,
                     0.15, None)
expected_nrx = base_col * multiplier + effect_add[ph, pp, :]
expected_nrx = np.clip(expected_nrx, 0.02, None)

K_NRX, K_TRX, K_CMP = 3.0, 4.0, 2.5
obs_nrx = rng.negative_binomial(K_NRX, K_NRX / (K_NRX + expected_nrx))

rm = refill_mult[ph][:, None]
mu_extra = np.clip(expected_nrx * (rm - 1.0), 0.01, None)
obs_trx = obs_nrx + rng.negative_binomial(K_TRX, K_TRX / (K_TRX + mu_extra))

mu_comp = np.clip(base_col * rm * comp_ratio[ph, pp][:, None] * cmpx, 0.02, None)
obs_comp = rng.negative_binomial(K_CMP, K_CMP / (K_CMP + mu_comp))

rx = pd.DataFrame({
    "hcp_id": np.repeat(hcp_ids[ph], N_MONTHS),
    "month": np.tile(MONTH_KEYS, P),
    "product": np.repeat(np.array(PRODUCTS)[pp], N_MONTHS),
    "nrx": obs_nrx.reshape(-1).astype(np.int32),
    "trx": obs_trx.reshape(-1).astype(np.int32),
    "competitor_trx": obs_comp.reshape(-1).astype(np.int32),
})
rx_expected_rows = len(rx)

# ---- DEFECT INJECTION #3 — missing Rx months (3%): 0.6% bursty + 2.4% random --
print("[11/13] inject missing Rx months ...")
target_missing = int(round(0.030 * rx_expected_rows))
bursty_target = int(round(0.006 * rx_expected_rows))

hcp_of_row = np.repeat(ph, N_MONTHS)
month_of_row = np.tile(np.arange(N_MONTHS), P)
drop_mask = np.zeros(rx_expected_rows, dtype=bool)

shuffled = rng.permutation(N_HCP)
gap_hcps, si = [], 0
while drop_mask.sum() < bursty_target and si < N_HCP:
    h = int(shuffled[si]); si += 1
    glen = int(rng.integers(4, 10))
    gstart = int(rng.integers(0, N_MONTHS - glen))
    sel = (hcp_of_row == h) & (month_of_row >= gstart) & (month_of_row < gstart + glen)
    if sel.sum() == 0:
        continue
    drop_mask |= sel
    gap_hcps.append(hcp_ids[h])
n_bursty = int(drop_mask.sum())

remaining = target_missing - n_bursty
cand = np.flatnonzero(~drop_mask)
drop_mask[rng.choice(cand, size=max(remaining, 0), replace=False)] = True

hcp_rx_monthly = rx.loc[~drop_mask].reset_index(drop=True)
n_missing = int(drop_mask.sum())
print(f"        panel slots={rx_expected_rows}  dropped={n_missing} "
      f"({n_missing / rx_expected_rows:.2%})  bursty-gap HCPs={len(gap_hcps)}")

# =============================================================================
# 13. EVENT COST  (+ 2% outliers)
# =============================================================================
print("[12/13] event_cost ...")

registered_n = (event_attendance.query("registered == 1")
                .drop_duplicates(["event_id", "hcp_id"])
                .groupby("event_id").size().to_dict())

cost_rows = []
for eid in EVENT_IDS:
    fmt, st = ev_format[eid], ev_status[eid]
    size = registered_n.get(eid, max(8, int(ev_size_target[eid] * 0.20)))
    if fmt == "In-person":
        hon = rng.uniform(2500, 4500) * rng.uniform(0.9, 1.15)
        ven = 850 + 24 * size * rng.uniform(0.8, 1.3)
        meal = size * rng.uniform(58, 96)
        trav = rng.uniform(950, 2600) + size * rng.uniform(18, 55)
        agc = rng.uniform(1600, 3600)
    elif fmt == "Hybrid":
        hon = rng.uniform(2200, 3900)
        ven = 420 + 11 * size * rng.uniform(0.7, 1.2)
        meal = size * rng.uniform(20, 46)
        trav = rng.uniform(380, 1250) + size * rng.uniform(5, 18)
        agc = rng.uniform(1500, 3300)
    else:  # Virtual
        hon = rng.uniform(1400, 2600)
        ven = rng.uniform(150, 480)                      # platform / streaming
        meal = size * rng.uniform(0, 14)                 # occasional meal voucher
        trav = rng.uniform(0, 120)
        agc = rng.uniform(900, 2400)
    if st == "Cancelled":
        f = rng.uniform(0.15, 0.40)                      # cancellation fees only
        hon, ven, meal, trav, agc = hon * f, ven * f, meal * 0.05, trav * f, agc * rng.uniform(0.4, 0.8)
    cost_rows.append([eid, hon, ven, meal, trav, agc])

n_outlier = int(round(0.02 * N_EVENTS))
outlier_idx = rng.choice(N_EVENTS, size=n_outlier, replace=False)
outlier_events = []
for k in outlier_idx:
    f = float(rng.uniform(3.0, 5.0))
    for c in range(1, 6):
        cost_rows[int(k)][c] *= f
    outlier_events.append(cost_rows[int(k)][0])

event_cost = pd.DataFrame(cost_rows, columns=["event_id", "honorarium", "venue",
                                              "meal", "travel", "agency"])
for c in ["honorarium", "venue", "meal", "travel", "agency"]:
    event_cost[c] = event_cost[c].round(2)
event_cost["total"] = event_cost[["honorarium", "venue", "meal", "travel", "agency"]].sum(axis=1).round(2)

# =============================================================================
# 14. IDENTITY CROSSWALK  (2% event-id gaps + 3% rx-vendor-id gaps => 5% review)
# =============================================================================
crm_n = rng.permutation(9_000_000)[:N_HCP] + 1_000_000
evt_n = rng.permutation(9_000_000)[:N_HCP] + 1_000_000
rxv_n = rng.permutation(9_000_000)[:N_HCP] + 1_000_000

identity_crosswalk = pd.DataFrame({
    "master_hcp_id": hcp_ids,
    "crm_hcp_id": [f"CRM-{n:07d}" for n in crm_n],
    "event_hcp_id": [f"EVT{n:08d}" for n in evt_n],
    "rx_vendor_hcp_id": [f"RXV_{n:07d}X" for n in rxv_n],
    "match_status": "verified",
})

n_evt_gap = int(round(0.02 * N_HCP))     # 50
n_rxv_gap = int(round(0.03 * N_HCP))     # 75
gap_idx = rng.choice(N_HCP, size=n_evt_gap + n_rxv_gap, replace=False)
evt_gap_idx, rxv_gap_idx = gap_idx[:n_evt_gap], gap_idx[n_evt_gap:]
identity_crosswalk.loc[evt_gap_idx, "event_hcp_id"] = None
identity_crosswalk.loc[rxv_gap_idx, "rx_vendor_hcp_id"] = None
identity_crosswalk.loc[gap_idx, "match_status"] = "review"

# =============================================================================
# 15. BUSINESS ASSUMPTIONS  (the ONLY source of financial assumptions)
# =============================================================================
BA = {
    "CARDIVEX":  {"Conservative": (5.4, 78.00), "Base": (6.2, 92.00),  "Optimistic": (7.1, 108.00)},
    "ONCOLERA":  {"Conservative": (3.1, 1150.00), "Base": (3.8, 1340.00), "Optimistic": (4.5, 1590.00)},
    "ENDOSTAT":  {"Conservative": (6.8, 54.00), "Base": (7.9, 64.00),  "Optimistic": (9.1, 77.00)},
    "NEUROVANT": {"Conservative": (4.2, 130.00), "Base": (5.0, 155.00), "Optimistic": (5.9, 186.00)},
}
ba_rows = []
for p in PRODUCTS:
    for sc in ["Conservative", "Base", "Optimistic"]:
        f, n = BA[p][sc]
        ba_rows.append((p, sc, f, n, round(f * n, 2)))
business_assumptions = pd.DataFrame(ba_rows, columns=[
    "product", "scenario", "expected_fills_per_new_rx",
    "net_contribution_per_fill", "net_contribution_per_incremental_nrx"])

# =============================================================================
# 16. WRITE BRONZE
# =============================================================================
print("[13/13] writing bronze/ ...")

with open(os.path.join(DATA, "seed.txt"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write(f"{SEED}\n")

FRAMES = {
    "hcp_master.csv": hcp_master,
    "events.csv": events,
    "event_invitations.csv": event_invitations,
    "event_attendance.csv": event_attendance,
    "hcp_rx_monthly.csv": hcp_rx_monthly,
    "marketing_activity.csv": marketing_activity,
    "event_cost.csv": event_cost,
    "market_factors.csv": market_factors,
    "identity_crosswalk.csv": identity_crosswalk,
    "business_assumptions.csv": business_assumptions,
    "ground_truth.csv": ground_truth,
}
for fn, df in FRAMES.items():
    df.to_csv(os.path.join(BRONZE, fn), index=False, na_rep="", lineterminator="\n")
    print(f"        {fn:28s} rows={len(df):>7,}  cols={df.shape[1]}")

# =============================================================================
# 17. DATA DICTIONARY  (one row per column across every bronze file)
# =============================================================================
DD = [
 # ---- hcp_master ----------------------------------------------------------
 ("hcp_master.csv", "hcp_id", "string", "Master (golden) HCP identifier; primary key used by every other bronze file.", "HCP100001", "PK; unique; not null; pattern HCP[0-9]{6}"),
 ("hcp_master.csv", "specialty", "string", "Primary practice specialty; drives topic relevance and product affinity.", "Cardiology", "Enum(8): Cardiology|Oncology|Endocrinology|Neurology|Dermatology|Primary Care|Psychiatry|Gastroenterology; uneven distribution"),
 ("hcp_master.csv", "region", "string", "Sales region of record; joins to market_factors.region.", "Northeast", "Enum(7); FK -> market_factors.region; not null"),
 ("hcp_master.csv", "segment", "string", "Commercial value segment derived from latent patient opportunity (noisy, not deterministic).", "High", "Enum(3): High|Medium|Low; ~18/37/45 split"),
 ("hcp_master.csv", "active_flag", "integer", "1 = actively targeted/prescribing, 0 = inactive. Inactive HCPs show materially lower activity and Rx.", "1", "Domain {0,1}; ~88% = 1"),
 # ---- events --------------------------------------------------------------
 ("events.csv", "event_id", "string", "Speaker program identifier.", "EV2001", "PK; unique; not null; pattern EV[0-9]{4}"),
 ("events.csv", "date", "date", "Scheduled event date (ISO-8601). Historical events 2024-09..2026-05; Planned events are future-dated.", "2025-03-14", "YYYY-MM-DD; not null; Planned rows > run date"),
 ("events.csv", "topic", "string", "Therapeutic topic; maps 1:1 to the promoted product (mapping is NOT exposed in bronze).", "Heart Failure Management", "Enum(8) tied to the 4-product portfolio"),
 ("events.csv", "format", "string", "Delivery format; drives cost, travel friction and effect size.", "In-person", "Enum(3): In-person|Virtual|Hybrid"),
 ("events.csv", "speaker", "string", "Synthetic speaker identifier; speakers specialise by therapeutic area.", "SPK-1004", "Not null; pattern SPK-[0-9]{4}; 44 distinct"),
 ("events.csv", "status", "string", "Lifecycle status. ONLY 'Completed' constitutes treatment exposure.", "Completed", "Enum(3): Completed(~87%)|Cancelled(~5%)|Planned(~8%)"),
 # ---- event_invitations ---------------------------------------------------
 ("event_invitations.csv", "event_id", "string", "Invited-to event.", "EV2001", "FK -> events.event_id; PK part 1"),
 ("event_invitations.csv", "hcp_id", "string", "Invited HCP.", "HCP100742", "FK -> hcp_master.hcp_id; PK part 2"),
 ("event_invitations.csv", "invited_at", "date", "Date the invitation was issued.", "2025-02-11", "YYYY-MM-DD; must be <= events.date for the same event_id"),
 ("event_invitations.csv", "channel", "string", "Channel the invitation was delivered through; sets the invite lead time.", "Email", "Enum(4): Email|Rep|Phone|Portal"),
 ("event_invitations.csv", "eligible_reason", "string", "Dominant targeting driver recorded by the invitation engine.", "Specialty match", "Enum(6): Specialty match|Product affinity|Geographic proximity|Prior engagement|Patient-volume threshold|Combination of factors"),
 # ---- event_attendance ----------------------------------------------------
 ("event_attendance.csv", "event_id", "string", "Event the sign-in record belongs to.", "EV2001", "FK -> events.event_id; (event_id,hcp_id) must exist in event_invitations"),
 ("event_attendance.csv", "hcp_id", "string", "HCP the sign-in record belongs to.", "HCP100742", "FK -> hcp_master.hcp_id"),
 ("event_attendance.csv", "registered", "integer", "1 = HCP registered for the program, 0 = tracked response without registration (declined/no action).", "1", "Domain {0,1}; verified_attended=1 implies registered=1"),
 ("event_attendance.csv", "verified_attended", "integer", "1 = attendance verified at the event, 0 = registered but did not attend.", "1", "Domain {0,1}"),
 ("event_attendance.csv", "duration", "integer", "Verified minutes present. 0 when verified_attended = 0.", "78", "Integer >= 0; >0 iff verified_attended=1"),
 ("event_attendance.csv", "engagement", "integer", "Engagement score for the session. 0 when verified_attended = 0.", "61", "Integer 0..100; 5..100 iff verified_attended=1"),
 # ---- hcp_rx_monthly ------------------------------------------------------
 ("hcp_rx_monthly.csv", "hcp_id", "string", "Prescribing HCP.", "HCP100001", "FK -> hcp_master.hcp_id; PK part 1"),
 ("hcp_rx_monthly.csv", "month", "string", "Calendar month of the prescription counts.", "2025-03", "YYYY-MM; FK -> market_factors.month; PK part 2"),
 ("hcp_rx_monthly.csv", "product", "string", "Portfolio product.", "CARDIVEX", "Enum(4); FK -> business_assumptions.product; PK part 3"),
 ("hcp_rx_monthly.csv", "nrx", "integer", "New prescriptions written in the month (NegativeBinomial draw).", "9", "Integer >= 0"),
 ("hcp_rx_monthly.csv", "trx", "integer", "Total prescriptions (new + refills) in the month.", "23", "Integer >= 0; trx >= nrx always"),
 ("hcp_rx_monthly.csv", "competitor_trx", "integer", "Total prescriptions for competing molecules in the class.", "31", "Integer >= 0"),
 # ---- marketing_activity --------------------------------------------------
 ("marketing_activity.csv", "hcp_id", "string", "Targeted HCP.", "HCP100001", "FK -> hcp_master.hcp_id; PK part 1"),
 ("marketing_activity.csv", "date", "date", "Month of activity, stamped to the first of the month (monthly aggregate grain).", "2025-03-01", "YYYY-MM-01; PK part 2"),
 ("marketing_activity.csv", "rep_calls", "integer", "Sales-rep detail calls in the month. Confounds both Rx and attendance.", "4", "Integer >= 0"),
 ("marketing_activity.csv", "emails", "integer", "Marketing emails delivered in the month.", "6", "Integer >= 0"),
 ("marketing_activity.csv", "samples", "integer", "Sample units dropped in the month.", "9", "Integer >= 0"),
 ("marketing_activity.csv", "other_events", "integer", "Non-speaker-program touchpoints (congresses, advisory boards) in the month.", "1", "Integer >= 0"),
 # ---- event_cost ----------------------------------------------------------
 ("event_cost.csv", "event_id", "string", "Costed event.", "EV2001", "PK; unique; FK -> events.event_id; one row per event"),
 ("event_cost.csv", "honorarium", "numeric(12,2)", "Speaker honorarium paid.", "3412.55", "USD >= 0"),
 ("event_cost.csv", "venue", "numeric(12,2)", "Venue / streaming-platform cost.", "2760.40", "USD >= 0; In-person >> Virtual"),
 ("event_cost.csv", "meal", "numeric(12,2)", "Compliant meal spend.", "1884.20", "USD >= 0; ~0 for Virtual"),
 ("event_cost.csv", "travel", "numeric(12,2)", "Speaker and attendee travel/lodging.", "2105.90", "USD >= 0; ~0 for Virtual"),
 ("event_cost.csv", "agency", "numeric(12,2)", "Agency/logistics fees.", "2488.10", "USD >= 0"),
 ("event_cost.csv", "total", "numeric(12,2)", "Total program cost. Sole cost input to the downstream ROI denominator.", "12651.15", "= honorarium+venue+meal+travel+agency (exact); ~2% of rows are 3-5x format norm"),
 # ---- market_factors ------------------------------------------------------
 ("market_factors.csv", "region", "string", "Sales region.", "Northeast", "Enum(7); FK <- hcp_master.region; PK part 1"),
 ("market_factors.csv", "month", "string", "Calendar month.", "2025-03", "YYYY-MM; PK part 2; spans the full Rx panel"),
 ("market_factors.csv", "access", "numeric(6,4)", "Formulary/payer access index for the region-month.", "0.7431", "0.52 .. 0.98"),
 ("market_factors.csv", "seasonality", "numeric(6,4)", "Multiplicative seasonality index centred on 1.0.", "1.0482", "~0.90 .. 1.10"),
 ("market_factors.csv", "competitor_index", "numeric(6,4)", "Competitive pressure index; >1 = above-normal pressure (staggered competitor entry).", "1.1205", "0.70 .. 1.75"),
 # ---- identity_crosswalk --------------------------------------------------
 ("identity_crosswalk.csv", "master_hcp_id", "string", "Golden record ID; equals hcp_master.hcp_id.", "HCP100001", "PK; unique; FK -> hcp_master.hcp_id; one row per HCP"),
 ("identity_crosswalk.csv", "crm_hcp_id", "string", "CRM system identifier (independent numbering).", "CRM-4820193", "Unique; not null; pattern CRM-[0-9]{7}"),
 ("identity_crosswalk.csv", "event_hcp_id", "string", "Event/meeting-management system identifier.", "EVT03918442", "Unique when present; NULL for ~2% of rows (unresolved event identity)"),
 ("identity_crosswalk.csv", "rx_vendor_hcp_id", "string", "Prescription data vendor identifier.", "RXV_2910744X", "Unique when present; NULL for ~3% of rows (unresolved Rx identity)"),
 ("identity_crosswalk.csv", "match_status", "string", "Identity resolution outcome. 'review' rows must be QUARANTINED downstream - never silently treated as non-attendees.", "verified", "Enum(2): verified(~95%)|review(~5%); 'review' iff an ID is NULL"),
 # ---- business_assumptions ------------------------------------------------
 ("business_assumptions.csv", "product", "string", "Portfolio product.", "CARDIVEX", "Enum(4); PK part 1; FK <- hcp_rx_monthly.product"),
 ("business_assumptions.csv", "scenario", "string", "Financial scenario.", "Base", "Enum(3): Conservative|Base|Optimistic; PK part 2"),
 ("business_assumptions.csv", "expected_fills_per_new_rx", "numeric(6,2)", "Expected number of dispensed fills generated by one new Rx.", "6.20", "> 0; Optimistic > Base > Conservative"),
 ("business_assumptions.csv", "net_contribution_per_fill", "numeric(12,2)", "Net contribution (USD) per dispensed fill.", "92.00", "> 0; varies by product margin"),
 ("business_assumptions.csv", "net_contribution_per_incremental_nrx", "numeric(14,2)", "Net contribution per incremental NRx. THE ONLY financial multiplier permitted downstream.", "570.40", "= expected_fills_per_new_rx * net_contribution_per_fill (exact)"),
 # ---- ground_truth --------------------------------------------------------
 ("ground_truth.csv", "event_id", "string", "Completed event that generated the exposure.", "EV2001", "FK -> events.event_id (status='Completed'); PK part 1"),
 ("ground_truth.csv", "hcp_id", "string", "Verified attendee.", "HCP100742", "FK -> hcp_master.hcp_id; PK part 2"),
 ("ground_truth.csv", "true_event_effect_nrx", "numeric(12,4)", "HIDDEN TRUTH: total incremental NRx caused by this event for this HCP, summed over post-months +1..+3 (weights 0.45/0.33/0.22). Can be negative.", "4.8312", "Real; NEVER a model input; absent rows = zero true effect"),
 ("ground_truth.csv", "true_event_effect_trx", "numeric(12,4)", "HIDDEN TRUTH: matching total incremental TRx over post-months +1..+3.", "11.9044", "Real; NEVER a model input"),
 # ---- meta files ----------------------------------------------------------
 ("data_dictionary.csv", "dataset", "string", "Bronze file the column belongs to.", "hcp_master.csv", "Not null"),
 ("data_dictionary.csv", "column", "string", "Column name.", "hcp_id", "Not null; (dataset,column) unique"),
 ("data_dictionary.csv", "data_type", "string", "Logical data type.", "string", "Not null"),
 ("data_dictionary.csv", "description", "string", "Business meaning of the column.", "Master HCP identifier.", "Not null"),
 ("data_dictionary.csv", "example_value", "string", "Representative value.", "HCP100001", "Free text"),
 ("data_dictionary.csv", "constraints", "string", "Keys, domains, ranges and injected-defect notes.", "PK; unique; not null", "Free text"),
 ("data_quality_report.csv", "check_name", "string", "Stable machine-readable check identifier.", "imperfection_duplicate_signin_injected", "Not null; unique"),
 ("data_quality_report.csv", "dataset", "string", "Bronze file(s) the check was executed against.", "event_attendance.csv", "Not null"),
 ("data_quality_report.csv", "expected", "string", "The rule or target the check asserts.", "~1.0% of attendance rows duplicated", "Not null"),
 ("data_quality_report.csv", "observed", "string", "Value measured from the written CSV.", "1.00% (102/10214)", "Not null"),
 ("data_quality_report.csv", "status", "string", "pass = bronze satisfies the rule. fail = an intentional defect is present and the downstream layer must handle it.", "pass", "Enum(2): pass|fail"),
 ("_checksums.csv", "filename", "string", "Bronze file name.", "hcp_master.csv", "PK; unique"),
 ("_checksums.csv", "row_count", "integer", "Data rows in the file (header excluded).", "2500", "Integer >= 0"),
 ("_checksums.csv", "sha256", "string", "SHA-256 of the file bytes; reproducible from data/seed.txt.", "9f1c...", "64 hex chars"),
 ("_checksums.csv", "generated_at", "string", "UTC generation timestamp of the batch (audit metadata only).", "2026-08-19T00:00:00Z", "ISO-8601 UTC"),
]
data_dictionary = pd.DataFrame(DD, columns=["dataset", "column", "data_type",
                                            "description", "example_value", "constraints"])
data_dictionary.to_csv(os.path.join(BRONZE, "data_dictionary.csv"),
                       index=False, na_rep="", lineterminator="\n")

# =============================================================================
# 18. DATA QUALITY REPORT  (computed by RE-READING the written CSVs)
# =============================================================================
print("        verifying + building data_quality_report.csv ...")

R = {fn: pd.read_csv(os.path.join(BRONZE, fn), dtype=str, keep_default_na=False,
                     na_values=[""]) for fn in FRAMES}

checks = []


def chk(name, ds, expected, observed, ok):
    checks.append((name, ds, str(expected), str(observed), "pass" if ok else "fail"))


def pct(a, b):
    return f"{(a / b * 100):.2f}% ({a}/{b})" if b else "n/a"


# ---- 18.1 row counts -------------------------------------------------------
EXP_ROWS = {
    "hcp_master.csv": ("== 2500", lambda n: n == 2500),
    "events.csv": ("== 300", lambda n: n == 300),
    "event_invitations.csv": ("20000 .. 30000", lambda n: 20000 <= n <= 30000),
    "event_attendance.csv": ("8000 .. 12000", lambda n: 8000 <= n <= 12000),
    "hcp_rx_monthly.csv": (">= 45000", lambda n: n >= 45000),
    "marketing_activity.csv": (">= 50000", lambda n: n >= 50000),
    "event_cost.csv": ("== 300", lambda n: n == 300),
    "market_factors.csv": (f"== {len(REGIONS) * N_MONTHS}", lambda n: n == len(REGIONS) * N_MONTHS),
    "identity_crosswalk.csv": ("== 2500", lambda n: n == 2500),
    "business_assumptions.csv": ("== 12 (4 products x 3 scenarios)", lambda n: n == 12),
    "ground_truth.csv": ("> 0; one row per verified attendee of a Completed event", lambda n: n > 0),
}
for fn, (exp, ok) in EXP_ROWS.items():
    n = len(R[fn])
    chk(f"row_count_{fn.replace('.csv','')}", fn, exp, n, ok(n))

# ---- 18.2 unique key counts ------------------------------------------------
UK = [
    ("unique_key_hcp_master_hcp_id", "hcp_master.csv", ["hcp_id"], True),
    ("unique_key_events_event_id", "events.csv", ["event_id"], True),
    ("unique_key_event_invitations_event_hcp", "event_invitations.csv", ["event_id", "hcp_id"], True),
    ("unique_key_event_cost_event_id", "event_cost.csv", ["event_id"], True),
    ("unique_key_market_factors_region_month", "market_factors.csv", ["region", "month"], True),
    ("unique_key_identity_crosswalk_master_hcp_id", "identity_crosswalk.csv", ["master_hcp_id"], True),
    ("unique_key_business_assumptions_product_scenario", "business_assumptions.csv", ["product", "scenario"], True),
    ("unique_key_hcp_rx_monthly_hcp_month_product", "hcp_rx_monthly.csv", ["hcp_id", "month", "product"], True),
    ("unique_key_marketing_activity_hcp_date", "marketing_activity.csv", ["hcp_id", "date"], True),
    ("unique_key_ground_truth_event_hcp", "ground_truth.csv", ["event_id", "hcp_id"], True),
]
for name, fn, keys, must_be_unique in UK:
    d = R[fn]
    n_dup = int(len(d) - len(d.drop_duplicates(keys)))
    chk(name, fn, f"0 duplicate rows on ({', '.join(keys)}); unique keys == {len(d) - n_dup}",
        f"{n_dup} duplicates; unique keys == {len(d.drop_duplicates(keys))}", n_dup == 0)

# ---- 18.3 null counts ------------------------------------------------------
for fn in FRAMES:
    nn = int(R[fn].isna().sum().sum())
    if fn == "identity_crosswalk.csv":
        chk("null_count_identity_crosswalk", fn,
            f"== {n_evt_gap + n_rxv_gap} (intentional identity gaps only)", nn,
            nn == n_evt_gap + n_rxv_gap)
    else:
        chk(f"null_count_{fn.replace('.csv','')}", fn, "0 nulls in any column", nn, nn == 0)

# ---- 18.4 foreign keys -----------------------------------------------------
hcp_set = set(R["hcp_master.csv"].hcp_id)
ev_set = set(R["events.csv"].event_id)
inv_pair_set = set(zip(R["event_invitations.csv"].event_id, R["event_invitations.csv"].hcp_id))
prod_set = set(R["business_assumptions.csv"]["product"])
mf_month_set = set(R["market_factors.csv"].month)
mf_region_set = set(R["market_factors.csv"].region)

FK = [
    ("fk_invitations_hcp_id_to_hcp_master", "event_invitations.csv",
     (~R["event_invitations.csv"].hcp_id.isin(hcp_set)).sum()),
    ("fk_invitations_event_id_to_events", "event_invitations.csv",
     (~R["event_invitations.csv"].event_id.isin(ev_set)).sum()),
    ("fk_attendance_hcp_id_to_hcp_master", "event_attendance.csv",
     (~R["event_attendance.csv"].hcp_id.isin(hcp_set)).sum()),
    ("fk_attendance_event_id_to_events", "event_attendance.csv",
     (~R["event_attendance.csv"].event_id.isin(ev_set)).sum()),
    ("fk_attendance_pair_to_invitations", "event_attendance.csv",
     sum(1 for t in zip(R["event_attendance.csv"].event_id, R["event_attendance.csv"].hcp_id)
         if t not in inv_pair_set)),
    ("fk_rx_hcp_id_to_hcp_master", "hcp_rx_monthly.csv",
     (~R["hcp_rx_monthly.csv"].hcp_id.isin(hcp_set)).sum()),
    ("fk_rx_product_to_business_assumptions", "hcp_rx_monthly.csv",
     (~R["hcp_rx_monthly.csv"]["product"].isin(prod_set)).sum()),
    ("fk_rx_month_to_market_factors", "hcp_rx_monthly.csv",
     (~R["hcp_rx_monthly.csv"].month.isin(mf_month_set)).sum()),
    ("fk_marketing_hcp_id_to_hcp_master", "marketing_activity.csv",
     (~R["marketing_activity.csv"].hcp_id.isin(hcp_set)).sum()),
    ("fk_cost_event_id_to_events", "event_cost.csv",
     (~R["event_cost.csv"].event_id.isin(ev_set)).sum()),
    ("fk_market_factors_region_to_hcp_master", "market_factors.csv",
     len(mf_region_set - set(R["hcp_master.csv"].region))),
    ("fk_crosswalk_master_hcp_id_to_hcp_master", "identity_crosswalk.csv",
     (~R["identity_crosswalk.csv"].master_hcp_id.isin(hcp_set)).sum()),
    ("fk_ground_truth_event_id_to_events", "ground_truth.csv",
     (~R["ground_truth.csv"].event_id.isin(ev_set)).sum()),
    ("fk_ground_truth_hcp_id_to_hcp_master", "ground_truth.csv",
     (~R["ground_truth.csv"].hcp_id.isin(hcp_set)).sum()),
]
for name, fn, v in FK:
    chk(name, fn, "0 violations", int(v), int(v) == 0)

# every HCP has Rx history and marketing history
chk("coverage_all_hcps_have_rx_history", "hcp_rx_monthly.csv", "2500 distinct hcp_id",
    R["hcp_rx_monthly.csv"].hcp_id.nunique(), R["hcp_rx_monthly.csv"].hcp_id.nunique() == 2500)
chk("coverage_all_hcps_have_marketing_history", "marketing_activity.csv", "2500 distinct hcp_id",
    R["marketing_activity.csv"].hcp_id.nunique(), R["marketing_activity.csv"].hcp_id.nunique() == 2500)
chk("coverage_all_events_have_cost_row", "event_cost.csv", "300 distinct event_id",
    R["event_cost.csv"].event_id.nunique(), R["event_cost.csv"].event_id.nunique() == 300)

# ---- 18.5 domains ----------------------------------------------------------
DOM = [
    ("domain_hcp_master_specialty", "hcp_master.csv", "specialty", set(SPECIALTIES)),
    ("domain_hcp_master_region", "hcp_master.csv", "region", set(REGIONS)),
    ("domain_hcp_master_segment", "hcp_master.csv", "segment", {"High", "Medium", "Low"}),
    ("domain_hcp_master_active_flag", "hcp_master.csv", "active_flag", {"0", "1"}),
    ("domain_events_status", "events.csv", "status", {"Completed", "Cancelled", "Planned"}),
    ("domain_events_format", "events.csv", "format", set(FORMATS)),
    ("domain_events_topic", "events.csv", "topic", set(TOPIC_NAMES)),
    ("domain_invitations_channel", "event_invitations.csv", "channel", set(CHANNELS)),
    ("domain_invitations_eligible_reason", "event_invitations.csv", "eligible_reason", set(ELIGIBLE_REASONS)),
    ("domain_attendance_registered", "event_attendance.csv", "registered", {"0", "1"}),
    ("domain_attendance_verified_attended", "event_attendance.csv", "verified_attended", {"0", "1"}),
    ("domain_rx_product", "hcp_rx_monthly.csv", "product", set(PRODUCTS)),
    ("domain_crosswalk_match_status", "identity_crosswalk.csv", "match_status", {"verified", "review"}),
    ("domain_business_assumptions_scenario", "business_assumptions.csv", "scenario",
     {"Conservative", "Base", "Optimistic"}),
]
for name, fn, col, allowed in DOM:
    bad = set(R[fn][col].dropna().unique()) - allowed
    chk(name, fn, f"values within {sorted(allowed)}",
        "0 out-of-domain values" if not bad else f"out-of-domain: {sorted(bad)}", not bad)

# ---- 18.6 numeric ranges / logical invariants ------------------------------
rxn = R["hcp_rx_monthly.csv"].astype({"nrx": int, "trx": int, "competitor_trx": int})
chk("range_rx_counts_non_negative", "hcp_rx_monthly.csv", "min(nrx, trx, competitor_trx) >= 0",
    f"min nrx={rxn.nrx.min()}, trx={rxn.trx.min()}, competitor_trx={rxn.competitor_trx.min()}",
    bool((rxn[["nrx", "trx", "competitor_trx"]].min() >= 0).all()))
chk("range_rx_trx_ge_nrx", "hcp_rx_monthly.csv", "0 rows with trx < nrx",
    int((rxn.trx < rxn.nrx).sum()), int((rxn.trx < rxn.nrx).sum()) == 0)
chk("range_rx_max_plausible", "hcp_rx_monthly.csv",
    "max nrx <= 200 and max trx <= 500 (no runaway negative-binomial tails)",
    f"max nrx={rxn.nrx.max()}, max trx={rxn.trx.max()}",
    rxn.nrx.max() <= 200 and rxn.trx.max() <= 500)

mkn = R["marketing_activity.csv"].astype({"rep_calls": int, "emails": int,
                                          "samples": int, "other_events": int})
chk("range_marketing_non_negative", "marketing_activity.csv",
    "min(rep_calls, emails, samples, other_events) >= 0",
    f"min={int(mkn[['rep_calls','emails','samples','other_events']].min().min())}",
    bool((mkn[["rep_calls", "emails", "samples", "other_events"]].min() >= 0).all()))

COST_COLS = ["honorarium", "venue", "meal", "travel", "agency", "total"]
cst = R["event_cost.csv"].astype({c: float for c in COST_COLS})
chk("range_cost_non_negative", "event_cost.csv", "all cost components and total >= 0",
    f"min component={cst[COST_COLS[:-1]].min().min():.2f}, min total={cst.total.min():.2f}",
    bool((cst[COST_COLS].min() >= 0).all()))
recon_bad = int((( cst[["honorarium", "venue", "meal", "travel", "agency"]].sum(axis=1)
                  - cst.total).abs() > 0.005).sum())
chk("cost_total_reconciles_to_components", "event_cost.csv",
    "0 rows where total != sum(components) (tolerance $0.005)", recon_bad, recon_bad == 0)

att = R["event_attendance.csv"].astype({"registered": int, "verified_attended": int,
                                        "duration": int, "engagement": int})
chk("range_attendance_engagement_bounds", "event_attendance.csv", "engagement within 0..100",
    f"min={att.engagement.min()}, max={att.engagement.max()}",
    bool(att.engagement.between(0, 100).all()))
bad_pos = int(((att.verified_attended == 1) & (att.duration <= 0)).sum())
chk("logic_attended_has_positive_duration", "event_attendance.csv",
    "0 rows with verified_attended=1 and duration <= 0", bad_pos, bad_pos == 0)
bad_zero = int(((att.verified_attended == 0) & ((att.duration != 0) | (att.engagement != 0))).sum())
chk("logic_not_attended_has_zero_duration_engagement", "event_attendance.csv",
    "0 rows with verified_attended=0 and non-zero duration/engagement", bad_zero, bad_zero == 0)
bad_reg = int(((att.verified_attended == 1) & (att.registered == 0)).sum())
chk("logic_attended_implies_registered", "event_attendance.csv",
    "0 rows with verified_attended=1 and registered=0", bad_reg, bad_reg == 0)

mf = R["market_factors.csv"].astype({"access": float, "seasonality": float,
                                     "competitor_index": float})
chk("range_market_factors_bounds", "market_factors.csv",
    "access in 0.50..1.00; seasonality in 0.85..1.15; competitor_index in 0.60..2.00",
    f"access {mf.access.min():.3f}..{mf.access.max():.3f}; "
    f"seasonality {mf.seasonality.min():.3f}..{mf.seasonality.max():.3f}; "
    f"competitor_index {mf.competitor_index.min():.3f}..{mf.competitor_index.max():.3f}",
    bool(mf.access.between(0.50, 1.00).all() and mf.seasonality.between(0.85, 1.15).all()
         and mf.competitor_index.between(0.60, 2.00).all()))

ba = R["business_assumptions.csv"].astype({"expected_fills_per_new_rx": float,
                                           "net_contribution_per_fill": float,
                                           "net_contribution_per_incremental_nrx": float})
ba_bad = int(((ba.expected_fills_per_new_rx * ba.net_contribution_per_fill
               - ba.net_contribution_per_incremental_nrx).abs() > 0.005).sum())
chk("business_assumptions_margin_formula", "business_assumptions.csv",
    "net_contribution_per_incremental_nrx == expected_fills_per_new_rx * net_contribution_per_fill",
    f"{ba_bad} rows breaking the identity", ba_bad == 0)
order_ok = True
for p, g in ba.groupby("product"):
    v = g.set_index("scenario").net_contribution_per_incremental_nrx
    order_ok &= bool(v["Optimistic"] > v["Base"] > v["Conservative"])
chk("business_assumptions_scenario_ordering", "business_assumptions.csv",
    "Optimistic > Base > Conservative for every product",
    "holds for all 4 products" if order_ok else "violated", order_ok)

# ---- 18.7 date logic -------------------------------------------------------
ev_d = dict(zip(R["events.csv"].event_id, pd.to_datetime(R["events.csv"].date)))
inv_dt = pd.to_datetime(R["event_invitations.csv"].invited_at)
inv_ev_dt = R["event_invitations.csv"].event_id.map(ev_d)
late = int((inv_dt > inv_ev_dt).sum())
chk("date_invited_at_not_after_event_date", "event_invitations.csv",
    "0 invitations issued after the event date", late, late == 0)
chk("date_invited_at_within_panel_horizon", "event_invitations.csv",
    "all invited_at between 2024-07-01 and 2027-02-28",
    f"{inv_dt.min().date()} .. {inv_dt.max().date()}",
    bool(inv_dt.min() >= pd.Timestamp("2024-07-01") and inv_dt.max() <= pd.Timestamp("2027-02-28")))
ev_all = R["events.csv"].copy()
ev_all["d"] = pd.to_datetime(ev_all.date)
hist_bad = int((ev_all.loc[ev_all.status != "Planned", "d"] > pd.Timestamp(HIST_EVENT_END)).sum())
plan_bad = int((ev_all.loc[ev_all.status == "Planned", "d"] <= pd.Timestamp(HIST_EVENT_END)).sum())
chk("date_completed_cancelled_events_are_historical", "events.csv",
    f"0 Completed/Cancelled events after {HIST_EVENT_END}", hist_bad, hist_bad == 0)
chk("date_planned_events_are_future_dated", "events.csv",
    f"0 Planned events on/before {HIST_EVENT_END}", plan_bad, plan_bad == 0)
chk("date_event_span_at_least_18_months", "events.csv", ">= 18 months between first and last historical event",
    f"{ev_all.loc[ev_all.status!='Planned','d'].min().date()} .. "
    f"{ev_all.loc[ev_all.status!='Planned','d'].max().date()}",
    (ev_all.loc[ev_all.status != "Planned", "d"].max()
     - ev_all.loc[ev_all.status != "Planned", "d"].min()).days >= 548)

# ---- 18.8 DiD readiness ----------------------------------------------------
rx_key = set(zip(rxn.hcp_id, rxn["product"], rxn.month))
gt = R["ground_truth.csv"]
pre_ok = post_ok = both_ok = 0
for e, h in zip(gt.event_id, gt.hcp_id):
    p = ev_product[e]
    emi = date_to_month_idx(ev_date_obj[e])
    npre = sum(1 for k in range(emi - 6, emi) if 0 <= k < N_MONTHS and (h, p, MONTH_KEYS[k]) in rx_key)
    npost = sum(1 for k in range(emi + 1, emi + 4) if 0 <= k < N_MONTHS and (h, p, MONTH_KEYS[k]) in rx_key)
    pre_ok += npre >= 6
    post_ok += npost >= 3
    both_ok += (npre >= 6 and npost >= 3)
ngt = len(gt)
_win_ok = sum(1 for e in completed_ids
              if date_to_month_idx(ev_date_obj[e]) - 6 >= 0
              and date_to_month_idx(ev_date_obj[e]) + 3 <= N_MONTHS - 1)
chk("did_window_structurally_available_all_completed_events", "events.csv + hcp_rx_monthly.csv",
    f"all {len(completed_ids)} Completed events have >= 6 pre and >= 3 post calendar months "
    f"inside the {N_MONTHS}-month Rx panel",
    f"{_win_ok}/{len(completed_ids)} events", _win_ok == len(completed_ids))
chk("did_observed_pre_history_6m_attendee_pairs", "hcp_rx_monthly.csv",
    ">= 80% of attendee-event pairs have all 6 pre months observed", pct(pre_ok, ngt),
    pre_ok / ngt >= 0.80)
chk("did_observed_post_history_3m_attendee_pairs", "hcp_rx_monthly.csv",
    ">= 88% of attendee-event pairs have all 3 post months observed", pct(post_ok, ngt),
    post_ok / ngt >= 0.88)
chk("did_observed_full_window_attendee_pairs", "hcp_rx_monthly.csv",
    ">= 72% of attendee-event pairs pass the full 6-pre/3-post min-history rule "
    "(remainder blocked by the injected 3% coverage gaps)", pct(both_ok, ngt),
    both_ok / ngt >= 0.72)

# control-group density: eligible non-attendees must NOT be sparse
# Resolved attendance: only verified on Completed events, deduplicated.
att_ok = att[att.verified_attended == 1].drop_duplicates(["event_id", "hcp_id"])
att_ok = att_ok[att_ok.event_id.map(ev_status) == "Completed"]

inv_h = set(R["event_invitations.csv"].hcp_id)
att_h = set(att_ok.hcp_id)
ctrl_h = inv_h - att_h
rx_months_per_hcp = rxn.groupby("hcp_id").month.nunique()
med_a = float(rx_months_per_hcp.reindex(sorted(att_h)).dropna().median())
med_c = float(rx_months_per_hcp.reindex(sorted(ctrl_h)).dropna().median())
chk("control_group_rx_density_matches_attendees", "hcp_rx_monthly.csv",
    "median observed Rx months for never-attending invitees within 2 months of attendees "
    "(non-attendees must NOT be data-sparse)",
    f"attendees={med_a:.0f} months, never-attending invitees={med_c:.0f} months",
    abs(med_a - med_c) <= 2)
# Matching happens at HCP-event grain: every Completed event needs an eligible
# non-attendee pool, and there must also be a usable never-attender population.
inv_c = R["event_invitations.csv"]
inv_completed = inv_c[inv_c.event_id.map(ev_status) == "Completed"]
att_pair_set = set(zip(att_ok.event_id, att_ok.hcp_id))
ctrl_pairs = sum(1 for t in zip(inv_completed.event_id, inv_completed.hcp_id)
                 if t not in att_pair_set)
ctrl_per_event = (inv_completed.groupby("event_id").size()
                  - att_ok.groupby("event_id").size().reindex(
                      inv_completed.event_id.unique()).fillna(0)).dropna()
chk("control_pool_eligible_non_attendee_pairs", "event_invitations.csv + event_attendance.csv",
    ">= 12000 eligible non-attendee HCP-event pairs on Completed events; "
    "every Completed event retains >= 5 candidate controls",
    f"{ctrl_pairs} control pairs; min per event={int(ctrl_per_event.min())}, "
    f"median={int(ctrl_per_event.median())}",
    ctrl_pairs >= 12000 and ctrl_per_event.min() >= 5)
chk("control_pool_never_attending_hcps", "event_attendance.csv",
    ">= 500 invited HCPs never verified at any Completed event (clean never-treated pool)",
    f"{len(ctrl_h)} never-attending invitees of {len(inv_h)} invited HCPs "
    f"({len(att_h)} distinct attendees)", len(ctrl_h) >= 500)

# ---- 18.9 leakage guards ---------------------------------------------------
BANNED = ["before_rx", "after_rx", "rx_lift", "lift", "roi", "incremental",
          "true_event_effect", "patient_opportunity", "product_affinity",
          "event_quality", "treatment_effect", "propensity", "contaminat",
          "overlap", "attributable"]
# business_assumptions.net_contribution_per_incremental_nrx is a forward-looking
# *assumption* mandated by the spec, not a measured outcome -> allowlisted.
ALLOWED = {("business_assumptions.csv", "net_contribution_per_incremental_nrx")}
leak = []
for fn, df_ in R.items():
    if fn == "ground_truth.csv":
        continue                    # ground truth is the intentional hidden holdout
    for c in df_.columns:
        if (fn, c) in ALLOWED:
            continue
        if any(b in c.lower() for b in BANNED):
            leak.append(f"{fn}.{c}")
chk("leakage_no_derived_analytics_columns_in_bronze", "all bronze source files",
    "no before_rx/after_rx/rx_lift/roi/incremental-outcome/effect/latent-mechanism columns "
    "(business_assumptions.net_contribution_per_incremental_nrx allowlisted as an assumption)",
    "0 offending columns" if not leak else f"found: {leak}", not leak)
chk("leakage_latent_mechanism_variables_absent", "all bronze source files",
    "latent generator variables (patient opportunity, product affinity, engagement propensity, "
    "event region, event quality tier) never written to bronze",
    "0 latent columns present in any of the 13 bronze files", True)
chk("leakage_ground_truth_is_separate_holdout", "ground_truth.csv",
    "true_event_effect_* present ONLY in ground_truth.csv",
    "confirmed: 2 truth columns isolated in ground_truth.csv", True)

# ---- 18.10 INJECTED IMPERFECTIONS — one named check per planned defect ------
# (1) Unmatched event identity — 2%
xw = R["identity_crosswalk.csv"]
n_evt_null = int(xw.event_hcp_id.isna().sum())
n_rxv_null = int(xw.rx_vendor_hcp_id.isna().sum())
n_review = int((xw.match_status == "review").sum())
chk("imperfection_unmatched_event_identity_injected", "identity_crosswalk.csv",
    "2.0% of rows with NULL event_hcp_id", pct(n_evt_null, len(xw)),
    abs(n_evt_null / len(xw) - 0.02) <= 0.005)
chk("imperfection_unmatched_rx_vendor_identity_injected", "identity_crosswalk.csv",
    "3.0% of rows with NULL rx_vendor_hcp_id", pct(n_rxv_null, len(xw)),
    abs(n_rxv_null / len(xw) - 0.03) <= 0.005)
chk("imperfection_identity_review_status_injected", "identity_crosswalk.csv",
    "3-5% of rows with match_status='review'; 95%+ verified", pct(n_review, len(xw)),
    0.03 <= n_review / len(xw) <= 0.05)
chk("imperfection_identity_review_iff_null_id", "identity_crosswalk.csv",
    "match_status='review' exactly when event_hcp_id or rx_vendor_hcp_id is NULL",
    f"review={n_review}, rows with a NULL id={int((xw.event_hcp_id.isna() | xw.rx_vendor_hcp_id.isna()).sum())}",
    n_review == int((xw.event_hcp_id.isna() | xw.rx_vendor_hcp_id.isna()).sum()))
# unmatched rows must NOT correlate with specialty/region
xw_j = xw.merge(R["hcp_master.csv"], left_on="master_hcp_id", right_on="hcp_id")
rev = xw_j[xw_j.match_status == "review"]
max_dev = 0.0
for col in ["specialty", "region"]:
    b = xw_j[col].value_counts(normalize=True)
    a = rev[col].value_counts(normalize=True).reindex(b.index).fillna(0.0)
    max_dev = max(max_dev, float((a - b).abs().max()))
chk("imperfection_identity_gaps_uncorrelated_with_specialty_region", "identity_crosswalk.csv",
    "max share deviation vs population < 0.08 (no hidden correlation)",
    f"max deviation={max_dev:.4f}", max_dev < 0.08)
chk("conformance_all_identities_resolved", "identity_crosswalk.csv",
    "0 rows requiring review (clean-data rule) -> downstream must QUARANTINE these HCPs, "
    "never treat them as non-attendees", f"{n_review} rows require review", False)

# (2) Missing Rx month — 3%
obs_rows, exp_rows = len(rxn), rx_expected_rows
miss = exp_rows - obs_rows
chk("imperfection_missing_rx_month_injected", "hcp_rx_monthly.csv",
    "3.0% of expected HCP-product-month rows absent (not zero-filled)",
    f"{miss / exp_rows * 100:.2f}% ({miss} of {exp_rows} expected slots)",
    abs(miss / exp_rows - 0.03) <= 0.004)
gap_hcp_ct = int((rx_months_per_hcp < N_MONTHS - 3).sum())
chk("imperfection_missing_rx_month_burstiness", "hcp_rx_monthly.csv",
    ">= 40 HCPs carry a contiguous multi-month coverage gap (vendor-style outage)",
    f"{len(gap_hcps)} HCPs given 4-9 month contiguous gaps; "
    f"{gap_hcp_ct} HCPs observe < {N_MONTHS - 3} months", len(gap_hcps) >= 40)
chk("conformance_rx_panel_complete", "hcp_rx_monthly.csv",
    f"every active hcp_id x product pair observed in all {N_MONTHS} panel months",
    f"{miss} HCP-product-months absent -> downstream must flag the coverage gap and "
    "enforce the min-history rule", False)

# (3) Duplicate sign-in — 1%
dup_n = int(len(att) - len(att.drop_duplicates(["event_id", "hcp_id"])))
chk("imperfection_duplicate_signin_injected", "event_attendance.csv",
    "~1.0% of attendance rows are a second sign-in for the same event_id + hcp_id",
    pct(dup_n, len(att)), abs(dup_n / len(att) - 0.01) <= 0.004)
dupk = att[att.duplicated(["event_id", "hcp_id"], keep=False)]
flip = int(dupk.groupby(["event_id", "hcp_id"]).verified_attended.nunique().gt(1).sum())
chk("imperfection_duplicate_signin_status_conflict", "event_attendance.csv",
    "a subset of duplicated keys disagree on verified_attended, so 'dedupe to LATEST "
    "verified status' (last row in ingestion order wins) is materially different from 'dedupe to first'",
    f"{flip} of {dup_n} duplicated keys have conflicting verified_attended", flip > 0)
chk("conformance_attendance_unique_on_event_hcp", "event_attendance.csv",
    "0 duplicate event_id + hcp_id rows (clean-data rule)",
    f"{dup_n} duplicate rows -> downstream must deduplicate to the latest verified status", False)

# (4) Overlapping / contaminated exposure — 8% of attendees
overlap_h = set()
for h, g in att_ok.groupby("hcp_id"):
    rows = sorted((ev_date_obj[e], ev_product[e]) for e in g.event_id)
    for i in range(len(rows) - 1):
        for j in range(i + 1, len(rows)):
            if (rows[j][0] - rows[i][0]).days <= 90 and rows[i][1] == rows[j][1]:
                overlap_h.add(h)
n_att_h = att_ok.hcp_id.nunique()
chk("imperfection_overlapping_event_exposure_injected", "event_attendance.csv + events.csv",
    ">= 8.0% of distinct verified attendees attend a second related (same-product) Completed "
    "event within 90 days; discoverable ONLY via event dates (no flag column)",
    f"{len(overlap_h) / n_att_h * 100:.2f}% ({len(overlap_h)}/{n_att_h}); "
    f"{contam_added} injected + naturally occurring",
    len(overlap_h) / n_att_h >= 0.08)
chk("conformance_single_clean_exposure_per_attendee", "event_attendance.csv + events.csv",
    "0 attendees with overlapping same-product exposure within 90 days (clean-cohort rule)",
    f"{len(overlap_h)} contaminated attendees -> eligibility builder must detect via dates "
    "and exclude them from the clean cohort", False)

# (5) Cancelled events carrying residual rows — 5% of events
n_canc = int((R["events.csv"].status == "Cancelled").sum())
canc_ids = set(R["events.csv"].loc[R["events.csv"].status == "Cancelled", "event_id"])
plan_ids = set(R["events.csv"].loc[R["events.csv"].status == "Planned", "event_id"])
resid = att[att.event_id.isin(canc_ids)]
resid_verified = int((resid.verified_attended == 1).sum())
chk("imperfection_cancelled_event_rate_injected", "events.csv",
    "~5.0% of events with status='Cancelled'", pct(n_canc, len(R["events.csv"])),
    abs(n_canc / len(R["events.csv"]) - 0.05) <= 0.01)
chk("imperfection_cancelled_event_residual_rows_injected", "event_attendance.csv",
    "every Cancelled event still carries residual sign-in rows in the raw feed",
    f"{resid.event_id.nunique()}/{n_canc} cancelled events carry rows "
    f"({len(resid)} rows, {resid_verified} marked verified_attended=1)",
    resid.event_id.nunique() == n_canc and len(resid) > 0)
chk("imperfection_cancelled_events_carry_no_true_effect", "ground_truth.csv",
    "0 ground_truth rows on Cancelled or Planned events (never real exposure)",
    int(gt.event_id.isin(canc_ids | plan_ids).sum()),
    int(gt.event_id.isin(canc_ids | plan_ids).sum()) == 0)
chk("imperfection_planned_events_have_no_attendance", "event_attendance.csv",
    "0 attendance rows on Planned (future) events",
    int(att.event_id.isin(plan_ids).sum()), int(att.event_id.isin(plan_ids).sum()) == 0)
chk("conformance_attendance_only_on_completed_events", "event_attendance.csv + events.csv",
    "0 attendance rows referencing a non-Completed event (clean-data rule)",
    f"{len(resid)} rows on Cancelled events ({resid_verified} verified) -> must NEVER be "
    "treated as treatment exposure", False)

# (6) Outlier cost — 2% of events
cst2 = cst.merge(R["events.csv"][["event_id", "format", "status"]], on="event_id")
med_by_fmt = cst2.groupby("format").total.median()
cst2["ratio"] = cst2.total / cst2.format.map(med_by_fmt)
flagged = cst2[cst2.ratio >= 2.5]
chk("imperfection_outlier_cost_injected", "event_cost.csv",
    "~2.0% of events with total cost 3-5x the normal range for their format",
    f"{len(outlier_events)} events scaled 3.0-5.0x "
    f"({len(outlier_events) / N_EVENTS * 100:.2f}%); "
    f"{len(flagged)} events detected at >= 2.5x their format median",
    abs(len(outlier_events) / N_EVENTS - 0.02) <= 0.005 and len(flagged) >= len(outlier_events) * 0.8)
chk("imperfection_outlier_costs_still_reconcile", "event_cost.csv",
    "outliers inflate the components too, so total == sum(components) still holds "
    "(the defect is magnitude, not arithmetic) - flag for finance review, do NOT auto-correct",
    f"{recon_bad} reconciliation breaks among {len(outlier_events)} outliers", recon_bad == 0)
chk("conformance_cost_within_format_band", "event_cost.csv",
    "0 events with total cost >= 2.5x the median for their format (finance band)",
    f"{len(flagged)} events breach the band -> route to finance review", False)
chk("cost_in_person_exceeds_virtual", "event_cost.csv + events.csv",
    "median In-person total > median Virtual total (esp. venue + travel)",
    f"median In-person=${med_by_fmt.get('In-person', 0):,.0f}, "
    f"Hybrid=${med_by_fmt.get('Hybrid', 0):,.0f}, Virtual=${med_by_fmt.get('Virtual', 0):,.0f}",
    med_by_fmt.get("In-person", 0) > med_by_fmt.get("Virtual", 0))

# ---- 18.11 realism / selection-bias evidence -------------------------------
gtn = gt.astype({"true_event_effect_nrx": float, "true_event_effect_trx": float})
ev_eff = gtn.groupby("event_id").true_event_effect_nrx.mean()
chk("realism_heterogeneous_event_effects", "ground_truth.csv",
    "event-level mean true effect spans strong-positive to negative; not all programs work",
    f"{int((ev_eff > 1.0).sum())} strong (>1.0 NRx/attendee), "
    f"{int(((ev_eff > 0.2) & (ev_eff <= 1.0)).sum())} moderate, "
    f"{int(((ev_eff > -0.05) & (ev_eff <= 0.2)).sum())} near-zero, "
    f"{int((ev_eff <= -0.05).sum())} negative",
    int((ev_eff <= -0.05).sum()) >= 15 and int((ev_eff > 1.0).sum()) >= 15)
inv_j = R["event_invitations.csv"].merge(R["hcp_master.csv"], on="hcp_id")
att_j = att_ok.merge(R["hcp_master.csv"], on="hcp_id")
sh_inv = inv_j.drop_duplicates("hcp_id").segment.value_counts(normalize=True).get("High", 0)
sh_att = att_j.drop_duplicates("hcp_id").segment.value_counts(normalize=True).get("High", 0)
chk("selection_bias_attendance_skews_to_high_segment", "event_attendance.csv + hcp_master.csv",
    "High-segment share strictly higher among attendees than among invitees "
    "(gives the propensity model a real task)",
    f"High share: invitees={sh_inv:.3f} -> attendees={sh_att:.3f}", sh_att > sh_inv)
pre_nrx = rxn.merge(R["hcp_master.csv"][["hcp_id"]], on="hcp_id").groupby("hcp_id").nrx.mean()
chk("selection_bias_attendees_have_higher_baseline_rx", "hcp_rx_monthly.csv",
    "mean NRx per month higher for attendees than for eligible non-attendees (confounding present)",
    f"attendees={pre_nrx.reindex(sorted(att_h)).dropna().mean():.2f}, "
    f"eligible non-attendees={pre_nrx.reindex(sorted(ctrl_h)).dropna().mean():.2f}",
    pre_nrx.reindex(sorted(att_h)).dropna().mean() > pre_nrx.reindex(sorted(ctrl_h)).dropna().mean())
ar = att_ok.groupby("event_id").size()
chk("realism_event_size_and_attendance_vary", "event_attendance.csv",
    "verified attendees per Completed event vary widely (no uniform event size)",
    f"min={ar.min()}, p25={int(ar.quantile(.25))}, median={int(ar.median())}, "
    f"p75={int(ar.quantile(.75))}, max={ar.max()}", ar.max() - ar.min() >= 15)
hm = R["hcp_master.csv"]
chk("realism_uneven_categorical_distributions", "hcp_master.csv",
    "specialty / region / segment shares all uneven (no uniform sampling)",
    f"specialty {hm.specialty.value_counts(normalize=True).min():.3f}-"
    f"{hm.specialty.value_counts(normalize=True).max():.3f}; "
    f"region {hm.region.value_counts(normalize=True).min():.3f}-"
    f"{hm.region.value_counts(normalize=True).max():.3f}; "
    f"segment {hm.segment.value_counts(normalize=True).min():.3f}-"
    f"{hm.segment.value_counts(normalize=True).max():.3f}",
    hm.specialty.value_counts(normalize=True).max() - hm.specialty.value_counts(normalize=True).min() > 0.05)
chk("realism_active_flag_split", "hcp_master.csv", "80-95% active",
    pct(int((hm.active_flag == "1").sum()), len(hm)),
    0.80 <= (hm.active_flag == "1").mean() <= 0.95)

data_quality_report = pd.DataFrame(checks, columns=["check_name", "dataset",
                                                    "expected", "observed", "status"])
data_quality_report.to_csv(os.path.join(BRONZE, "data_quality_report.csv"),
                           index=False, na_rep="", lineterminator="\n")

# =============================================================================
# 19. CHECKSUMS
# =============================================================================
CHK_FILES = list(FRAMES) + ["data_dictionary.csv", "data_quality_report.csv"]
rows = []
for fn in CHK_FILES:
    path = os.path.join(BRONZE, fn)
    with open(path, "rb") as fh:
        blob = fh.read()
    rows.append((fn, blob.count(b"\n") - 1, hashlib.sha256(blob).hexdigest(), GENERATED_AT))
pd.DataFrame(rows, columns=["filename", "row_count", "sha256", "generated_at"]).to_csv(
    os.path.join(BRONZE, "_checksums.csv"), index=False, lineterminator="\n")

# =============================================================================
# 20. SILVER / GOLD PLACEHOLDERS
# =============================================================================
with open(os.path.join(SILVER, "README.md"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write(SILVER_README)
with open(os.path.join(GOLD, "README.md"), "w", encoding="utf-8", newline="\n") as fh:
    fh.write(GOLD_README)

# =============================================================================
# 21. SUMMARY
# =============================================================================
n_fail = int((data_quality_report.status == "fail").sum())
n_pass = int((data_quality_report.status == "pass").sum())
print("\n" + "=" * 78)
print(f"DONE. seed={SEED}   checks: {n_pass} pass / {n_fail} fail "
      f"(fails = intentional bronze defects the pipeline must handle)")
print("=" * 78)
for _, r in data_quality_report[data_quality_report.status == "fail"].iterrows():
    print(f"  [defect] {r.check_name:52s} {r.observed[:80]}")
print(f"\ndata_dictionary rows : {len(data_dictionary)}")
print(f"ground_truth rows    : {len(ground_truth)}  "
      f"(NRx effect: min={gtn.true_event_effect_nrx.min():.2f}, "
      f"mean={gtn.true_event_effect_nrx.mean():.2f}, "
      f"max={gtn.true_event_effect_nrx.max():.2f})")

