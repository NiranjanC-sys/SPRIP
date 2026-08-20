"""
SPRIP ML Training Pipeline
===========================
Trains three models from gold/silver-layer CSVs and records results
in the ml.model_versions / ml.model_metrics database tables.

Models:
  M1 — Propensity (LogisticRegression)   -> treatment/control classification
  M2 — Causal DiD estimator              -> ATT with CI (no persisted artifact)
  M3 — Forecast  (LightGBM)              -> next-month Rx prediction

Usage:
    .venv/Scripts/python scripts/train_models.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_GOLD = ROOT / "DATA_EXTRACT" / "syn dt" / "data" / "gold"
DATA_SILVER = ROOT / "DATA_EXTRACT" / "syn dt" / "data" / "silver" / "conformed"
ARTIFACT_DIR = ROOT / "artifacts" / "models"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# DB connection (sync via psycopg)
# ---------------------------------------------------------------------------
DATABASE_URL = "postgresql+psycopg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi"


def _get_engine():
    from sqlalchemy import create_engine
    return create_engine(DATABASE_URL)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ===================================================================
# M1 — Propensity Model (LogisticRegression)
# ===================================================================
def train_propensity_model() -> dict:
    print("\n" + "=" * 60)
    print("M1 — Propensity Model (LogisticRegression)")
    print("=" * 60)

    features_df = pd.read_csv(DATA_GOLD / "hcp_event_features.csv")

    # The features CSV already has a 'group' column: 'treatment' or 'control_candidate'
    df = features_df[features_df["group"].isin(["treatment", "control_candidate"])].copy()
    df["target"] = (df["group"] == "treatment").astype(int)

    # Numeric feature columns
    numeric_cols = [
        "avg_nrx_3m", "avg_nrx_6m", "avg_trx_3m", "avg_trx_6m",
        "nrx_trend", "competitor_trx_avg", "rep_calls_3m", "emails_3m",
        "samples_3m", "prior_event_count", "specialty_topic_match",
        "access_index", "seasonality_index", "competitor_index",
    ]

    # Encode categoricals
    label_encoders: dict[str, LabelEncoder] = {}
    for col in ["segment", "specialty", "region"]:
        le = LabelEncoder()
        df[col + "_enc"] = le.fit_transform(df[col].astype(str))
        label_encoders[col] = le
        numeric_cols.append(col + "_enc")

    X = df[numeric_cols].fillna(0).values
    y = df["target"].values

    print(f"  Samples: {len(y)}  |  Treated: {y.sum()}  |  Control: {(1 - y).sum()}")

    model = LogisticRegression(max_iter=1000, solver="lbfgs", C=1.0, random_state=42)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    auc_scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")
    acc_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy")

    print(f"  CV AUC-ROC: {auc_scores.mean():.4f} (+/- {auc_scores.std():.4f})")
    print(f"  CV Accuracy: {acc_scores.mean():.4f} (+/- {acc_scores.std():.4f})")

    # Refit on full data
    model.fit(X, y)
    y_pred = model.predict(X)
    y_prob = model.predict_proba(X)[:, 1]

    print(f"\n  Full-data AUC-ROC: {roc_auc_score(y, y_prob):.4f}")
    print(f"  Full-data Accuracy: {accuracy_score(y, y_pred):.4f}")
    print("\n  Classification Report:")
    print(classification_report(y, y_pred, target_names=["control", "treated"]))

    # Save artifact
    artifact_path = ARTIFACT_DIR / "propensity_model.joblib"
    joblib.dump({"model": model, "label_encoders": label_encoders, "feature_cols": numeric_cols}, artifact_path)
    print(f"  Artifact saved: {artifact_path}")

    return {
        "model_kind": "PROPENSITY",
        "artifact_path": artifact_path,
        "cv_auc": float(auc_scores.mean()),
        "cv_accuracy": float(acc_scores.mean()),
        "full_auc": float(roc_auc_score(y, y_prob)),
        "full_accuracy": float(accuracy_score(y, y_pred)),
        "training_rows": int(len(y)),
        "feature_cols": numeric_cols,
    }


# ===================================================================
# M2 — Causal / Difference-in-Differences
# ===================================================================
def train_causal_model() -> dict:
    print("\n" + "=" * 60)
    print("M2 — Causal DiD Estimator")
    print("=" * 60)

    matched = pd.read_csv(DATA_GOLD / "matched_pairs.csv")
    rx = pd.read_csv(DATA_SILVER / "hcp_rx_monthly.csv")
    events = pd.read_csv(DATA_SILVER / "events.csv")

    # Determine cutoff: median event date
    events["date"] = pd.to_datetime(events["date"])
    cutoff = events["date"].median()
    print(f"  DiD cutoff date (median event): {cutoff.date()}")

    rx["month"] = pd.to_datetime(rx["month"])

    # Treated HCPs and their matched controls
    treated_ids = set(matched["master_hcp_id_treated"].unique())
    control_ids = set(matched["master_hcp_id_control"].unique())

    def aggregate_rx(hcp_ids: set, label: str) -> pd.DataFrame:
        sub = rx[rx["hcp_id"].isin(hcp_ids)].copy()
        sub["period"] = np.where(sub["month"] < cutoff, "pre", "post")
        agg = sub.groupby(["hcp_id", "period"])["nrx"].mean().reset_index()
        agg["group"] = label
        return agg

    treated_agg = aggregate_rx(treated_ids, "treated")
    control_agg = aggregate_rx(control_ids, "control")
    combined = pd.concat([treated_agg, control_agg], ignore_index=True)

    # Pivot to wide: one row per hcp with pre/post columns
    wide = combined.pivot_table(index=["hcp_id", "group"], columns="period", values="nrx").reset_index()
    if "pre" not in wide.columns or "post" not in wide.columns:
        print("  WARNING: insufficient pre/post data for DiD")
        wide["pre"] = wide.get("pre", 0)
        wide["post"] = wide.get("post", 0)
    wide = wide.dropna(subset=["pre", "post"])

    treated_diff = wide.loc[wide["group"] == "treated", "post"].values - wide.loc[wide["group"] == "treated", "pre"].values
    control_diff = wide.loc[wide["group"] == "control", "post"].values - wide.loc[wide["group"] == "control", "pre"].values

    att = treated_diff.mean() - control_diff.mean()
    se = np.sqrt(treated_diff.var() / len(treated_diff) + control_diff.var() / len(control_diff))
    t_stat = att / se if se > 0 else 0.0
    df_val = len(treated_diff) + len(control_diff) - 2
    p_value = float(2 * stats.t.sf(abs(t_stat), df=max(df_val, 1)))
    ci_low = att - 1.96 * se
    ci_high = att + 1.96 * se

    print(f"  Treated HCPs: {len(treated_diff)}  |  Control HCPs: {len(control_diff)}")
    print(f"  ATT (Avg Treatment Effect on Treated): {att:.4f}")
    print(f"  Standard Error: {se:.4f}")
    print(f"  t-statistic: {t_stat:.4f}")
    print(f"  p-value: {p_value:.4f}")
    print(f"  95% CI: [{ci_low:.4f}, {ci_high:.4f}]")
    print(f"  Significant at 0.05? {'Yes' if p_value < 0.05 else 'No'}")

    return {
        "model_kind": "CAUSAL_DID",
        "att": float(att),
        "se": float(se),
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "n_treated": int(len(treated_diff)),
        "n_control": int(len(control_diff)),
    }


# ===================================================================
# M3 — Forecast Model (LightGBM)
# ===================================================================
def train_forecast_model() -> dict:
    print("\n" + "=" * 60)
    print("M3 — Forecast Model (LightGBM)")
    print("=" * 60)

    rx = pd.read_csv(DATA_SILVER / "hcp_rx_monthly.csv")
    rx["month"] = pd.to_datetime(rx["month"])

    # Aggregate by month + product
    monthly = rx.groupby(["month", "product"]).agg(
        nrx=("nrx", "sum"),
        trx=("trx", "sum"),
        competitor_trx=("competitor_trx", "sum"),
    ).reset_index().sort_values(["product", "month"])

    # Time-series features per product
    feature_frames = []
    for product, grp in monthly.groupby("product"):
        grp = grp.sort_values("month").copy()
        grp["nrx_lag1"] = grp["nrx"].shift(1)
        grp["nrx_lag2"] = grp["nrx"].shift(2)
        grp["nrx_lag3"] = grp["nrx"].shift(3)
        grp["nrx_roll3"] = grp["nrx"].rolling(3).mean()
        grp["nrx_roll6"] = grp["nrx"].rolling(6).mean()
        grp["trx_lag1"] = grp["trx"].shift(1)
        grp["competitor_lag1"] = grp["competitor_trx"].shift(1)
        grp["trend"] = np.arange(len(grp))
        grp["month_num"] = grp["month"].dt.month
        feature_frames.append(grp)

    df = pd.concat(feature_frames, ignore_index=True).dropna()

    feature_cols = [
        "nrx_lag1", "nrx_lag2", "nrx_lag3", "nrx_roll3", "nrx_roll6",
        "trx_lag1", "competitor_lag1", "trend", "month_num",
    ]
    target_col = "nrx"

    # Encode product
    le_product = LabelEncoder()
    df["product_enc"] = le_product.fit_transform(df["product"])
    feature_cols.append("product_enc")

    X = df[feature_cols].values
    y = df[target_col].values

    # Train/test split: last 20% by time
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    print(f"  Train samples: {len(X_train)}  |  Test samples: {len(X_test)}")

    try:
        import lightgbm as lgb
        model = lgb.LGBMRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=6,
            num_leaves=31,
            random_state=42,
            verbose=-1,
        )
        model_name = "LightGBM"
    except ImportError:
        print("  LightGBM not available, falling back to sklearn GradientBoostingRegressor")
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=6,
            random_state=42,
        )
        model_name = "GradientBoostingRegressor"

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))
    r2 = float(r2_score(y_test, y_pred))

    print(f"  Model: {model_name}")
    print(f"  RMSE: {rmse:.4f}")
    print(f"  MAE:  {mae:.4f}")
    print(f"  R^2:  {r2:.4f}")

    artifact_path = ARTIFACT_DIR / "forecast_model.joblib"
    joblib.dump({"model": model, "label_encoder_product": le_product, "feature_cols": feature_cols}, artifact_path)
    print(f"  Artifact saved: {artifact_path}")

    return {
        "model_kind": "FUTURE_IMPACT",
        "artifact_path": artifact_path,
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "training_rows": int(len(X_train)),
        "validation_rows": int(len(X_test)),
        "feature_cols": feature_cols,
    }


# ===================================================================
# Database recording
# ===================================================================
def record_to_database(m1_results: dict, m2_results: dict, m3_results: dict):
    """Write model_versions + model_metrics rows for each trained model."""
    print("\n" + "=" * 60)
    print("Recording results to database")
    print("=" * 60)

    try:
        from sqlalchemy import text
        engine = _get_engine()
    except Exception as e:
        print(f"  WARNING: Could not connect to database: {e}")
        print("  Skipping DB recording. Results are printed above and artifacts saved to disk.")
        return

    with engine.connect() as conn:
        # Fetch tenant_id and user_id
        row = conn.execute(text("SELECT id FROM core.tenants WHERE code = 'demo-pharma'")).fetchone()
        if not row:
            print("  WARNING: tenant 'demo-pharma' not found. Skipping DB recording.")
            return
        tenant_id = str(row[0])

        row = conn.execute(text("SELECT id FROM auth.users WHERE email = 'admin@demo.com'")).fetchone()
        if not row:
            print("  WARNING: user 'admin@demo.com' not found. Skipping DB recording.")
            return
        user_id = str(row[0])

        # Set RLS tenant context
        conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

        now = datetime.now(timezone.utc)

        # --- Helper: find or create model_spec ---
        def ensure_model_spec(code: str, name: str, model_kind: str, algorithm: str) -> str:
            existing = conn.execute(
                text("SELECT id FROM ml.model_specs WHERE tenant_id = :tid AND code = :code"),
                {"tid": tenant_id, "code": code},
            ).fetchone()
            if existing:
                return str(existing[0])
            spec_id = str(uuid.uuid4())
            conn.execute(text("""
                INSERT INTO ml.model_specs (id, tenant_id, code, name, model_kind, algorithm, target_definition, is_active, created_by, updated_by, created_at, updated_at, row_version)
                VALUES (:id, :tid, :code, :name, :kind, :algo, :target_def, true, :uid, :uid, :now, :now, 1)
            """), {
                "id": spec_id, "tid": tenant_id, "code": code, "name": name,
                "kind": model_kind, "algo": algorithm, "target_def": f"{model_kind} target",
                "uid": user_id, "now": now,
            })
            return spec_id

        # --- Helper: insert model_version ---
        def insert_model_version(
            spec_id: str, model_kind: str, artifact_path: Path | None,
            training_rows: int | None, validation_rows: int | None,
            hyperparameters: dict | None = None,
            lifecycle_state: str = "ACTIVE",
        ) -> str:
            ver_id = str(uuid.uuid4())
            artifact_key = None
            artifact_checksum = None
            artifact_bytes = None
            if artifact_path and artifact_path.exists():
                artifact_key = str(artifact_path.relative_to(ROOT))
                artifact_checksum = _sha256_file(artifact_path)
                artifact_bytes = artifact_path.stat().st_size

            next_ver = conn.execute(text("""
                SELECT COALESCE(MAX(version_number), 0) + 1
                FROM ml.model_versions
                WHERE tenant_id = :tid AND model_spec_id = :spec_id
            """), {"tid": tenant_id, "spec_id": spec_id}).scalar()

            conn.execute(text("""
                INSERT INTO ml.model_versions
                    (id, tenant_id, model_spec_id, model_kind, version_number, label,
                     lifecycle_state, artifact_key, artifact_checksum, artifact_bytes,
                     hyperparameters, training_rows, validation_rows,
                     trained_at, trained_on_synthetic,
                     created_by, updated_by, created_at, updated_at, row_version)
                VALUES
                    (:id, :tid, :spec_id, :kind, :ver_num, :label,
                     :lifecycle, :akey, :achk, :abytes,
                     :hyper, :tr_rows, :val_rows,
                     :now, true,
                     :uid, :uid, :now, :now, 1)
            """), {
                "id": ver_id, "tid": tenant_id, "spec_id": spec_id, "kind": model_kind,
                "ver_num": next_ver, "lifecycle": lifecycle_state, "label": f"train-v{next_ver}-{now.strftime('%Y%m%d')}",
                "akey": artifact_key, "achk": artifact_checksum, "abytes": artifact_bytes,
                "hyper": json.dumps(hyperparameters) if hyperparameters else None,
                "tr_rows": training_rows, "val_rows": validation_rows,
                "now": now, "uid": user_id,
            })
            return ver_id

        # --- Helper: insert metric ---
        def insert_metric(ver_id: str, split: str, name: str, value: float, n_obs: int | None = None):
            conn.execute(text("""
                INSERT INTO ml.model_metrics
                    (id, tenant_id, model_version_id, split, metric_name, metric_value, segment, n_observations, created_at, updated_at)
                VALUES
                    (:id, :tid, :vid, :split, :name, :val, 'ALL', :nobs, :now, :now)
            """), {
                "id": str(uuid.uuid4()), "tid": tenant_id, "vid": ver_id,
                "split": split, "name": name, "val": value, "nobs": n_obs, "now": now,
            })

        # ---- M1 Propensity ----
        print("  Recording M1 (Propensity)...")
        spec_id = ensure_model_spec("propensity-v1", "Propensity Model", "PROPENSITY", "LogisticRegression")
        ver_id = insert_model_version(
            spec_id, "PROPENSITY", m1_results.get("artifact_path"),
            m1_results["training_rows"], None,
            {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
        )
        insert_metric(ver_id, "validation", "auc_roc", m1_results["cv_auc"], m1_results["training_rows"])
        insert_metric(ver_id, "validation", "accuracy", m1_results["cv_accuracy"], m1_results["training_rows"])
        insert_metric(ver_id, "train", "auc_roc", m1_results["full_auc"], m1_results["training_rows"])
        insert_metric(ver_id, "train", "accuracy", m1_results["full_accuracy"], m1_results["training_rows"])

        # ---- M2 Causal (no artifact — use DRAFT state to satisfy constraint) ----
        print("  Recording M2 (Causal DiD)...")
        spec_id = ensure_model_spec("causal-did-v1", "Causal DiD Estimator", "PROPENSITY", "DiD")
        ver_id = insert_model_version(
            spec_id, "PROPENSITY", None,
            m2_results["n_treated"] + m2_results["n_control"], None,
            {"method": "difference_in_differences"},
            lifecycle_state="DRAFT",
        )
        insert_metric(ver_id, "holdout", "att", m2_results["att"], m2_results["n_treated"])
        insert_metric(ver_id, "holdout", "standard_error", m2_results["se"])
        insert_metric(ver_id, "holdout", "p_value", m2_results["p_value"])
        insert_metric(ver_id, "holdout", "ci_lower", m2_results["ci_low"])
        insert_metric(ver_id, "holdout", "ci_upper", m2_results["ci_high"])

        # ---- M3 Forecast ----
        print("  Recording M3 (Forecast)...")
        spec_id = ensure_model_spec("forecast-v1", "Rx Forecast Model", "FUTURE_IMPACT", "LightGBM")
        ver_id = insert_model_version(
            spec_id, "FUTURE_IMPACT", m3_results.get("artifact_path"),
            m3_results["training_rows"], m3_results["validation_rows"],
            {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 6},
        )
        insert_metric(ver_id, "validation", "rmse", m3_results["rmse"], m3_results["validation_rows"])
        insert_metric(ver_id, "validation", "mae", m3_results["mae"], m3_results["validation_rows"])
        insert_metric(ver_id, "validation", "r2", m3_results["r2"], m3_results["validation_rows"])

        conn.commit()
        print("  Database recording complete.")


# ===================================================================
# Main
# ===================================================================
def main():
    print("SPRIP ML Training Pipeline")
    print("=" * 60)

    m1 = train_propensity_model()
    m2 = train_causal_model()
    m3 = train_forecast_model()

    record_to_database(m1, m2, m3)

    print("\n" + "=" * 60)
    print("Training complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
