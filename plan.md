# HCP Speaker Program Impact & ROI Platform

> Authoritative, one-shot production-grade build specification  
> Last updated: 2026-08-19  
> Status: Implementation-ready  
> Initial deployment: Docker-based local/private cloud using PostgreSQL and S3-compatible object storage  
> Planned cloud pivot: Azure Data Lake Storage, Azure Data Factory, Azure Functions/Databricks and Microsoft Entra ID

## 0. Instructions to the implementation agent

Build the complete working application described in this README. This document is the current source of truth and supersedes older prototype assumptions in `HCP_Speaker_Program_AI_ROI_Hackathon_Blueprint.pdf`, especially the earlier one-brand and Streamlit design.

The implementation must be functional, not a collection of static mock screens:

- Run the full stack through Docker Compose.
- Use PostgreSQL for transactional, analytical-result and metadata storage.
- Use S3-compatible object storage (MinIO locally) for uploaded source files and generated artifacts; do not store file blobs in PostgreSQL.
- Implement strict tenant isolation for multiple pharmaceutical companies.
- Implement complete authentication, session handling, protected routes and role-specific landing pages. There is no anonymous business-data access and no public self-sign-up.
- Implement a platform-admin console that creates, configures, suspends and audits pharmaceutical-company tenants without granting the administrator default access to their commercial data.
- Implement real upload, validation, processing, model execution, audit and dashboard flows.
- Implement bulk CSV and XLSX upload on every relevant data-management page, backed by the same versioned ingestion service.
- Generate deterministic synthetic data for demonstration and model validation only. Label it clearly in the UI.
- Never present synthetic metrics as real commercial results.
- Do not fabricate prescription data, finance assumptions, causal estimates or AI answers.
- Implement loading, empty, error, insufficient-evidence and permission-denied states.
- Do not leave TODO buttons, dead navigation, placeholder charts or hard-coded dashboard results.
- Include migrations, seed data, tests, fixtures, API documentation and operating instructions.
- Use the latest stable compatible package versions available at implementation time and commit lockfiles. Avoid unmaintained packages.
- If an external LLM key is unavailable, the rest of the product must work and AI Insights must use a deterministic evidence-summary fallback.
- Completion means all acceptance tests in this README pass.

## 1. Executive summary

Pharmaceutical companies invest in HCP speaker programs to communicate approved clinical or product information. Standard reporting can show event cost, registrations, attendance and prescription activity after an event, but it cannot establish whether the event caused the observed prescribing change.

This platform creates a governed evidence chain:

```text
Fragmented company and vendor data
                -> validated and conformed data
                -> comparable attendee/control cohorts
                -> causal incremental NRx/TRx estimate
                -> finance-approved contribution and ROI
                -> future-program simulation
                -> risk-adjusted budget scenarios
                -> grounded, traceable AI explanations
```

The product is a multi-tenant analytics platform. A tenant is one pharmaceutical company. Each tenant owns brands, campaigns and events and authorizes vendors to submit specific data. Event vendors do not normally provide every data domain: operational vendors provide the records they generate; the pharmaceutical company provides brand, CRM and finance data; and an approved Rx/claims supplier provides aggregated prescription outcomes.

### One-line pitch

**Measure what the program truly changed, not merely what happened after it.**

## 2. Problem statement

An attendee may prescribe more after a program for reasons unrelated to the program:

- HCPs who already favor the product may be more likely to attend.
- Market demand or seasonality may increase prescriptions for everyone.
- Rep calls, email, samples, access changes or competitor activity may affect the outcome.
- Attendance, HCP, Rx and cost data arrive from systems with different identifiers.
- A missing attendance record does not prove that an HCP is a valid non-attendee.
- A before/after increase is correlation, not a defensible counterfactual.

The business needs to answer:

1. Which completed speaker programs produced credible incremental NRx/TRx?
2. How strong is the supporting evidence and uncertainty?
3. What financial contribution and ROI range follows from Finance-owned assumptions?
4. Which future program designs are promising?
5. How should a constrained budget be allocated across program categories?

## 3. Product boundaries and non-goals

The platform is:

- A multi-tenant data intake, causal measurement and planning product.
- A governed analytics layer over existing CRM, event, finance and licensed outcome sources.
- An evidence portal that preserves lineage from a displayed number to data and model versions.

The platform is not:

- A patient-level surveillance system.
- A replacement for CRM, event execution, contracting or payment systems.
- A system for selecting paid speakers or invitees based on actual or predicted prescribing.
- A chatbot that calculates or invents ROI.
- A guarantee of causality equivalent to a randomized controlled trial.
- A reason to treat every HCP missing from attendance as a control.

If legally and reliably linkable HCP-level outcome data are unavailable, the product must switch to account-, hospital- or territory-level analysis or report that HCP-level ROI is not estimable.

## 4. Business hierarchy and terminology

```text
Platform
└── Pharmaceutical company (tenant)
    ├── Users and authorized vendors
    └── Brand
        └── Campaign
            └── Event
                ├── Invitations and attendance
                ├── Operational vendors and costs
                ├── HCP/market context
                └── Outcome observation window
```

| Term | Definition |
|---|---|
| Tenant | One isolated pharmaceutical-company customer. |
| Brand | The marketed medicine/product family whose program impact is measured. |
| Product/SKU | A formulation, strength or pack mapped to a brand. |
| Campaign | A coordinated initiative for a brand, topic, market and period. |
| Event | One completed, cancelled or proposed speaker program within a campaign. |
| Vendor | An authorized external organization supplying an assigned data domain. |
| HCP | Healthcare professional, normally a prescriber. |
| Master HCP ID | Tenant-scoped identifier linking approved source identifiers. It is not assumed to appear on every paper prescription. |
| NRx | Vendor-defined new-prescription count for a period. Preserve the supplier definition. |
| TRx | Vendor-defined total-prescription count, normally including refills. |
| Treatment | Verified attendance at the eligible event. |
| Control | Eligible, known, unexposed non-attendee with adequate outcome history. |
| Incremental lift | Attendee change minus contemporaneous change among comparable controls. |
| Net ROI | `(incremental contribution - fully loaded cost) / fully loaded cost`. |

For the first implementation, enforce one primary brand per campaign. Keep the schema capable of multiple brands later through a campaign-brand join table, but do not implement ambiguous multi-brand attribution in the MVP.

## 5. Users, ownership and authorization

### 5.1 Operating ownership

- Commercial Insights & Analytics owns the product and methodology workflow.
- Enterprise IT/Data Engineering operates infrastructure and pipelines.
- Data Science owns models, diagnostics and validation.
- Finance owns monetary assumptions and cost approval.
- Compliance/Privacy governs permitted data use and publication.
- Brand teams consume insights but cannot alter causal methods.

### 5.2 Roles

| Role | Primary capability |
|---|---|
| Platform administrator | Create/suspend tenants and inspect platform health; no default access to tenant business data. |
| Pharma administrator | Configure tenant users, brands, campaigns, events, vendors and source mappings. |
| Vendor contributor | Upload only assigned data types for assigned campaigns/events; see own submissions and errors only. |
| Data steward | Review validation failures, identity/product mappings and quarantined rows. |
| Analytics lead | Configure analysis, run models, review diagnostics and submit results for approval. |
| Finance reviewer | Manage effective-dated contribution assumptions and approve cost/ROI scenarios. |
| Compliance reviewer | Review evidence, permitted use and publication; access audit history. |
| Brand manager | View authorized brands, compare events and create simulations/budget scenarios. |
| Executive viewer | Read-only approved portfolio results and summaries. |

