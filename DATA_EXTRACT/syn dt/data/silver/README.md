# silver/ — conformed layer (NOT produced by the generator)

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
