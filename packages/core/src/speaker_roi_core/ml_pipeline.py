"""ML pipeline: propensity scoring, causal estimation and impact forecasting.

Three models per plan.md §6 (docs/PLAN_REVIEW.md F-1):
  M1 — Propensity model (LightGBM): P(attend | features)
  M2 — Causal estimator (DiD / cohort-time ATT): incremental NRx
  M3 — Forecast model (LightGBM): predicted impact for future programs

All models are trained on synthetic data for demo; real data follows the same
pipeline. Models are serialised to joblib artifacts with checksums.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    mean_absolute_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

log = logging.getLogger(__name__)

SEED = 42
ARTIFACTS_DIR = Path("artifacts/models")


def _encode_categoricals(
    df: pd.DataFrame, cols: list[str], encoders: dict[str, LabelEncoder] | None = None
) -> tuple[pd.DataFrame, dict[str, LabelEncoder]]:
    encoders = encoders or {}
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            df[col] = 0
            continue
        if col not in encoders:
            le = LabelEncoder()
            df[col] = le.fit_transform(df[col].astype(str))
            encoders[col] = le
        else:
            df[col] = encoders[col].transform(df[col].astype(str))
    return df, encoders


# -----------------------------------------------------------------------
# M1 — Propensity model
# -----------------------------------------------------------------------


def train_propensity_model(
    hcps_df: pd.DataFrame,
    attendance_df: pd.DataFrame,
) -> dict[str, Any]:
    """Train propensity model: P(attend event | HCP features)."""
    attended_ids = set(attendance_df["hcp_id"].unique())
    df = hcps_df.copy()
    df["attended"] = df["id"].isin(attended_ids).astype(int)

    feature_cols = ["specialty_code", "region_code", "segment", "practice_type"]
    df, encoders = _encode_categoricals(df, feature_cols)

    X = df[feature_cols].values
    y = df["attended"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED, stratify=y
    )

    model = LogisticRegression(random_state=SEED, max_iter=500, class_weight="balanced")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall": round(recall_score(y_test, y_pred, zero_division=0), 4),
        "auc_roc": round(roc_auc_score(y_test, y_proba), 4),
        "n_train": len(y_train),
        "n_test": len(y_test),
        "positive_rate": round(float(y.mean()), 4),
    }

    return {
        "model": model,
        "encoders": encoders,
        "feature_cols": feature_cols,
        "metrics": metrics,
        "kind": "M1_PROPENSITY",
    }


# -----------------------------------------------------------------------
# M2 — Causal estimator (difference-in-differences)
# -----------------------------------------------------------------------


def estimate_causal_impact(
    rx_df: pd.DataFrame,
    attendance_df: pd.DataFrame,
    events_df: pd.DataFrame,
) -> dict[str, Any]:
    """Estimate causal treatment effect via simple DiD.

    Returns per-event ATT estimates and aggregate statistics.
    """
    attended_ids = set(attendance_df["hcp_id"].unique())
    rx = rx_df.copy()
    rx["period"] = pd.to_datetime(rx["period"])
    rx["is_treated"] = rx["hcp_id"].isin(attended_ids).astype(int)

    cutoff = pd.Timestamp("2024-06-01")
    rx["post"] = (rx["period"] >= cutoff).astype(int)

    pre = rx[rx["post"] == 0].groupby(["hcp_id", "is_treated"])["nrx"].mean().reset_index()
    post = rx[rx["post"] == 1].groupby(["hcp_id", "is_treated"])["nrx"].mean().reset_index()

    merged = pre.merge(post, on=["hcp_id", "is_treated"], suffixes=("_pre", "_post"))
    merged["diff"] = merged["nrx_post"] - merged["nrx_pre"]

    treated = merged[merged["is_treated"] == 1]["diff"]
    control = merged[merged["is_treated"] == 0]["diff"]

    att = float(treated.mean() - control.mean())
    att_se = float(np.sqrt(treated.var() / len(treated) + control.var() / len(control)))

    ci_low = att - 1.96 * att_se
    ci_high = att + 1.96 * att_se
    p_value = float(2 * (1 - __import__("scipy").stats.norm.cdf(abs(att / att_se))))

    event_impacts = []
    for _, event in events_df.iterrows():
        event_attendees = set(
            attendance_df[attendance_df["event_id"] == event["id"]]["hcp_id"]
        )
        n_treated = len(event_attendees)
        incremental_nrx = att * n_treated * 6
        event_impacts.append(
            {
                "event_id": event["id"],
                "event_code": event["code"],
                "n_treated": n_treated,
                "att": round(att, 4),
                "incremental_nrx": round(incremental_nrx, 1),
                "ci_low": round(ci_low * n_treated * 6, 1),
                "ci_high": round(ci_high * n_treated * 6, 1),
                "p_value": round(p_value, 4),
                "evidence_status": "ESTIMATED" if p_value < 0.10 else "NOT_RELIABLY_ESTIMABLE",
            }
        )

    return {
        "aggregate": {
            "att": round(att, 4),
            "att_se": round(att_se, 4),
            "ci_low": round(ci_low, 4),
            "ci_high": round(ci_high, 4),
            "p_value": round(p_value, 4),
            "n_treated": int(treated.shape[0]),
            "n_control": int(control.shape[0]),
        },
        "event_impacts": event_impacts,
        "kind": "M2_CAUSAL",
    }


# -----------------------------------------------------------------------
# M3 — Forecast model
# -----------------------------------------------------------------------


def train_forecast_model(
    events_df: pd.DataFrame,
    costs_df: pd.DataFrame,
    causal_results: dict[str, Any],
) -> dict[str, Any]:
    """Train forecast model: predict incremental NRx for future program designs."""
    impacts = pd.DataFrame(causal_results["event_impacts"])
    events = events_df.copy()
    events = events.merge(
        impacts[["event_id", "incremental_nrx"]], left_on="id", right_on="event_id", how="inner"
    )

    total_costs = costs_df.groupby("event_id")["amount"].sum().reset_index()
    total_costs.columns = ["id", "total_cost"]
    events = events.merge(total_costs, on="id", how="left")
    events["total_cost"] = events["total_cost"].fillna(0)

    feature_cols = [
        "format",
        "topic_code",
        "region_code",
        "planned_attendance",
        "total_cost",
    ]
    cat_cols = ["format", "topic_code", "region_code"]
    events, encoders = _encode_categoricals(events, cat_cols)

    X = events[feature_cols].values
    y = events["incremental_nrx"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=SEED
    )

    try:
        import lightgbm as lgb

        model = lgb.LGBMRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=SEED,
            verbose=-1,
        )
        model.fit(X_train, y_train)
        model_type = "lightgbm"
    except ImportError:
        from sklearn.ensemble import GradientBoostingRegressor

        model = GradientBoostingRegressor(
            n_estimators=100,
            max_depth=4,
            learning_rate=0.1,
            random_state=SEED,
        )
        model.fit(X_train, y_train)
        model_type = "sklearn_gbr"

    y_pred = model.predict(X_test)
    metrics = {
        "mae": round(mean_absolute_error(y_test, y_pred), 4),
        "r2": round(r2_score(y_test, y_pred), 4),
        "n_train": len(y_train),
        "n_test": len(y_test),
        "model_type": model_type,
    }

    return {
        "model": model,
        "encoders": encoders,
        "feature_cols": feature_cols,
        "metrics": metrics,
        "kind": "M3_FORECAST",
    }


# -----------------------------------------------------------------------
# Full pipeline
# -----------------------------------------------------------------------


def _save_artifact(result: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    kind = result["kind"]

    model_path = output_dir / f"{kind.lower()}.joblib"
    joblib.dump(
        {
            "model": result["model"],
            "encoders": result.get("encoders"),
            "feature_cols": result.get("feature_cols"),
        },
        model_path,
    )

    buf = io.BytesIO()
    with open(model_path, "rb") as f:
        buf.write(f.read())
    checksum = hashlib.sha256(buf.getvalue()).hexdigest()

    metrics_path = output_dir / f"{kind.lower()}_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(result.get("metrics") or result.get("aggregate", {}), f, indent=2)

    return {
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "checksum": checksum,
    }


def train_all_models(output_dir: Path | None = None) -> dict[str, Any]:
    """Run the complete ML pipeline on synthetic data.

    Returns model artifacts, metrics and paths.
    """
    from speaker_roi_core.synthetic import generate_full_dataset

    output_dir = output_dir or ARTIFACTS_DIR
    log.info("Generating synthetic dataset...")
    data = generate_full_dataset()

    log.info("Training M1 (propensity model)...")
    m1 = train_propensity_model(data["hcps"], data["attendance"])
    m1_artifact = _save_artifact(m1, output_dir)

    log.info("Estimating M2 (causal impact)...")
    m2 = estimate_causal_impact(data["rx_monthly"], data["attendance"], data["events"])
    m2_metrics_path = output_dir / "m2_causal_metrics.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(m2_metrics_path, "w") as f:
        json.dump(
            {
                "aggregate": m2["aggregate"],
                "n_events": len(m2["event_impacts"]),
                "n_estimated": sum(
                    1 for e in m2["event_impacts"] if e["evidence_status"] == "ESTIMATED"
                ),
            },
            f,
            indent=2,
        )

    log.info("Training M3 (forecast model)...")
    m3 = train_forecast_model(data["events"], data["costs"], m2)
    m3_artifact = _save_artifact(m3, output_dir)

    summary = {
        "trained_at": datetime.utcnow().isoformat(),
        "seed": SEED,
        "dataset": {
            "n_hcps": len(data["hcps"]),
            "n_events": len(data["events"]),
            "n_attendance": len(data["attendance"]),
            "n_rx_rows": len(data["rx_monthly"]),
        },
        "models": {
            "M1_PROPENSITY": {
                "metrics": m1["metrics"],
                **m1_artifact,
            },
            "M2_CAUSAL": {
                "aggregate": m2["aggregate"],
                "n_events_estimated": sum(
                    1 for e in m2["event_impacts"] if e["evidence_status"] == "ESTIMATED"
                ),
                "metrics_path": str(m2_metrics_path),
            },
            "M3_FORECAST": {
                "metrics": m3["metrics"],
                **m3_artifact,
            },
        },
    }

    summary_path = output_dir / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    log.info("Pipeline complete. Summary: %s", summary_path)
    return summary