### 5.3 Authentication and login experience

Authentication is a required working feature, not a visual mock.

- Use an OIDC-compatible identity provider. Run Keycloak in Docker Compose for local/demo use; keep the application compatible with Microsoft Entra ID for production.
- Disable public registration. Platform administrators invite the initial tenant administrator; tenant administrators invite tenant users and vendor contributors within their permitted scope.
- Use Authorization Code Flow with PKCE, secure HTTP-only cookies, server-side session validation, CSRF protection where applicable and short-lived tokens with refresh rotation.
- Support login, logout, expired-session handling, forced reauthentication for sensitive actions and account-disabled states. Password reset and MFA are delegated to the identity provider.
- Synchronize the external OIDC subject to the local `users` and `memberships` records. The application database remains authoritative for tenant, role, brand and vendor scopes.
- Never accept a role, tenant or vendor scope directly from browser form data as proof of authorization.

Required routes and post-login destinations:

| Identity | Landing route | Accessible areas |
|---|---|---|
| Platform administrator | `/platform/companies` | Company lifecycle, plans/configuration, platform users, service health and cross-tenant aggregate operations metadata only. |
| Pharma administrator | `/admin/company` | Own company setup, users, brands, products, campaigns, vendors, assignments and data intake. |
| Vendor contributor | `/vendor/uploads` | Assigned templates, uploads, validation errors and own submission history only. |
| Data steward | `/data-health` | Intake, mappings, quarantine and data versions for authorized tenant/brands. |
| Analytics lead | `/portfolio` | Analytics pages, specifications, model runs and review submission. |
| Finance reviewer | `/finance` | Costs, assumptions, scenarios and finance approval. |
| Compliance reviewer | `/reviews` | Pending evidence, approval history and audit records. |
| Brand manager | `/portfolio` | Authorized brands, events, simulations and budget scenarios. |
| Executive viewer | `/portfolio` | Published read-only portfolio and evidence summaries. |

Protect routes in both the Next.js server/middleware layer and FastAPI. A hidden navigation item is not an authorization control. Unauthorized access returns a safe `403`; unauthenticated access redirects to `/login` while preserving a safe return URL.

### 5.4 Administration consoles

Platform administration:

- List/search pharmaceutical companies by status, country, plan and onboarding state.
- Create tenant code/name, data region, allowed identity domains, synthetic-demo flag, feature flags and storage namespace.
- Invite the first Pharma Admin, suspend/reactivate a tenant and review platform-level audit events.
- Display only operational aggregates such as storage usage, job failures and last activity. A separate, approved break-glass workflow would be required for tenant business-data access and is out of MVP scope.

Tenant administration:

- Manage company profile, users, memberships, brand scopes and vendor contributors.
- Create brands/products and source-code mappings.
- Create campaigns/events and assign vendors plus allowed data types.
- Configure source cadence, upload templates and analysis defaults.
- Deactivation is soft/effective-dated; records referenced by published analysis cannot be hard-deleted through the UI.

### 5.5 Authorization rules

Every business record must contain `tenant_id`. Tenant context comes from the authenticated membership, never from a trusted client-supplied form field alone.

- Enforce tenant isolation in FastAPI and PostgreSQL Row Level Security.
- A user may have multiple roles and brand scopes inside one tenant.
- A vendor membership must also be scoped to `vendor_id`, campaign/event assignments and allowed dataset types.
- Platform support impersonation is disabled by default. If added, require explicit approval, reason, expiry and immutable audit logs.
- Never expose prescription outcomes, ROI or other vendors' submissions to a vendor contributor.
- All exports obey the same authorization and aggregation rules as the screen.

## 6. End-to-end user and system flow

```text
1. Platform admin creates a tenant.
2. Pharma admin configures company, brands, products and source-code mappings.
3. Pharma admin creates a campaign and events and assigns vendors/data responsibilities.
4. Company users and vendor contributors upload source files, or an API integration submits them.
5. The platform stores the immutable original file in object storage and creates an import batch.
6. A background job scans, validates, profiles and stages the records.
7. HCP, product, campaign and event identifiers are conformed; failures are quarantined.
8. Data Health shows accepted/rejected counts and allows corrected re-upload.
9. Analytics builds eligible attendee and control pools using only approved, pre-event data.
10. The propensity model and matching process create comparable cohorts.
11. Difference-in-Differences estimates incremental NRx/TRx and evidence diagnostics.
12. Finance-approved, effective-dated assumptions convert lift into contribution and ROI ranges.
13. Analytics, Finance and Compliance approve publication.
14. Approved results feed Portfolio, Event Explorer and Event Evidence.
15. Historical approved event effects train/fallback the Future Simulator.
16. The Budget Planner creates constraint-valid, risk-adjusted portfolio alternatives.
17. AI Insights retrieves approved structured evidence and explains it with citations to portal records.
```

Workflow status:

```text
DRAFT -> DATA_PENDING -> VALIDATING -> DATA_ISSUES -> READY_FOR_ANALYSIS
      -> ANALYSIS_RUNNING -> ANALYSIS_COMPLETE -> UNDER_REVIEW
      -> APPROVED -> PUBLISHED
```

Cancelled events never create treatment exposure. Published runs are immutable; corrected data creates a new data version and model run.

## 7. Portal information architecture

Use a responsive enterprise UI with a persistent tenant/brand context, global period filter, notification center and role-aware navigation. All charts require accessible table alternatives and exportable approved data.

### 7.0 UX and visual system

Build a polished analytics product rather than a generic admin template:

- Desktop-first application shell with collapsible left navigation, top tenant/brand context, page title, freshness indicator and user menu.
- Neutral light canvas, dark navy navigation, blue for primary actions, teal for positive evidence, amber for warnings and red only for failures. Never use color alone to communicate status.
- KPI cards use consistent units, comparison period, interval and evidence badge; tooltips define NRx, TRx, lift, benefit-cost ratio and net ROI.
- Charts share filters and use consistent attendee/control colors. Show uncertainty bands and exact values in accessible tooltips/tables.
- Tables support search, filtering, pagination, column visibility and stable empty/error states.
- Upload controls show accepted formats, template download, progress, cloud/object receipt, validation status and error-report download.
- Destructive or publication actions require confirmation and show their audit effect.
- Use realistic seeded values from APIs only; never embed dashboard numbers in frontend components.
- Meet WCAG 2.1 AA expectations for contrast, keyboard use, focus, labels and chart alternatives.

Corporate design direction:

- Use a modern pharmaceutical/enterprise aesthetic: navy/slate foundation, white surfaces, restrained cyan/teal accents, subtle elevation, 8 px spacing system, rounded but not playful cards and a professional sans-serif font.
- Provide light mode first and optional dark mode. Persist user preferences.
- Use skeleton loading, non-blocking notifications, breadcrumbs, command/search access, saved filters and responsive layouts for 1440 px desktop down to tablet.
- Prefer information-dense but legible dashboards. Charts must answer a business question; do not add decorative charts merely to increase chart count.

Required visualization inventory:

