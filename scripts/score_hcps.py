"""
SPRIP HCP Scoring Script
=========================
Loads the trained propensity model and scores all HCPs in core.hcps.
Writes results to analytics.propensity_scores if the table exists,
otherwise falls back to a JSON summary file.

Usage:
    .venv/Scripts/python scripts/score_hcps.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = ROOT / "artifacts" / "models"
MODEL_PATH = ARTIFACT_DIR / "propensity_model.joblib"
DATA_SILVER = ROOT / "DATA_EXTRACT" / "syn dt" / "data" / "silver" / "conformed"
OUTPUT_JSON = ARTIFACT_DIR / "hcp_propensity_scores.json"

DATABASE_URL = "postgresql+psycopg://app_rw:app_rw_pw@127.0.0.1:54329/speaker_roi"


def _get_engine():
    from sqlalchemy import create_engine
    return create_engine(DATABASE_URL)


def load_model():
    if not MODEL_PATH.exists():
        print(f"ERROR: Model artifact not found at {MODEL_PATH}")
        print("Run scripts/train_models.py first.")
        sys.exit(1)
    bundle = joblib.load(MODEL_PATH)
    return bundle["model"], bundle["label_encoders"], bundle["feature_cols"]


def build_features_from_csvs(hcp_ids: set[str]) -> pd.DataFrame:
    """Build feature vectors from silver-layer CSVs for the given HCP IDs."""

    rx = pd.read_csv(DATA_SILVER / "hcp_rx_monthly.csv")
    attendance = pd.read_csv(DATA_SILVER / "event_attendance.csv")

    # Rx aggregates per HCP
    rx_agg = rx.groupby("hcp_id").agg(
        avg_nrx_3m=("nrx", lambda s: s.tail(3).mean()),
        avg_nrx_6m=("nrx", lambda s: s.tail(6).mean()),
        avg_trx_3m=("trx", lambda s: s.tail(3).mean()),
        avg_trx_6m=("trx", lambda s: s.tail(6).mean()),
        nrx_trend=("nrx", lambda s: (s.tail(3).mean() - s.head(3).mean()) if len(s) >= 6 else 0.0),
        competitor_trx_avg=("competitor_trx", "mean"),
    ).reset_index()

    # Attendance aggregates per HCP
    att_agg = attendance.groupby("hcp_id").agg(
        prior_event_count=("event_id", "nunique"),
    ).reset_index()

    features = rx_agg.merge(att_agg, on="hcp_id", how="left")
    features["prior_event_count"] = features["prior_event_count"].fillna(0)

    # Fill columns that the propensity model expects but we cannot derive from silver
    for col in [
        "rep_calls_3m", "emails_3m", "samples_3m",
        "specialty_topic_match", "access_index",
        "seasonality_index", "competitor_index",
    ]:
        features[col] = 0.0

    return features


def score_hcps():
    print("SPRIP HCP Scoring Pipeline")
    print("=" * 60)

    model, label_encoders, feature_cols = load_model()

    # ------------------------------------------------------------------
    # Load HCPs from DB (or fall back to CSV hcp_ids)
    # ------------------------------------------------------------------
    hcps_from_db = False
    try:
        from sqlalchemy import text
        engine = _get_engine()
        with engine.connect() as conn:
            row = conn.execute(text("SELECT id FROM core.tenants WHERE code = 'demo-pharma'")).fetchone()
            if row:
                tenant_id = str(row[0])
                conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))
                hcp_rows = conn.execute(text(
                    "SELECT id, external_id, specialty, region FROM core.hcps WHERE tenant_id = :tid"
                ), {"tid": tenant_id}).fetchall()
                if hcp_rows:
                    hcps_df = pd.DataFrame(hcp_rows, columns=["db_id", "external_id", "specialty", "region"])
                    hcps_from_db = True
                    print(f"  Loaded {len(hcps_df)} HCPs from database")
    except Exception as e:
        print(f"  WARNING: Could not load HCPs from DB: {e}")

    if not hcps_from_db:
        # Fall back: use unique hcp_ids from silver CSVs
        rx = pd.read_csv(DATA_SILVER / "hcp_rx_monthly.csv")
        unique_ids = rx["hcp_id"].unique()
        hcps_df = pd.DataFrame({
            "db_id": [None] * len(unique_ids),
            "external_id": unique_ids,
            "specialty": "Unknown",
            "region": "Unknown",
        })
        print(f"  Loaded {len(hcps_df)} HCPs from CSV data (DB unavailable)")

    # ------------------------------------------------------------------
    # Build features
    # ------------------------------------------------------------------
    hcp_ids = set(hcps_df["external_id"].dropna().astype(str).unique())
    features = build_features_from_csvs(hcp_ids)

    # Map external_id to features
    hcps_df["external_id"] = hcps_df["external_id"].astype(str)
    features["hcp_id"] = features["hcp_id"].astype(str)

    merged = hcps_df.merge(features, left_on="external_id", right_on="hcp_id", how="left")

    # Fill categoricals with defaults, then encode
    for col in ["segment", "specialty", "region"]:
        enc_col = col + "_enc"
        if col in label_encoders:
            le = label_encoders[col]
            # For unknown categories, use 0
            if col == "segment":
                merged[col + "_raw"] = "unknown"
            elif col in merged.columns:
                merged[col + "_raw"] = merged[col].fillna("Unknown").astype(str)
            else:
                merged[col + "_raw"] = "Unknown"

            known_classes = set(le.classes_)
            merged[enc_col] = merged[col + "_raw"].apply(
                lambda v: int(le.transform([v])[0]) if v in known_classes else 0
            )
        else:
            merged[enc_col] = 0

    # Assemble feature matrix in the same order the model was trained
    for col in feature_cols:
        if col not in merged.columns:
            merged[col] = 0.0

    X = merged[feature_cols].fillna(0).values

    # ------------------------------------------------------------------
    # Score
    # ------------------------------------------------------------------
    probas = model.predict_proba(X)[:, 1]
    merged["propensity_score"] = probas
    merged["propensity_rank"] = merged["propensity_score"].rank(ascending=False, method="dense").astype(int)

    print(f"\n  Scored {len(merged)} HCPs")
    print(f"  Score distribution:")
    print(f"    Mean:   {probas.mean():.4f}")
    print(f"    Median: {np.median(probas):.4f}")
    print(f"    Min:    {probas.min():.4f}")
    print(f"    Max:    {probas.max():.4f}")
    print(f"\n  Top 10 HCPs by propensity:")
    top10 = merged.nlargest(10, "propensity_score")[["external_id", "propensity_score", "propensity_rank"]]
    print(top10.to_string(index=False))

    # ------------------------------------------------------------------
    # Write to DB or JSON
    # ------------------------------------------------------------------
    written_to_db = False
    try:
        from sqlalchemy import text
        engine = _get_engine()
        with engine.connect() as conn:
            # Check if analytics.propensity_scores exists
            exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'analytics' AND table_name = 'propensity_scores'
                )
            """)).scalar()

            if exists:
                row = conn.execute(text("SELECT id FROM core.tenants WHERE code = 'demo-pharma'")).fetchone()
                tenant_id = str(row[0])
                conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

                now = datetime.now(timezone.utc)
                for _, r in merged.iterrows():
                    if r["db_id"] is not None:
                        conn.execute(text("""
                            INSERT INTO analytics.propensity_scores
                                (tenant_id, hcp_id, score, rank, scored_at)
                            VALUES (:tid, :hid, :score, :rank, :now)
                            ON CONFLICT (tenant_id, hcp_id)
                            DO UPDATE SET score = EXCLUDED.score, rank = EXCLUDED.rank, scored_at = EXCLUDED.scored_at
                        """), {
                            "tid": tenant_id, "hid": str(r["db_id"]),
                            "score": float(r["propensity_score"]),
                            "rank": int(r["propensity_rank"]),
                            "now": now,
                        })
                conn.commit()
                written_to_db = True
                print(f"\n  Scores written to analytics.propensity_scores")
            else:
                print("\n  Table analytics.propensity_scores does not exist.")
    except Exception as e:
        print(f"\n  WARNING: Could not write to DB: {e}")

    if not written_to_db:
        # Write JSON summary
        scores = merged[["external_id", "propensity_score", "propensity_rank"]].copy()
        scores = scores.sort_values("propensity_rank")
        result = {
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "total_hcps": len(scores),
            "score_stats": {
                "mean": float(probas.mean()),
                "median": float(np.median(probas)),
                "min": float(probas.min()),
                "max": float(probas.max()),
            },
            "scores": scores.to_dict(orient="records"),
        }
        OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_JSON, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"  Scores written to {OUTPUT_JSON}")

    print("\n" + "=" * 60)
    print("Scoring complete.")
    print("=" * 60)


if __name__ == "__main__":
    score_hcps()
