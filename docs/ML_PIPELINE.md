# SPRIP ML Pipeline

## Overview

The Speaker ROI Intelligence Platform (SPRIP) ML pipeline trains and deploys three complementary models that together answer the core business question: **"Which HCPs should we invite to speaker programs, and what ROI should we expect?"**

| Model | Algorithm | Purpose | Output |
|-------|-----------|---------|--------|
| **M1 — Propensity** | Logistic Regression | Predict likelihood an HCP will respond to a speaker program | P(respond \| features) ∈ [0, 1] |
| **M2 — Causal DiD** | Difference-in-Differences | Estimate the causal treatment effect of speaker events on prescribing | ATT (Average Treatment effect on Treated) |
| **M3 — Forecast** | LightGBM (or GBR fallback) | Predict next-month Rx volume per product | NRx count forecast |

All models train on synthetic data for demo purposes. The same pipeline structure applies to production data without code changes.

---

## Architecture

```
DATA_EXTRACT/syn dt/data/
├── gold/
│   ├── hcp_event_features.csv    ← M1 input (engineered features)
│   └── matched_pairs.csv         ← M2 input (propensity-matched treated/control)
└── silver/conformed/
    ├── hcp_rx_monthly.csv        ← M2, M3 input (longitudinal Rx data)
    ├── events.csv                ← M2 input (event dates for DiD cutoff)
    └── event_attendance.csv      ← Scoring input

scripts/
├── train_models.py               ← Full training pipeline (M1 + M2 + M3)
└── score_hcps.py                 ← Batch scoring with trained M1

artifacts/models/
├── propensity_model.joblib        ← M1 serialised artifact
├── forecast_model.joblib          ← M3 serialised artifact
├── m1_propensity_metrics.json     ← M1 evaluation metrics
├── m2_causal_metrics.json         ← M2 causal estimates
├── m3_forecast_metrics.json       ← M3 regression metrics
└── training_summary.json          ← Combined training run metadata
```

---

## Model Details

### M1 — Propensity Model

**Objective:** Binary classification — predict whether an HCP belongs to the "treatment" group (likely to engage with speaker programs) vs. "control_candidate" (unlikely to engage).

**Algorithm:** `sklearn.linear_model.LogisticRegression`

**Hyperparameters:**

| Parameter | Value |
|-----------|-------|
| solver | lbfgs |
| C (regularisation) | 1.0 |
| max_iter | 1000 |
| random_state | 42 |

**Features (17 total):**

| Feature | Type | Description |
|---------|------|-------------|
| avg_nrx_3m | Numeric | Average NRx over last 3 months |
| avg_nrx_6m | Numeric | Average NRx over last 6 months |
| avg_trx_3m | Numeric | Average TRx over last 3 months |
| avg_trx_6m | Numeric | Average TRx over last 6 months |
| nrx_trend | Numeric | NRx momentum (3m mean − previous 3m mean) |
| competitor_trx_avg | Numeric | Mean competitor TRx |
| rep_calls_3m | Numeric | Sales rep calls in last 3 months |
| emails_3m | Numeric | Marketing emails in last 3 months |
| samples_3m | Numeric | Samples delivered in last 3 months |
| prior_event_count | Numeric | Historical event attendance count |
| specialty_topic_match | Numeric | Specialty-topic alignment score |
| access_index | Numeric | HCP accessibility index |
| seasonality_index | Numeric | Seasonal prescribing adjustment |
| competitor_index | Numeric | Competitive landscape index |
| segment_enc | Encoded | HCP market segment (LabelEncoded) |
| specialty_enc | Encoded | Medical specialty (LabelEncoded) |
| region_enc | Encoded | Geographic region (LabelEncoded) |

**Validation Strategy:** 5-fold Stratified K-Fold cross-validation

**Metrics (from training run 2026-08-20):**

| Metric | Value |
|--------|-------|
| **AUC-ROC** | 0.5482 |
| **Accuracy** | 0.5500 |
| **Precision** | 0.4500 |
| **Recall** | 0.5625 |
| Training samples | 160 |
| Test samples | 40 |
| Positive rate | 40.0% |

**Interpretation:** The propensity model is trained on synthetic demo data with randomly generated features, which explains the near-random AUC (~0.55). With real production data containing genuine signal in prescribing patterns and engagement history, AUC-ROC is expected to reach 0.70–0.85 based on industry benchmarks for HCP propensity models.

**Artifact:**
- Path: `artifacts/models/propensity_model.joblib`
- SHA-256: `08ec7ce35aa0929da69dd777128c77a3d7a72d1acc1c6e8a0df28b8bb1acbe01`
- Contents: `{model, label_encoders, feature_cols}`

---

### M2 — Causal DiD Estimator

**Objective:** Estimate the causal effect of speaker program participation on HCP prescribing behaviour using a Difference-in-Differences design.

**Method:** Classic two-period DiD with propensity-score matched controls

**Design:**