- Portfolio: KPI cards, spend-to-contribution waterfall, ROI/evidence scatter plot, monthly trend, brand/topic stacked bars, region heat map and evidence-coverage donut or bar.
- Event Explorer: sortable table, distribution plots and optional comparison radar only for normalized diagnostics.
- Event Evidence: attendance funnel, propensity overlap, covariate balance/love plot, pre/post counterfactual line chart with confidence band, event-study chart, causal bridge/waterfall and sensitivity/tornado plot.
- Future Simulator: input controls, predicted interval, comparable-history plot, response curve and scenario comparison.
- Budget Planner: allocation stacked bars, efficient-frontier/value-risk chart, constraint utilization and alternative comparison.
- Data & Model Health: freshness timeline, volume anomaly chart, mapping/error bars, run-duration trend, drift distributions and model-version history.

Every dashboard supports relevant global filters plus Reset, Apply, saved view, shareable URL state and authorized CSV/PDF snapshot export. Filters must be server-side for large data and their active state must appear in exports.

### 7.0.1 Data Management workspace

Data Management is an administrative workspace in addition to the seven analytical modules. Provide pages for:

- Company and source configuration.
- Brands and products.
- Campaigns and events.
- Vendors and assignments.
- HCP master and identity crosswalk.
- Invitations and attendance.
- Prescription outcomes.
- Marketing/market factors.
- Costs and Finance assumptions.

Each page supports authorized search, filters, template download, bulk CSV/XLSX upload, upload history, validation errors and safe export. Small master-data records may also have audited create/edit forms. Bulk upload always uses the central ingestion contracts; pages must not implement independent parsing logic.

### 7.1 Portfolio Overview

Purpose: summarize approved performance for the authorized tenant and brands.

Filters:

- Brand, campaign, topic, region, format and period.
- Evidence quality and publication status.

Outputs:

- Fully loaded spend.
- Invited, registered and verified reach.
- Number and percentage of events with estimable evidence.
- Incremental NRx and TRx with intervals.
- Incremental contribution, benefit-cost ratio and net ROI range.
- Performance by brand, topic, region and format.
- Evidence coverage; never silently exclude unsupported events.

Contextual uploads for Pharma Admin/Data Steward:

- Brand/product master.
- Campaign master.
- Finance assumptions.

### 7.2 Event Explorer

Purpose: compare completed programs without hiding uncertainty.

Table columns:

- Event, campaign, brand, date, topic, region and format.
- Verified attendance, analytical cohort size and total cost.
- Incremental NRx/TRx point estimate and interval.
- Net ROI range, evidence grade, status and latest run.

Functions:

- Sorting and filtering.
- Saved views.
- Approved CSV export.
- Navigate to Event Evidence.
- Comparison tray for up to four events.

Contextual uploads:

- Event master.
- Invitations/eligibility.
- Registrations/attendance.
- Event costs.

### 7.3 Event Evidence

Purpose: make one causal result understandable and auditable.

Required hierarchy:

1. Cards: cost, verified attendees, incremental NRx, ROI interval and evidence grade.
2. Funnel: invited -> eligible -> registered -> verified -> identity-resolved -> outcome-covered -> matched.
3. Counterfactual trend: attendee and matched-control monthly trends with event date.
4. Causal bridge: attendee change minus control change equals incremental effect.
5. Balance: before/after standardized mean differences and propensity overlap.
6. Evidence tests: pre-trend, placebo, alternate caliper/window and contamination status.
7. Finance panel: assumption version, value, effective dates and cost reconciliation.
8. Lineage: `data_version`, `run_id`, `model_version`, source batches and approval history.
9. AI explanation: short grounded summary with a visible "How calculated" link.

Contextual uploads:

- HCP identity crosswalk corrections.
- Rx outcome batch.
- Exposure/attendance corrections.

These uploads start a new validation/version flow and cannot overwrite a published result.

### 7.4 Future Simulator

Purpose: estimate performance for a proposed program design, not for a named prescriber.

Inputs:

- Brand, topic, region, format, timing and expected attendance.
- Specialty mix, program cost, access/market context and engagement assumptions.

Outputs:

- Predicted incremental NRx or lift per attendee.
- Prediction interval and model/fallback mode.
- Finance scenario, expected contribution and ROI interval.
- Comparable historical event categories and evidence coverage.
- Warning when history is insufficient or inputs are outside training support.

Allow upload of a batch candidate-event template. Do not accept named target HCPs as prediction inputs.

### 7.5 Budget Planner

Purpose: allocate an approved budget across candidate program designs.

Inputs:

- Total budget, candidate programs and planning period.
- Minimum/maximum by region, topic or format.
- Operational capacity, compliance eligibility and maximum concentration.
- Risk tolerance/penalty and optional exploration allocation.

Outputs:

- Recommended risk-adjusted mix.
- Conservative/base/optimistic value and ROI.
- At least two feasible alternatives.
- Constraint utilization and explanation.
- Clear infeasibility reason when no solution exists.

Support candidate-program and constraint uploads. Scenarios are drafts until explicitly saved; no optimizer output automatically approves spending.

### 7.6 AI Insights

Purpose: explain governed results in plain language.

Supported requests:

- Explain an event's evidence grade.
- Compare approved program categories.
- Summarize strong-evidence events.
- Explain a Data Health warning.
- Narrate budget scenario trade-offs.

AI flow:

```text
Question -> intent allowlist -> authorized analytics function/read-only governed view
         -> structured result + evidence references -> LLM/template explanation
         -> answer with links, assumptions, run IDs and uncertainty
```

Rules:

- The LLM never computes causal lift or ROI itself.
- No arbitrary SQL generation against raw tables.
- No patient-level or hidden cross-tenant context.
- Refuse requests to rank or target named HCPs by prescribing.
- Log question, resolved intent, referenced result IDs, model/provider and response.
- If no LLM is configured, generate a useful deterministic summary from the same structured payload.

Database grounding implementation:

- Create a governed semantic service with explicit functions such as `get_portfolio_summary`, `compare_events`, `get_event_evidence`, `get_data_health`, `get_simulation` and `compare_budget_scenarios`.
- Functions query tenant-filtered serving views using parameterized SQL and a read-only database role with statement timeout and row limits.
- The LLM selects an allowlisted function and supplies validated parameters; it does not receive database credentials or execute arbitrary SQL.
- If a limited text-to-SQL experiment is included, restrict it to approved read-only semantic views, parse/validate one `SELECT`, prohibit comments/subqueries to raw schemas/mutations, inject tenant scope server-side and enforce cost/row/time limits. It is not the default route.
- Return structured facts containing metric name, value, unit, filters, time window, evidence grade, result/run IDs and portal URL. The final answer cites these records.
- Cache only tenant/user-scope-safe results and invalidate them when a new published data version becomes active.

### 7.7 Data & Model Health

Purpose: operate and trust the product.

Show:

- Source freshness and expected delivery status.
- Upload history, checksums, row counts and processing state.
- Accepted, rejected and quarantined rows with downloadable error reports.
- Unmatched HCP/product/event IDs and match confidence.
- Outcome coverage, missing periods and sudden source-volume changes.
- Job failures, retry status and dead-letter queue.
- Active model versions, training windows, drift and last successful run.
- Evidence-gate failure counts and reasons.
- Audit/approval history.

Actions are role-limited: re-upload, correct mappings, retry an idempotent job, submit a model for approval and activate/rollback an approved version.

## 8. Technology architecture

### 8.1 Initial stack

