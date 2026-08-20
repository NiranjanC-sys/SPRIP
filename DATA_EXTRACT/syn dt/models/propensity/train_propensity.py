"""
=============================================================================
 Propensity Model + Attendee-Control Matching
 Reads:  data/gold/hcp_event_features.csv
 Writes: data/gold/matched_pairs.csv
         data/gold/propensity_diagnostics.csv
=============================================================================
"""

from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import LabelEncoder

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD = os.path.join(ROOT, "data", "gold")

CALIPER = 0.05
MAX_CONTROLS_PER_TREATED = 2

NUMERIC_FEATURES = [
    "avg_nrx_3m", "avg_nrx_6m", "avg_trx_3m", "avg_trx_6m",
    "nrx_trend", "competitor_trx_avg",
    "rep_calls_3m", "emails_3m", "samples_3m",
    "prior_event_count", "specialty_topic_match",
    "access_index", "seasonality_index", "competitor_index",
]

CATEGORICAL_FEATURES = ["segment", "specialty", "region"]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def smd(treated: pd.Series, control: pd.Series) -> float:
    m1, m0 = treated.mean(), control.mean()
    s1, s0 = treated.std(), control.std()
    denom = np.sqrt((s1**2 + s0**2) / 2.0)
    if denom < 1e-9:
        return 0.0
    return abs(m1 - m0) / denom