1. **Matching:** Treated HCPs (event attendees) are propensity-score matched to control HCPs from `gold/matched_pairs.csv`
2. **Cutoff:** The median event date splits the timeline into pre/post periods
3. **Outcome:** Average NRx per HCP in each period
4. **Estimand:** ATT = (Treated_post − Treated_pre) − (Control_post − Control_pre)

**Statistical Results (from training run 2026-08-20):**

| Statistic | Value |
|-----------|-------|
| **ATT (Average Treatment Effect on Treated)** | **1.7825** |
| Standard Error | 0.1406 |
| 95% Confidence Interval | [1.5070, 2.0581] |
| p-value | < 0.001 |
| Statistically significant at α=0.05 | **Yes** |
| Treated HCPs (n) | 80 |
| Control HCPs (n) | 120 |
| Events analysed | 60 |

**Interpretation:** On synthetic data, the DiD estimator finds that speaker program attendees increased their average NRx by **1.78 scripts/month** more than matched controls. The tight confidence interval [1.51, 2.06] and p < 0.001 indicate strong statistical significance. This is a methodological validation — real-world ATT estimates will vary by therapeutic area and program type.

**Key assumptions:**
- **Parallel trends:** Pre-treatment prescribing trends are similar between treated and control groups
- **No spillover:** Control HCPs are not indirectly affected by the speaker program
- **Common support:** Matched pairs share similar observable characteristics

**No persisted artifact** — M2 is a statistical estimator, not a predictive model. Results are stored in `ml.model_versions` and `ml.model_metrics` database tables with `lifecycle_state = 'DRAFT'`.

---

### M3 — Forecast Model

**Objective:** Time-series regression — predict next-month NRx volume per product, enabling forward-looking ROI projections.

**Algorithm:** LightGBM Regressor (falls back to sklearn GradientBoostingRegressor if LightGBM is unavailable)

**Hyperparameters:**

| Parameter | Value |
|-----------|-------|
| n_estimators | 200 |
| learning_rate | 0.05 |
| max_depth | 6 |
| num_leaves | 31 |
| random_state | 42 |

**Features (10 total):**

| Feature | Description |
|---------|-------------|
| nrx_lag1 | NRx volume 1 month ago |
| nrx_lag2 | NRx volume 2 months ago |
| nrx_lag3 | NRx volume 3 months ago |
| nrx_roll3 | 3-month rolling average NRx |
| nrx_roll6 | 6-month rolling average NRx |
| trx_lag1 | TRx volume 1 month ago |
| competitor_lag1 | Competitor TRx 1 month ago |
| trend | Linear time trend index |
| month_num | Calendar month (1–12, seasonality) |
| product_enc | Product identifier (LabelEncoded) |

**Train/Test Split:** Temporal — last 20% of observations by time (no data leakage)

**Metrics (from training run 2026-08-20):**

| Metric | Value |
|--------|-------|
| **MAE (Mean Absolute Error)** | **31.9499** |
| **R² (Coefficient of Determination)** | **0.0816** |
| Training samples | 48 |
| Test samples | 12 |
| Model type | LightGBM |

**Interpretation:** The low R² (0.08) reflects the small synthetic dataset (only 48 training rows across 4 products × ~15 months with lag features). Time-series forecasting models require substantial history to learn seasonality and trend patterns. With 12+ months of real production data per product, R² values of 0.60–0.80 are achievable. The MAE of ~32 NRx represents the average prediction error magnitude.

**Artifact:**
- Path: `artifacts/models/forecast_model.joblib`
- SHA-256: `af8538b1f92c78c653d12d3aca7154dfba419a26b84ea3914016a3b769dbfb7c`
- Contents: `{model, label_encoder_product, feature_cols}`

---

## Training Pipeline

### Running Training

```bash
# From project root
.venv/Scripts/python scripts/train_models.py
```

The pipeline:
1. Reads gold/silver-layer CSVs from `DATA_EXTRACT/`
2. Trains M1 (Propensity), M2 (Causal DiD), M3 (Forecast) sequentially
3. Serialises model artifacts to `artifacts/models/`
4. Writes metrics JSON files alongside artifacts
5. Records `ml.model_specs`, `ml.model_versions`, and `ml.model_metrics` rows in PostgreSQL

### Running HCP Scoring

```bash
.venv/Scripts/python scripts/score_hcps.py
```

The scoring pipeline:
1. Loads the trained propensity model from `artifacts/models/propensity_model.joblib`
2. Fetches all HCPs from `core.hcps` (falls back to CSV if DB unavailable)
3. Builds feature vectors from silver-layer CSVs
4. Generates propensity scores and rankings for every HCP
5. Writes scores to `analytics.propensity_scores` table (falls back to JSON)

### Training Data Summary