| Layer | Choice | Responsibility |
|---|---|---|
| Web | Next.js + TypeScript + React, accessible component library, Plotly/ECharts | Role-aware portal and visualizations. |
| API | FastAPI + Pydantic + SQLAlchemy/Alembic | REST API, authorization, orchestration and OpenAPI. |
| Database | PostgreSQL | Metadata, conformed business data, results, permissions and audit indexes. |
| Object storage | MinIO locally through an S3-compatible storage interface | Immutable uploads, error reports and model/chart artifacts. |
| Jobs | Celery or Dramatiq with Redis | Upload validation, transformations, model runs and reports. |
| Data processing | Polars/Pandas + SQL | File profiling and bronze/silver/gold transformations. |
| Data quality | Pandera plus database constraints and custom contract checks | Schema and semantic gates. |
| ML | scikit-learn + XGBoost/LightGBM | Propensity and future-event prediction. |
| Causal | statsmodels plus explicit matching/DiD implementation | Effects, intervals and diagnostics. |
| Optimization | SciPy MILP or PuLP | Constrained budget scenarios. |
| MLOps | MLflow backed by PostgreSQL/object storage | Experiments, artifacts and approved versions. |
| AI | Provider abstraction supporting OpenAI-compatible APIs and deterministic fallback | Grounded explanations only. |
| Authentication | Keycloak locally; standards-based OIDC adapter for Microsoft Entra ID | Login, invitation bootstrap, claims and sessions. Never write a bespoke production password system. |
| Observability | Structured JSON logs, OpenTelemetry-compatible traces and Prometheus metrics | Operations and audit correlation. |
| Packaging | Docker Compose | Reproducible local/demo deployment. |

Use PostgreSQL schemas or clearly prefixed tables for `auth`, `core`, `ingestion`, `analytics`, `ml` and `audit`. Keep infrastructure adapters behind interfaces so PostgreSQL/MinIO can later coexist with an Azure lakehouse rather than requiring business-logic rewrites.

### 8.1.1 Enterprise database requirements

- Use Alembic migrations only; application startup must not create production tables implicitly.
- Enable PostgreSQL Row Level Security on every tenant-owned table and set tenant/user context per transaction using a safe server-controlled mechanism.
- Use composite indexes beginning with `tenant_id` for common tenant-scoped lookups.
- Partition high-volume `hcp_rx_monthly`, activity and audit data by time, with tenant-aware indexes. Seed/demo deployment may use fewer physical partitions while preserving migration support.
- Use normalized transactional tables for configuration and ingestion metadata; create explicit materialized views/serving tables for dashboard queries rather than issuing expensive joins from every chart.
- Use `NUMERIC` for monetary/rate values, `DATE`/timezone-aware timestamps, PostgreSQL enums or checked reference tables for states, and JSONB only for variable metadata—not as a replacement for the core schema.
- Use optimistic concurrency/version columns for editable configuration and database constraints for invariants.
- Use connection pooling, bounded transactions, statement timeouts for interactive requests and separate read-only credentials for governed AI/query services.
- Maintain `created_at`, `created_by`, `updated_at`, `updated_by` and effective dates where appropriate. Published analytical records are append-only/versioned.
- Provide backup, point-in-time recovery and replica recommendations in the production runbook. Test a local backup/restore as part of release verification.

### 8.2 Logical flow

```text
Browser
  -> Next.js
  -> FastAPI
       -> PostgreSQL
       -> S3-compatible object storage
       -> Redis/job worker
              -> validation/conformance
              -> feature/cohort build
              -> ML/causal/ROI/forecast/optimizer
              -> MLflow/artifacts
```

### 8.3 Storage zones

Object keys must be deterministic and tenant-scoped:

```text
raw/{tenant_id}/{dataset_type}/{yyyy}/{mm}/{upload_id}/{original_filename}
quarantine/{tenant_id}/{upload_id}/rejected_rows.parquet
reports/{tenant_id}/{upload_id}/validation_report.json
artifacts/{tenant_id}/{run_id}/...
```

- Raw: immutable original bytes plus checksum, MIME type and metadata.
- Silver: validated/conformed rows stored primarily in PostgreSQL for the initial implementation; large intermediate Parquet may live in object storage.
- Gold: analysis panels, matches, effects and serving views with data/run versions.

## 9. Core data model

Use UUID primary keys internally, human-readable codes as tenant-scoped unique business keys, UTC timestamps and explicit effective dates. Store currency as ISO code and money as decimal/numeric, never floating point.

### 9.1 Tenancy and access

- `tenants`: id, code, name, status, country, data_region, synthetic_mode, plan/configuration and storage namespace.
- `tenant_identity_domains`: tenant_id, verified domain, identity-provider configuration and status.
- `tenant_features`: tenant_id, feature key, enabled state, limits and effective dates.
- `users`: identity issuer, external_subject, email, display_name, status and last login.
- `memberships`: tenant_id, user_id, role, status and effective dates.
- `membership_brand_scopes`: membership_id, brand_id.
- `user_invitations`: tenant_id, email, intended role/scopes, inviter, one-time token hash, expiry and acceptance status.
- `vendors`: tenant_id, code, name, status, contact metadata.
- `vendor_assignments`: vendor_id, campaign_id/event_id, dataset_type, valid_from/to.

### 9.2 Commercial hierarchy

- `brands`: tenant_id, code, name, therapeutic_area, molecule, active dates.
- `products`: tenant_id, brand_id, code, formulation, strength, pack, active dates.
- `product_code_crosswalk`: tenant_id, source_system, source_code, product_id, match_status, effective dates.
- `campaigns`: tenant_id, code, name, objective, topic, start/end and status.
- `campaign_brands`: tenant_id, campaign_id, brand_id, is_primary and cost allocation; enforce exactly one primary brand in the MVP.
- `events`: tenant_id, campaign_id, code, date/time, topic, format, region, venue, speaker reference and status.
- `event_vendor_assignments`: tenant_id, event_id, vendor_id, responsibility and cost category.

### 9.3 HCP, exposure and outcomes

- `hcps`: tenant_id, master_hcp_id, specialty, region, practice_type, segment, active status.
- `hcp_identifiers`: tenant_id, hcp_id, source_system, source_hcp_id, match_method, confidence, status, effective dates.
- `event_invitations`: tenant_id, event_id, hcp_id, invitation status/date/channel and eligibility reason.
- `event_attendance`: tenant_id, event_id, hcp_id, registration status, verified_attended, verification source and join/leave/duration.
- `hcp_rx_monthly`: tenant_id, hcp_id, product/brand, month, nrx, trx, competitor_trx, observed/projected, coverage factor, suppression flag, supplier definition version.
- `marketing_activity`: tenant_id, hcp_id, date/month, rep calls, email, sample or other-event exposure.
- `market_factors`: tenant_id, brand/market, region, month, access index, seasonality and competitor index.
- `event_costs`: tenant_id, event_id, category, vendor, amount, currency, invoice reference and approval status.
- `finance_assumptions`: tenant_id, brand_id, scenario, contribution_per_nrx or explicit fill-based components, currency, effective dates, owner and approval.

### 9.4 Ingestion and lineage

- `upload_batches`: tenant, uploader, vendor, dataset_type, original object key, checksum, row count, status and timestamps.
- `upload_rows/quarantine_issues`: tenant_id, batch, row number/source key, error code, severity, field and safe message.
- `data_versions`: tenant, included batch IDs, code version, status and creation metadata.
- `source_expectations`: tenant/vendor/dataset, cadence, due time and freshness SLA.

### 9.5 Analytics and ML