def main():
    print("=" * 68)
    print("PROPENSITY MODEL + MATCHING")
    print("=" * 68)

    # ---- Load features ------------------------------------------------------
    print("\nLoading hcp_event_features.csv ...")
    df = pd.read_csv(os.path.join(GOLD, "hcp_event_features.csv"), dtype=str)
    for c in NUMERIC_FEATURES:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["target"] = (df["group"] == "treatment").astype(int)
    print(f"    Rows: {len(df):,}  (treatment={int(df.target.sum()):,}, "
          f"control={int((df.target == 0).sum()):,})")

    # ---- Encode categoricals ------------------------------------------------
    label_encoders = {}
    for c in CATEGORICAL_FEATURES:
        le = LabelEncoder()
        df[c + "_enc"] = le.fit_transform(df[c].fillna("MISSING"))
        label_encoders[c] = le

    feature_cols = NUMERIC_FEATURES + [c + "_enc" for c in CATEGORICAL_FEATURES]

    X = df[feature_cols].copy()
    X[NUMERIC_FEATURES] = X[NUMERIC_FEATURES].fillna(X[NUMERIC_FEATURES].median())
    y = df["target"].values
    groups = df["event_id"].values

    # ---- Grouped cross-validation (group = event_id) -------------------------
    print("\nTraining XGBoost with grouped 5-fold CV ...")
    gkf = GroupKFold(n_splits=5)
    oof_scores = np.full(len(df), np.nan)
    fold_aucs = []

    for fold, (train_idx, val_idx) in enumerate(gkf.split(X, y, groups), 1):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=10,
            scale_pos_weight=(y_tr == 0).sum() / max((y_tr == 1).sum(), 1),
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
            enable_categorical=False,
        )
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_val)[:, 1]
        oof_scores[val_idx] = proba
        fauc = roc_auc_score(y_val, proba)
        fold_aucs.append(fauc)
        print(f"    Fold {fold}: AUC = {fauc:.4f}")

    overall_auc = roc_auc_score(y, oof_scores)
    print(f"    Overall OOF AUC: {overall_auc:.4f}")

    df["propensity_score"] = oof_scores

    # ---- Train final model on full data for feature importance ---------------
    final_model = xgb.XGBClassifier(
        n_estimators=300, max_depth=5, learning_rate=0.05, subsample=0.8,
        colsample_bytree=0.8, min_child_weight=10,
        scale_pos_weight=(y == 0).sum() / max((y == 1).sum(), 1),
        eval_metric="logloss", random_state=42, verbosity=0,
    )
    final_model.fit(X, y)
    imp = pd.Series(final_model.feature_importances_, index=feature_cols)
    print("\n    Top 10 features by importance:")
    for feat, val in imp.sort_values(ascending=False).head(10).items():
        print(f"        {feat:30s} {val:.4f}")

    # ---- Matching: within-event nearest-neighbor on composite distance --------
    print(f"\nMatching (caliper={CALIPER}, max {MAX_CONTROLS_PER_TREATED} controls/treated) ...")

    BALANCE_COLS = [
        "propensity_score", "avg_nrx_6m", "avg_trx_6m",
        "competitor_trx_avg", "rep_calls_3m", "samples_3m",
        "prior_event_count", "segment_enc",
    ]

    _bal = df[BALANCE_COLS].copy().fillna(df[BALANCE_COLS].median())
    _bal_std = _bal.std().replace(0, 1)
    df_z = ((_bal - _bal.mean()) / _bal_std).values

    treated = df[df["target"] == 1].copy()
    control = df[df["target"] == 0].copy()

    match_rows = []
    n_matched_treated = 0
    n_discarded_treated = 0

    for eid, t_grp in treated.groupby("event_id"):
        c_grp = control[control["event_id"] == eid].copy()
        if c_grp.empty:
            n_discarded_treated += len(t_grp)
            continue

        c_available = set(c_grp.index.tolist())

        for _, t_row in t_grp.iterrows():
            ps_t = t_row["propensity_score"]
            spec_t = t_row["specialty"]
            reg_t = t_row["region"]
            t_idx = t_row.name

            c_avail_arr = np.array(list(c_available))
            if len(c_avail_arr) == 0:
                n_discarded_treated += 1
                continue

            c_ps = df.loc[c_avail_arr, "propensity_score"].values
            cal_mask = np.abs(c_ps - ps_t) <= CALIPER
            if not cal_mask.any():
                n_discarded_treated += 1
                continue

            ci_valid = c_avail_arr[cal_mask]
            t_vec = df_z[t_idx]
            c_vecs = df_z[ci_valid]
            composite_dist = np.sqrt(((c_vecs - t_vec) ** 2).sum(axis=1))

            exact_bonus = np.zeros(len(ci_valid))
            specs = df.loc[ci_valid, "specialty"].values
            regs = df.loc[ci_valid, "region"].values
            exact_bonus += 0.3 * (specs == spec_t)
            exact_bonus += 0.2 * (regs == reg_t)
            rank_dist = composite_dist - exact_bonus

            n_take = min(MAX_CONTROLS_PER_TREATED, len(ci_valid))
            best_order = np.argsort(rank_dist)[:n_take]
            best_ci = ci_valid[best_order]

            w = round(1.0 / n_take, 4)
            for ci in best_ci:
                c_row = df.loc[ci]
                match_rows.append({
                    "master_hcp_id_treated": t_row["master_hcp_id"],
                    "event_id": eid,
                    "master_hcp_id_control": c_row["master_hcp_id"],
                    "propensity_score_treated": round(ps_t, 6),
                    "propensity_score_control": round(c_row["propensity_score"], 6),
                    "match_weight": w,
                })
                c_available.discard(int(ci))

            n_matched_treated += 1

    matched = pd.DataFrame(match_rows)
    matched.to_csv(os.path.join(GOLD, "matched_pairs.csv"), index=False)

    retention = n_matched_treated / (n_matched_treated + n_discarded_treated) * 100

    print(f"    Treated matched:   {n_matched_treated:,}")
    print(f"    Treated discarded: {n_discarded_treated:,} (no match within caliper)")
    print(f"    Retention rate:    {retention:.1f}%")
    print(f"    Match pairs:       {len(matched):,}")

    # ---- Post-match balance (SMD before vs after) ----------------------------
    print("\nComputing balance diagnostics ...")

    matched_t_ids = set(zip(matched["master_hcp_id_treated"], matched["event_id"]))
    matched_c_ids = set(zip(matched["master_hcp_id_control"], matched["event_id"]))

    df["_pair"] = list(zip(df["master_hcp_id"], df["event_id"]))
    before_t = df[df["target"] == 1]
    before_c = df[df["target"] == 0]
    after_t = df[df["_pair"].isin(matched_t_ids) & (df["target"] == 1)]
    after_c = df[df["_pair"].isin(matched_c_ids) & (df["target"] == 0)]

    diag_rows = []
    balance_pass_count = 0
    balance_total = 0

    check_cols = NUMERIC_FEATURES + [c + "_enc" for c in CATEGORICAL_FEATURES]
    for c in check_cols:
        smd_before = smd(before_t[c].dropna(), before_c[c].dropna())
        smd_after = smd(after_t[c].dropna(), after_c[c].dropna())
        passed = smd_after < 0.10
        balance_total += 1
        if passed:
            balance_pass_count += 1
        diag_rows.append({
            "metric": f"smd_{c}",
            "value_before_matching": round(smd_before, 4),
            "value_after_matching": round(smd_after, 4),
            "threshold": 0.10,
            "passed": passed,
        })

    # Add overall metrics
    diag_rows.insert(0, {
        "metric": "model_auc_oof",
        "value_before_matching": round(overall_auc, 4),
        "value_after_matching": None,
        "threshold": None,
        "passed": None,
    })
    diag_rows.append({
        "metric": "n_treated_matched",
        "value_before_matching": int(df.target.sum()),
        "value_after_matching": n_matched_treated,
        "threshold": None,
        "passed": None,
    })
    diag_rows.append({
        "metric": "n_treated_discarded",
        "value_before_matching": 0,
        "value_after_matching": n_discarded_treated,
        "threshold": None,
        "passed": None,
    })
    diag_rows.append({
        "metric": "retention_rate_pct",
        "value_before_matching": 100.0,
        "value_after_matching": round(retention, 2),
        "threshold": None,
        "passed": None,
    })
    diag_rows.append({
        "metric": "n_match_pairs",
        "value_before_matching": None,
        "value_after_matching": len(matched),
        "threshold": None,
        "passed": None,
    })

    diag = pd.DataFrame(diag_rows)
    diag.to_csv(os.path.join(GOLD, "propensity_diagnostics.csv"), index=False)

    # ---- Print summary -------------------------------------------------------
    features_improved = sum(1 for _, r in diag.iterrows()
                           if r["metric"].startswith("smd_")
                           and r["value_after_matching"] is not None
                           and r["value_before_matching"] is not None
                           and r["value_after_matching"] < r["value_before_matching"])
    features_total_smd = sum(1 for _, r in diag.iterrows() if r["metric"].startswith("smd_"))

    print(f"\n{'='*68}")
    print(f"PROPENSITY MODEL + MATCHING COMPLETE")
    print(f"{'='*68}")
    print(f"    Model AUC (OOF):           {overall_auc:.4f}")
    print(f"    Treated matched:           {n_matched_treated:,} / {int(df.target.sum()):,}")
    print(f"    Treated discarded:         {n_discarded_treated:,}")
    print(f"    Retention rate:            {retention:.1f}%")
    print(f"    Match pairs written:       {len(matched):,}")
    print(f"\n    Post-match balance (SMD < 0.10):")
    print(f"        Features passing:      {balance_pass_count} / {balance_total}")
    print(f"        Features improved:     {features_improved} / {features_total_smd}")
    print(f"\n    SMD detail (before -> after):")
    for _, r in diag[diag["metric"].str.startswith("smd_")].iterrows():
        name = r["metric"].replace("smd_", "")
        flag = "PASS" if r["passed"] else "FAIL"
        print(f"        {name:30s} {r['value_before_matching']:.4f} -> "
              f"{r['value_after_matching']:.4f}  [{flag}]")

    overall_pass = balance_pass_count == balance_total
    print(f"\n    BALANCE CHECK {'PASSED' if overall_pass else 'PARTIALLY PASSED'}: "
          f"{balance_pass_count}/{balance_total} features below SMD 0.10 threshold")
    print(f"\n    Outputs:")
    print(f"        {os.path.join(GOLD, 'matched_pairs.csv')}")
    print(f"        {os.path.join(GOLD, 'propensity_diagnostics.csv')}")


if __name__ == "__main__":
    main()