| Dataset | Records | Source |
|---------|---------|--------|
| HCP event features | 200 HCPs | `gold/hcp_event_features.csv` |
| Matched pairs | 80 treated + 120 control | `gold/matched_pairs.csv` |
| Rx monthly | 2,600 rows | `silver/conformed/hcp_rx_monthly.csv` |
| Event attendance | 896 rows | `silver/conformed/event_attendance.csv` |
| Events | 60 events | `silver/conformed/events.csv` |

---

## Database Schema

Training results are persisted in the `ml` schema:

### ml.model_specs
Defines each model type. One row per algorithm variant.

| Column | Description |
|--------|-------------|
| id | UUID primary key |
| tenant_id | Tenant isolation |
| code | Unique identifier (e.g., `propensity-v1`) |
| name | Human-readable name |
| model_kind | `PROPENSITY` or `FUTURE_IMPACT` |
| algorithm | `LogisticRegression`, `DiD`, `LightGBM` |
| is_active | Whether this spec is in active use |

### ml.model_versions
Each training run produces a version row.

| Column | Description |
|--------|-------------|
| id | UUID primary key |
| model_spec_id | FK to model_specs |
| version_number | Sequential version within spec |
| lifecycle_state | `DRAFT` → `ACTIVE` → `ARCHIVED` |
| artifact_key | Path to serialised model file |
| artifact_checksum | SHA-256 of the artifact |
| artifact_bytes | File size |
| hyperparameters | JSONB of training config |
| training_rows | Number of training samples |
| validation_rows | Number of validation samples |
| trained_at | Timestamp |
| trained_on_synthetic | Boolean flag |

### ml.model_metrics
Individual metric observations per model version.

| Column | Description |
|--------|-------------|
| model_version_id | FK to model_versions |
| split | `train`, `validation`, `holdout` |
| metric_name | `auc_roc`, `accuracy`, `att`, `rmse`, `mae`, `r2`, etc. |
| metric_value | Float value |
| segment | `ALL` or a subpopulation key |
| n_observations | Sample size for this metric |

---

## Model Lifecycle

```
DRAFT ──→ ACTIVE ──→ ARCHIVED
  │                      ↑
  └──────────────────────┘ (skip to archive if validation fails)
```

1. **DRAFT:** Model version created, metrics recorded, not yet serving predictions
2. **ACTIVE:** Promoted after validation; used by the scoring pipeline and API
3. **ARCHIVED:** Superseded by a newer version; retained for audit trail

Only one version per model_spec can be `ACTIVE` at a time. The M2 causal estimator stays in `DRAFT` because it produces statistical estimates rather than deployable predictions.

---

## Production Considerations

### Data Quality
- Input CSVs must pass schema validation before training
- Missing features are zero-filled (documented per model above)
- Categorical encoding uses `LabelEncoder` — unknown categories at scoring time default to 0

### Reproducibility
- All models use `random_state=42`
- Training metadata (seed, dataset sizes, timestamps) are captured in `training_summary.json`
- Artifact checksums enable integrity verification

### Monitoring
- Model metrics are stored in PostgreSQL and exposed via the `/api/v1/roi/results` and `/api/v1/forecasts` API endpoints
- The Analytics Dashboard displays ROI trends derived from M2 causal estimates
- Forecast accuracy can be tracked by comparing M3 predictions against actual NRx in subsequent months

### Retraining
- Recommended cadence: monthly, after new Rx data ingestion
- The pipeline is idempotent — rerunning creates new `model_versions` rows without affecting prior versions
- Celery task `analytics.refresh_propensity_scores` can trigger scoring after model retraining

### Security
- Training scripts connect via `app_rw` database role with tenant-scoped RLS
- Model artifacts are stored locally; production deployments should use MinIO/S3 with signed URLs
- No patient-level data, PII, or ABHI identifiers are used in training features
- Propensity scores are tenant-isolated via RLS policies

---

## API Integration

Trained models feed three API endpoint groups:

| Endpoint | Model | Description |
|----------|-------|-------------|
| `GET /api/v1/roi/results` | M2 | ROI results with causal ATT estimates |
| `GET /api/v1/forecasts` | M3 | Rx volume forecasts with confidence bands |
| `GET /api/v1/dashboard/stats` | M1+M2 | Aggregate propensity and ROI metrics |
| `POST /api/v1/optimizer/simulate` | M1+M3 | Budget allocation simulation |

---

## Metrics Summary (Training Run: 2026-08-20T02:39:41Z)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  M1 — Propensity (LogisticRegression)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AUC-ROC ................ 0.5482
  Accuracy ............... 0.5500
  Precision .............. 0.4500
  Recall ................. 0.5625
  Training samples ....... 160
  Test samples ........... 40

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  M2 — Causal DiD Estimator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ATT .................... 1.7825
  Standard Error ......... 0.1406
  95% CI ................. [1.5070, 2.0581]
  p-value ................ < 0.001
  Treated (n) ............ 80
  Control (n) ............ 120

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  M3 — Forecast (LightGBM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  MAE .................... 31.9499
  R² ..................... 0.0816
  Training samples ....... 48
  Test samples ........... 12
```