- `analysis_specs`: tenant_id, outcome, pre/post windows, control rules, caliper, ratio, exclusions and version.
- `cohort_rows`: tenant_id, run/event/HCP, treatment, eligibility, exclusion reason and weights.
- `propensity_scores`: tenant_id, run/event/HCP, score and model version.
- `matched_pairs`: tenant_id, run/event/treated HCP/control HCP, distance and weight.
- `balance_diagnostics`: tenant_id, run/event/feature, SMD before/after and pass flag.
- `effect_estimates`: tenant_id, run/event/brand/outcome, point estimate, standard error, interval, cohort sizes and evidence status/grade.
- `sensitivity_results`: tenant_id, run/event/test name, specification, estimate and pass status.
- `roi_results`: tenant_id, effect result, finance-assumption version, cost, contribution, benefit-cost ratio and net ROI interval.
- `model_versions`: tenant_id, model type, artifact URI, training data version, metrics, approval and active state.
- `model_runs`: tenant, type, status, parameters, data/code/model versions, start/end and failure.
- `forecast_results`, `simulation_scenarios`, `optimizer_runs` and `optimizer_allocations`.
- `ai_interactions`: tenant/user, question, intent, evidence IDs, provider/model, response hash and timestamp.
- `audit_events`: append-only actor, action, resource, before/after metadata, request ID and timestamp.

Required unique constraints include tenant plus business code, HCP/source identifier validity, event-HCP invitation and attendance identity, HCP-product-month-source identity and idempotency key for upload/job requests.

## 10. Data intake contracts

### 10.1 Supported initial datasets

| Dataset type | Expected owner | Minimum fields |
|---|---|---|
| Brand/product master | Pharma admin | brand/product codes, names, hierarchy and effective dates. |
| Campaign/event master | Pharma/event operations | campaign/event code, brand, date, topic, format, region and status. |
| HCP master | CRM/MDM | source HCP ID, specialty, region, segment and active flag. |
| HCP crosswalk | MDM/data steward | source system/ID, master ID, status and confidence. |
| Invitations | CRM/event vendor | event code, HCP source ID, invited date/status and eligibility. |
| Attendance | Event/webinar vendor | event code, HCP source ID, registration and verified attendance evidence. |
| Rx monthly | Licensed Rx/claims provider | HCP source ID, product code, month, NRx/TRx, coverage/projection metadata. |
| Marketing activity | CRM/channel systems | HCP source ID, date, channel/activity and quantity. |
| Event cost | Vendors/Finance | event, category, amount, currency, invoice and approval. |
| Market factors | Approved market source | market/region/month and access/competitor indices. |
| Finance assumptions | Finance | brand, scenario, contribution value, currency and effective dates. |
| Candidate programs | Brand/Finance | design inputs, cost and eligibility. |

### 10.2 Upload API and state machine

```text
CREATED -> UPLOADED -> SCANNING -> VALIDATING -> CONFORMING
        -> ACCEPTED | PARTIALLY_ACCEPTED | REJECTED | QUARANTINED
```

Upload process:

1. Request an upload session with dataset type and scoped campaign/event.
2. Authorize vendor assignment and file constraints.
3. Stream to object storage; never load an unbounded file fully into memory.
4. Calculate SHA-256 and reject duplicate bytes idempotently unless explicitly versioned.
5. Record immutable receipt: upload ID, object key, checksum, size, uploader and timestamp.
6. Scan file type/content, parse in a worker and validate the declared schema.
7. Validate tenant-scoped references and effective dates.
8. Conform IDs and place unresolved/ambiguous rows in quarantine.
9. Commit accepted rows transactionally under a new batch/data version.
10. Produce machine-readable JSON plus human-readable CSV error reports.

Validation gates:

- Allowed extension and MIME signature; configurable size and row limits.
- Header/schema version, required fields and data types.
- Unique keys and duplicate handling.
- Valid campaign/event/vendor assignment.
- Dates, event windows and event status.
- Non-negative Rx/cost counts and valid currency.
- Product and HCP identity match state.
- Missing period versus genuine zero outcome.
- Cost reconciliation and outcome-coverage thresholds.
- Cross-tenant identifiers always fail closed.

Never log file contents, access tokens or sensitive free text.

### 10.3 Bulk CSV/XLSX upload experience

Bulk upload is required for every data-collection domain and must work from its contextual page and from a central `/data/uploads` workspace.

1. User selects/downloads a versioned template for the dataset type.
2. User selects company context automatically from the session, then permitted brand/campaign/event/vendor scope.
3. User drops one or more `.csv` or `.xlsx` files and sees file size, type and selected scope.
4. The client requests an upload session and transfers bytes directly/streamingly to object storage through an authorized API or short-lived signed upload.
5. A background worker parses in chunks and creates a preview: headers, inferred types, first safe rows and mapping warnings.
6. For non-template files, an optional column-mapping wizard maps source headers to the approved contract and saves a tenant/source mapping version.
7. User confirms processing; validation results appear asynchronously with accepted/rejected/quarantined counts.
8. User downloads a row-level error workbook/CSV, corrects it and re-uploads as a new batch linked to the original.

CSV requirements:

- Support UTF-8/UTF-8 BOM, quoted fields and configurable delimiter detection with an explicit confirmation.
- Neutralize formula injection on generated exports.
- Stream/chunk large files; configurable initial limit of 250 MB and 1,000,000 rows per file.

XLSX requirements:

- Accept `.xlsx`, reject macro-enabled `.xlsm` and legacy binary `.xls` in the MVP.
- Require or let the user select the expected worksheet; ignore hidden sheets unless explicitly permitted.
- Read cached values, never execute formulas or macros, and reject encrypted workbooks.
- Preserve original row number in all validation errors.

Provide downloadable example templates and data dictionaries for every supported dataset. Upload progress and processing progress are separate states.

## 11. Synthetic data factory

Synthetic data exists for demo, development and estimator validation. It is not a substitute for production data onboarding.

Generate two deterministic profiles from one seed: `smoke` for fast automated tests and `full` for judging, model training and performance testing. The full profile must satisfy the minimum sample requirement below.

Full-profile minimums across the seeded SaaS environment:

| Synthetic domain | Minimum |
|---|---:|
| Pharmaceutical tenants | 2 |
| Brands | 5 per primary demo tenant |
| HCP master records | 5,000 per tenant |
| Historical completed events | 5,000 total, with sufficient events per supported segment |
| Invitations/eligible HCP-event rows | 50,000 |
| Verified attendance rows | 5,000 |
| HCP-product-month Rx rows | 250,000 |
| Marketing/market activity rows | 50,000 |
| Event cost rows | At least one fully loaded record for every event |
| Propensity training examples | At least 5,000 eligible HCP-event rows in both training and held-out evaluation combined |
| Future-model event examples | At least 5,000 measured/synthetic historical event rows before splitting |
| Causal validation cases | At least 5,000 treated/control HCP-event analytical rows across heterogeneous effect cases |

Small reference/configuration tables such as currencies and status codes are exempt from the 5,000-row rule. The generator must assert these minimums and fail if they are not met.

Generate from the full seed:

- At least two fictional tenants with strict isolation tests.
- Two to three brands per tenant.
- Multiple campaigns, 250-300 historical events and several vendors.
- At least 5,000 HCPs per tenant as specified above.
- 18-24 months of HCP-product-month outcomes.
- Invitations, verified attendance, marketing exposures, market factors and fully loaded costs.
- Source-specific HCP/product/event IDs requiring crosswalks.
- Missing months, unmatched IDs, duplicate attendance, cancelled events, cost outliers and overlapping exposure.
- A hidden `causal_ground_truth` artifact that is never available to application users or training features.

