# gold/ — analytics layer (NOT produced by the generator)

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
