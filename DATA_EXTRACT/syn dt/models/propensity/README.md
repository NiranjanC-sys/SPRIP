# Propensity Model + Attendee-Control Matching

This module trains an XGBoost propensity model to predict event attendance likelihood
based on pre-event HCP features, then uses the fitted propensity scores plus
covariate distance to match each treated (attendee) HCP with up to 2 control
(non-attendee) HCPs from the same event.

## How to rerun

```bash
# 1. Ensure feature engineering has been run first
python pipelines/feature_engineering.py

# 2. Train propensity model and produce matched pairs
python models/propensity/train_propensity.py
```

## Inputs

- `data/gold/hcp_event_features.csv` (from feature engineering)

## Outputs

- `data/gold/matched_pairs.csv` — one row per treated-control pair (columns:
  `master_hcp_id_treated`, `event_id`, `master_hcp_id_control`,
  `propensity_score_treated`, `propensity_score_control`, `match_weight`)
- `data/gold/propensity_diagnostics.csv` — model AUC, per-feature SMD before
  and after matching, retention metrics

## Method summary

| Component | Detail |
|---|---|
| Model | XGBoost classifier (300 trees, depth 5, lr 0.05) |
| CV | Grouped 5-fold (groups = event_id) |
| Target | 1 = treatment (attended), 0 = control_candidate |
| Matching | Within-event nearest-neighbor, PS caliper 0.05, composite covariate distance |
| Balance | SMD computed on all 17 features; 8/17 below 0.10 threshold |

Post-match balance on Rx-volume and marketing-intensity features (SMD 0.15-0.24)
reflects the intentional selection bias in the synthetic data — higher-prescribing,
more-engaged HCPs are more likely to attend. Regression adjustment on the matched
sample is recommended for the DiD step to control for remaining imbalance.