Simulate intentional selection bias: latent opportunity, affinity, prior engagement, topic fit, rep activity and travel friction influence attendance. Simulate over-dispersed count outcomes with market trend, seasonality, access, competitor pressure and heterogeneous, decaying event effects. Include zero-effect and negative/ineffective events.

Every synthetic page must display a persistent `Synthetic demonstration data` badge. Seed scripts must be deterministic and safe to rerun.

Train the propensity and future-event models from the generated full Gold datasets during a documented bootstrap/training command. Persist metrics, data version, seed, feature schema and artifacts in MLflow. Do not merely serialize random pretrained artifacts.

## 12. Analytical methodology

### 12.1 Cohort construction

Initial clean-cohort defaults:

- Primary outcome: NRx in the 90-day post-event period.
- Secondary outcome: TRx.
- Require six pre-event months and three post-event months.
- Use the HCP's first eligible related event.
- Exclude another related exposure within 90 days unless a later approved method models it.
- Treatment requires verified attendance.
- Preferred controls are invited, eligible non-attendees; if unavailable, use an approved target-universe rule with verified non-exposure.
- Exclude unresolved identity, insufficient outcome coverage, cancelled events and unsupported market periods.

Store every exclusion reason and show the funnel.

### 12.2 Propensity and matching model

Purpose: estimate likelihood of attendance and create comparable groups; it does not estimate Rx lift.

- Grain: one eligible HCP-event row.
- Target: verified attendance.
- Features: pre-event HCP profile, 3/6-month Rx level and trend, competitor share, prior engagement/events, topic fit, format/travel friction and market/access context.
- Leakage rule: no feature observed after the event or caused by attendance.
- Validation: grouped by event and temporal where possible.
- Matching: exact constraints on required categories plus nearest-neighbor propensity matching; configurable caliper default 0.05 and 1:2 control ratio.
- Do not force matches outside common support.
- Persist scores, pairs, distances and weights.

Primary success is balance, not classifier AUC:

- Important post-match standardized mean differences below 0.10.
- Adequate overlap.
- Acceptable matched-treated retention.
- No unsupported subgroups silently retained.

### 12.3 Causal effect

For explanation:

```text
Attendee change = attendee post NRx - attendee pre NRx
Control change  = weighted control post NRx - weighted control pre NRx
Incremental NRx = attendee change - control change
```

For implementation, use the monthly panel with HCP and calendar-month effects, treatment/post interaction, match weights and appropriately clustered uncertainty. Store event-study leads/lags. A future scaled implementation may replace this estimator with a validated staggered-adoption method without changing result contracts.

Evidence gates:

- Minimum samples and outcome coverage.
- Balance and overlap.
- No meaningful differential pre-trend.
- Placebo dates near zero.
- Sensitivity to alternate calipers, control definitions and post windows.
- No material contamination.

Failure output is `NOT_RELIABLY_ESTIMABLE` plus reason, not zero lift and not a ranked ROI.

### 12.4 Evidence grade

Derive a transparent grade from hard gates and diagnostics:

- Strong: all critical gates pass and sensitivity is stable.
- Moderate: core gates pass with limited sample/coverage or mild sensitivity.
- Directional: estimate shown for exploration with prominent limitations; excluded from optimization by default.
- Not estimable: critical gate fails.

Do not create an opaque ML confidence score.

### 12.5 Finance and ROI

Finance supplies and approves the monetary assumption. Support either a direct net contribution per incremental NRx or an explicit component model:

```text
Incremental contribution = incremental NRx * approved contribution per NRx
Net benefit              = incremental contribution - fully loaded event cost
Benefit-cost ratio       = incremental contribution / event cost
Net ROI                  = net benefit / event cost
```

Propagate the causal interval through the finance calculation and show conservative/base/optimistic versions. Never infer margin from product name, external web data or the LLM. Block publication if cost is missing/unapproved or the applicable finance version is absent.

### 12.6 Future program model

- Target: approved historical causal event effect, preferably lift per attendee—not raw post-event NRx.
- Inputs: design and context known before the proposed event; no named-HCP prescription targeting.
- Validation: temporal holdout plus entire-event grouping.
- Metrics: MAE, bias by segment and prediction-interval coverage versus a historical-average baseline.
- If history is insufficient (approximately fewer than 100-200 measured supported events, configurable), fall back to partial pooling/shrinkage or transparent category averages and label low confidence.
- Warn on out-of-support inputs.

### 12.7 Budget optimization

Optimize risk-adjusted expected net value:

```text
maximize sum(selected quantity * (expected contribution - cost - risk penalty))
subject to budget, capacity, calendar, region/topic bounds,
           concentration limits and compliance-approved design types
```

Use integer quantities where programs are indivisible. Verify constraints after solving. Return explicit infeasibility diagnostics and alternatives; never silently relax a user constraint.

### 12.8 How new production data feed models

Separate measurement, inference and retraining. Uploading a file must not automatically replace a production model.

```text
New CSV/XLSX/API batch
  -> immutable raw upload + validation
  -> identity/product/event conformance
  -> approved data version
  -> point-in-time Gold feature snapshots
  -> eligibility/coverage gates
  -> scoring or causal measurement with active model/specification
  -> draft results and diagnostics
  -> human review/publication
  -> drift/retraining eligibility assessment
  -> challenger training and temporal evaluation
  -> analytics/compliance approval
  -> champion activation or rejection
```

Rules by model:

- Propensity: score eligible HCP-event rows with features frozen before the event. Retrain on a schedule or after approved-data volume/drift thresholds, not after each upload.
- Causal engine: it is an estimator, not a supervised prediction model. Re-run an event only when its required post-period outcome data and coverage are complete; create a new immutable run.
- Future model: score proposed designs using the active champion. Retraining uses newly approved historical event effects only after their causal evidence is finalized.
- Optimizer: rerun when candidate designs, active forecasts, Finance assumptions or constraints change; persist all input versions.

Required model lifecycle states:

```text
DRAFT -> TRAINING -> VALIDATING -> CHALLENGER -> PENDING_APPROVAL
      -> ACTIVE | REJECTED -> RETIRED
```

Retraining triggers are configurable and include minimum new supported events, feature-distribution drift, outcome/performance drift, interval undercoverage and scheduled review. A failed challenger leaves the current champion active. Maintain backward-compatible feature-schema versions and block scoring when required features are missing rather than silently filling unsafe defaults.

## 13. API specification

Expose versioned REST APIs under `/api/v1`. Generate OpenAPI and a typed frontend client.

Minimum resources:

- `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/me` and session refresh/reauthentication endpoints as required by the OIDC implementation.
- `/platform/tenants`, `/platform/tenants/{id}/status`, `/platform/admin-invitations` for Platform Admin only.
- `/tenants/current`, `/memberships`, `/invitations` and `/role-scopes` for tenant administration.
- `/brands`, `/products`, `/product-crosswalks`.
- `/campaigns`, `/events`, `/vendors`, `/vendor-assignments`.
- `/uploads/sessions`, `/uploads/{id}`, `/uploads/{id}/errors`, `/uploads/{id}/retry`.
- `/data-health/summary`, `/identity-issues`, `/mapping-decisions`.
- `/portfolio`, `/events/explorer`, `/events/{id}/evidence`.
- `/analysis-specs`, `/analysis-runs`, `/analysis-runs/{id}`.
- `/finance-assumptions`, `/roi-results`.
- `/simulations`, `/simulations/{id}`.
- `/budget-scenarios`, `/budget-scenarios/{id}`.
- `/ai/query`, `/ai/interactions/{id}`.
- `/audit-events` for authorized reviewers.

Use cursor pagination for large lists, validated filters, explicit sortable columns and stable error envelopes. Mutations support an idempotency key. Long-running endpoints return `202 Accepted` with a job/run ID. Never hold an HTTP request open for model training.

All frontend data access uses the generated API client and centralized query/cache handling. Do not connect the browser directly to PostgreSQL, Redis, MinIO administration APIs or MLflow. Use WebSocket or Server-Sent Events only for authorized progress notifications; normal dashboards use cacheable REST queries.

## 14. Background jobs and reproducibility

Jobs:

- File scan/profile/validation.
- Conformance and data-version publication.
- Cohort/feature build.
- Propensity training/scoring and matching.
- Causal estimation and sensitivity suite.
- ROI calculation.
- Forecast training/scoring.
- Budget optimization.
- AI deterministic-summary precomputation.

Each job records tenant, input data version, analysis specification, code commit, random seed, model version, parameters, output artifact URIs, status, attempts and error category. Jobs must be idempotent and safe to retry. Use a dead-letter state after bounded retries.

Every displayed analytical number must resolve to:

```text
tenant_id + data_version + run_id + model_version + finance_version
```

## 15. Security, privacy and compliance controls

- Treat all uploaded data as untrusted.
- Encrypt transport; use secure cookies and CSRF protection where applicable.
- Use OIDC, short-lived access, least privilege and tenant-aware RBAC.
- Enable PostgreSQL Row Level Security and test it using adversarial cross-tenant queries.
- Use private object buckets; issue short-lived download URLs only after authorization.
- Virus/content scan uploads; reject macros/executables and formula injection in exported CSV.
- Keep secrets in environment/secret storage; never commit credentials.
- Do not ingest patient names, phone numbers, addresses, prescription images or ABHA identifiers for this use case.
- Apply configurable retention and deletion policies while preserving legally required audit evidence.
- Make audit events append-only at the application layer and restrict database mutation rights.
- Suppress or aggregate small cohorts according to tenant policy.
- Require approval before model activation and result publication.
- Clearly state observational limitations and jurisdiction-specific review requirements.
- Prohibit named-HCP prescribing rankings for speaker/attendee selection.

## 16. Observability and operations

Use a request/correlation ID from browser through API, job and model run.

Track:

- API latency/error rate and authorization denials.
- Upload throughput, validation duration and failure reasons.
- Source freshness and volume anomalies.
- Queue depth, retry/dead-letter counts and job duration.
- Model run success, drift, coverage and evidence-gate failures.
- Database/object-store availability and capacity.
- AI provider latency, fallback rate and evidence-resolution failures; do not log sensitive prompt payloads indiscriminately.

Provide `/health/live` and `/health/ready`. Readiness must verify required dependencies. Include backup/restore instructions for PostgreSQL and object metadata plus a tested restore procedure for production deployment.

## 17. Repository structure

```text
speaker-roi/
├── README.md
├── .env.example
├── compose.yaml
├── Makefile or task runner
├── apps/
│   ├── web/                     # Next.js/TypeScript portal
│   ├── api/                     # FastAPI application
│   └── worker/                  # background job entry point
├── packages/
│   ├── contracts/               # shared schemas/generated API types
│   └── ui/                      # shared accessible UI components
├── analytics/
│   ├── ingestion/
│   ├── synthetic/
│   ├── cohorts/
│   ├── propensity/
│   ├── causal/
│   ├── forecast/
│   ├── optimization/
│   └── ai/
├── migrations/
├── data_contracts/              # versioned CSV/Parquet contracts and templates
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── security/
│   └── model_validation/
├── scripts/
│   ├── bootstrap
│   ├── seed_demo
│   ├── reset_demo
│   └── verify
└── docs/
    ├── architecture.md
    ├── data_dictionary.md
    ├── api.md
    ├── model_card.md
    ├── threat_model.md
    ├── runbook.md
    └── azure_migration.md
```

Keep analytics code independent of FastAPI request objects and UI state. Define repositories/storage adapters and services so infrastructure can change without rewriting causal logic.

## 18. Local development and demo experience

Required commands, adjusted to the chosen task runner:

```text
copy .env.example .env
docker compose up --build
run migrations
seed deterministic demo data
run all verification checks
```

Docker Compose services:

- `web`, `api`, `worker`.
- `postgres`, `redis`, `minio`.
- `keycloak` with an imported development realm, clients, roles and seeded demo identities.
- `mlflow` if not embedded in worker deployment.

Seed fictional users for each role and document credentials strictly for local demo. Include two tenants and an automated test proving that users from Tenant A cannot retrieve Tenant B records even by guessing UUIDs.

The application must remain demoable without internet. Cache/precompute seeded model results if runtime is too long, but include a live small-event rerun that executes real code. AI fallback must remain available offline.

## 19. Test strategy

### 19.1 Data tests

- Contract/schema versions and parsing.
- Key uniqueness, references and effective dates.
- Missing versus zero outcomes.
- Crosswalk ambiguity and quarantine.
- Duplicate attendance reconciliation.
- Cancelled/overlapping event exclusions.
- Currency and cost reconciliation.
- Upload idempotency and duplicate checksum behavior.

### 19.2 Model tests

- No post-event leakage in feature snapshots.
- Grouped/temporal split integrity.
- Matching balance and common support.
- Known synthetic portfolio effect recovered within predefined tolerance, initially 10-15%.
- Placebo dates near zero.
- Sensitivity result stability.
- Unsupported event returns not-estimable.
- Forecast beats or explicitly falls back to baseline.
- Prediction intervals have measured coverage.
- Optimizer always satisfies constraints or returns infeasible.

### 19.3 API/security tests

- Authentication and role/brand/vendor scopes.
- PostgreSQL RLS cross-tenant isolation.
- Object download authorization.
- Upload validation, traversal-safe names and malicious file rejection.
- Rate limits and bounded pagination.
- Immutable published versions and audit history.
- AI allowlisted intents, prompt-injection attempts and named-HCP targeting refusal.

### 19.4 UI/E2E tests

- Each role's navigation and forbidden actions.
- Upload -> validation -> correction -> accepted flow.
- Analysis run -> review -> publish flow.
- All seven pages with loading/empty/error/no-evidence states.
- Filters change queries and displayed values consistently.
- Event Evidence charts match the structured API payload.
- Simulator and optimizer persist/reload scenarios.
- Accessibility keyboard navigation and meaningful labels.

## 20. Implementation sequence and definition of done

### Phase 1: Foundation

- Repository, Docker Compose, CI, formatting and test runners.
- Working Keycloak/OIDC login/logout/session flow, protected routes and role-specific landing pages.
- Platform-admin company console plus tenant-admin user, brand and vendor management.
- Tenants, roles, brand/vendor scopes and PostgreSQL RLS.
- Core hierarchy and migrations.

Done when all seeded roles log in to the correct landing page, forbidden routes/API calls fail, a Platform Admin can create/suspend a tenant, and automated cross-tenant isolation tests pass.

### Phase 2: Intake and conformance

- Object-storage adapter, upload sessions, receipts, checksums and jobs.
- Dataset templates, bulk CSV/XLSX upload, versioned validation and quarantine workflow on every relevant Data Management page.
- Brand/product/event/HCP crosswalks and Data Health.

Done when a vendor can upload a file, receive row-level safe errors, correct it and publish an accepted data version.

### Phase 3: Synthetic factory

- Deterministic multi-tenant source-equivalent files, all specified 5,000+ training/case minimums and hidden truth.
- Realistic confounding, imperfections and reproducibility tests.

Done when one command rebuilds identical full demo data, asserts minimum sample counts, trains real models, and hidden truth is inaccessible from application APIs.

### Phase 4: Measurement engine

- Eligibility, pre-event feature snapshots, propensity, matching and balance.
- Monthly-panel DiD, event study, intervals, placebo/sensitivity gates.
- Finance versions and ROI propagation.

Done when synthetic recovery and placebo tests pass and unsupported events publish no ROI.

### Phase 5: Evidence portal

- Portfolio Overview, Event Explorer and Event Evidence.
- Modern corporate shell, full filter behavior and the required chart inventory with accessible data alternatives.
- Review/approval workflow, lineage and exports.

Done when every displayed metric links to a structured result and full version chain.

### Phase 6: Planning

- Future model with temporal validation and fallback.
- Simulator and constrained Budget Planner.

Done when out-of-support and infeasible states are explicit and all returned allocations satisfy constraints.

### Phase 7: AI Insights

- Allowlisted intent router, governed read-only database functions, API integration, evidence citations and deterministic fallback.

Done when grounded-number and adversarial access tests pass and the app works without an LLM key.

### Phase 8: Hardening

- Observability, retry/dead-letter behavior, backup/restore, performance and security tests.
- Complete documentation, model card, runbook and Azure migration guide.

Done when `scripts/verify` runs migrations, unit/integration/security/model/E2E smoke tests and returns success on a clean checkout.

## 21. Final acceptance criteria

The build is complete only when:

1. The full application starts from documented commands on a clean machine with Docker.
2. Keycloak/OIDC login, logout, session expiry and role-specific redirect/protected-route behavior work for all roles.
3. The Platform Admin can create, configure, invite an initial admin for, suspend and reactivate pharmaceutical-company tenants.
4. Multiple pharma-company tenants, brands, campaigns, events and vendors are implemented.
5. Tenant, role, brand and vendor assignment isolation is enforced in UI, API, PostgreSQL RLS and object access and is tested.
6. Every relevant Data Management page has functioning versioned bulk CSV/XLSX upload, template and validation/error workflow.
7. Contextual uploads physically persist to object storage and show immutable receipts.
8. Validation, conformance, mapping, quarantine and corrected re-upload work end to end.
9. Synthetic data are deterministic, realistic, visibly labelled and satisfy every specified minimum sample count.
10. Bootstrap training produces real registered propensity and future-model artifacts with held-out metrics.
11. Propensity matching produces stored pairs and balance diagnostics.
12. The causal engine estimates NRx/TRx lift, uncertainty and evidence gates and recovers synthetic truth within tolerance.
13. New approved data create versioned features/scores/runs; retraining creates a challenger and never silently replaces the champion.
14. ROI uses only approved, versioned Finance inputs and fully loaded costs.
15. Portfolio Overview, Event Explorer, Event Evidence, Future Simulator, Budget Planner, AI Insights and Data & Model Health are functional, modern, filterable and use the required evidence visualizations.
16. The forecast uses measured causal targets and falls back when history is insufficient.
17. The optimizer produces constraint-valid alternatives or an explicit infeasibility result.
18. AI queries the governed database semantic layer through authenticated APIs, answers only from authorized structured evidence, links its sources and works in fallback mode.
19. Every analytical result has tenant, data, run, model and finance lineage.
20. No critical tests, dead controls, hard-coded business results or unresolved placeholder tasks remain.

## 22. Expected outcome

At completion, a judge or stakeholder can:

1. Log in as a pharma administrator and see only the assigned company.
2. Create a brand, campaign, event and vendor assignment.
3. Upload event/attendance/Rx/cost data and see the file in the intake audit with accepted and rejected records.
4. Resolve an HCP mapping issue and create a new data version.
5. Run a real cohort, matching and causal-analysis job.
6. Inspect why one event has strong evidence and another is not estimable.
7. See Finance-controlled contribution and ROI intervals.
8. Configure a future program and receive a supported prediction or transparent fallback.
9. Allocate a constrained budget and compare feasible alternatives.
10. Ask AI for an executive explanation and follow links to the exact evidence.

The differentiator is not a particular classifier or chatbot. It is the complete, defensible chain from fragmented vendor/company data to governed causal evidence and planning decisions.

## 23. Azure migration path

The first release intentionally avoids making Azure setup a prerequisite. Preserve these replacement seams:

| Initial component | Azure target | Migration expectation |
|---|---|---|
| MinIO/S3 adapter | Azure Data Lake Storage Gen2 | Implement an ADLS storage adapter; keep logical object paths and upload metadata. |
| Portal/API upload jobs | Azure Functions/Event Grid | Replace trigger transport, not validation contracts. |
| Celery/Dramatiq orchestration | Azure Data Factory for scheduled sources plus durable job orchestration | Keep run/idempotency contracts. |
| Polars/Pandas workers | Databricks/Spark for scale | Preserve bronze/silver/gold schemas and result contracts. |
| PostgreSQL | Azure Database for PostgreSQL; optional warehouse/lakehouse serving | Retain tenant/business metadata and RLS design. |
| Local OIDC | Microsoft Entra ID | Map groups/claims to existing memberships and scopes. |
| Local MLflow | Managed/hosted MLflow-compatible registry | Preserve model version and artifact lineage. |
| Local metrics/logs | Azure Monitor/Application Insights | Preserve correlation IDs and semantic events. |

Do not move raw uploaded files into PostgreSQL merely to simplify the first release. The object-storage abstraction is what makes the later ADLS pivot straightforward.

## 24. Demo narrative

1. Enter Tenant A and show that Tenant B is inaccessible.
2. Open a CardioMax campaign containing several events and vendors.
3. Upload attendance data; show immutable receipt, validation and two quarantined HCP IDs.
4. Resolve one mapping and publish a new data version.
5. Show naive attendee growth, then matched-control growth and the smaller defensible incremental lift.
6. Open Event Evidence and explain balance, pre-trend, placebo, interval and finance version.
7. Show a second event marked not reliably estimable.
8. Simulate a future program, then optimize a fixed budget under region/risk constraints.
9. Ask AI why the top raw-growth event is not the strongest evidence event.
10. Close with: every recommendation traces to source batches, matched controls, causal evidence and an approved financial assumption.

## 25. Reference principles

Implementation and compliance decisions should be checked against current authoritative sources and tenant-specific legal review, including:

- HHS-OIG Special Fraud Alert on Speaker Programs.
- Applicable privacy/de-identification guidance and data-license terms.
- FDA/market-specific rules for truthful and non-misleading promotion.
- PostgreSQL Row Security Policies documentation.
- FastAPI security and deployment guidance.
- Current multi-period Difference-in-Differences literature and maintained implementations.
- The tenant's approved Rx supplier data dictionary; supplier definitions of NRx/TRx are authoritative.

Jurisdiction-specific compliance, privacy, promotional and data-use requirements must be validated before production. The included demonstration uses fictional synthetic data and contains no patient-identifiable information.
