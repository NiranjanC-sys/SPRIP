# Plan Review — Contradictions, Risks and Binding Decisions

> Reviewer: implementation engineering
> Date: 2026-08-19
> Subject: `plan.md` — "HCP Speaker Program Impact & ROI Platform"
> Status: **Decisions below are binding for this build.** `plan.md` is preserved verbatim as
> the original brief; where this document disagrees with it, this document wins and says why.

The brief is unusually good: the causal framing is correct, the governance model is correct, and
the refusal to let an LLM compute ROI is correct. The problems are not in the vision — they are in
(a) three internally inconsistent numeric sections, (b) a genuinely confused ML section, and
(c) two infrastructure choices that would make the product undemonstrable on a clean machine.

Each finding below is numbered `F-n`, rated, and closed with a decision.

---

## Summary table

| # | Area | Severity | Finding | Decision |
|---|---|---|---|---|
| F-1 | ML pipeline | **Blocker** | Three unrelated models are described as one "ML pipeline"; the forward-looking model — the actual business ask — is under-specified and circularly defined | Split into 4 named models with distinct contracts; build M3 as a shrinkage + conformal-interval forecaster |
| F-2 | Synthetic minimums | **Blocker** | §11 contradicts itself: 5,000 events **and** "250–300 historical events"; 5,000 events with 5,000 attendance rows = 1 attendee/event | Resolve upward to a self-consistent generator; assert every stated minimum |
| F-3 | Auth | **High** | Keycloak as the required login path makes a clean-machine, offline demo fragile (extra DB, realm import, ~1 GB, slow first boot) | Two real providers: `local` (invite-only, Argon2id, TOTP) default; `oidc` (PKCE) for Keycloak/Entra. Neither is a mock |
| F-4 | Forecast target | **High** | §12.6 trains on a *noisy estimate* with no measurement-error handling; cold-start is impossible as written | Inverse-variance weighting + empirical-Bayes partial pooling + explicit support gate |
| F-5 | MLflow | Medium | MLflow described as the registry, but acceptance criteria read `model_versions` in Postgres — two sources of truth | Postgres registry authoritative; MLflow optional compose profile for experiment tracking |
| F-6 | Propensity exposure | **High / compliance** | A per-HCP propensity score is one join away from the "rank named HCPs" behaviour §3 forbids | Scores never leave the analytics tier at HCP grain; API exposes distributions/diagnostics only. Enforced by test |
| F-7 | Charting | Medium | "Plotly/ECharts" — Plotly's bundle and weak theming fight the dark-mode requirement | ECharts only, one shared light/dark theme, zero embedded numbers |
| F-8 | Vendor read/write | Medium | Rx vendors must *submit* outcomes but §5.5 forbids vendors *seeing* outcomes — undefined for the submitter | Dataset grants are directional: `write` ≠ `read`. Rx vendors get write-only |
| F-9 | Control definition | **High / methodology** | "if unavailable, use an approved target-universe rule" is a silent-degradation hatch | Control strategy is an explicit, stored, displayed field on every run. Never auto-downgraded |
| F-10 | DiD estimator | Medium | Two-way FE with staggered treatment is biased when effects are heterogeneous — the brief itself asks for heterogeneous effects | Cohort-time ATT (Callaway–Sant'Anna style) aggregation implemented alongside TWFE; TWFE kept as a diagnostic |
| F-11 | RLS + pooling | Medium | RLS via session variables breaks silently under a shared pooled connection | `SET LOCAL` inside an explicit transaction per request, non-BYPASSRLS role, adversarial test |
| F-12 | Upload limits | Low | 250 MB / 1 M rows synchronous-feeling in a demo | Kept as config ceiling; demo default 25 MB / 200 k rows; chunked streaming either way |
| F-13 | "Executive viewer" scope | Low | Read-only "published" results, but no publication scope exists on the result tables | `publication_state` + `published_at` on serving views; executives read the published projection only |
| F-14 | Money | Low | Currency named but no FX policy; multi-region tenants will mix currencies | Tenant reporting currency + effective-dated FX table; no implicit conversion |
| F-15 | Deletion | Low | "configurable retention and deletion" vs "published runs immutable" | Deletion is tombstone + crypto-shred of raw objects; published analytical rows never mutate |

---

## F-1 (Blocker) — The ML pipeline is three different things wearing one coat

### What the brief does

§12.2, §12.3 and §12.6 all sit under "Analytical methodology" and §14 lists them as peer "jobs".
That framing caused the confusion the client flagged. Concretely:

- §12.2 **propensity** is a *classifier* whose output is never a business answer. Its job is to
  make two groups comparable. The brief even says so — "it does not estimate Rx lift" — then
  §12.2 grades it with AUC language that invites people to treat it as predictive.
- §12.3 **DiD** is not machine learning at all. It is an *estimator*. It has no training set, no
  holdout, no drift, and cannot be "retrained". Putting it in a model lifecycle
  (`DRAFT -> TRAINING -> ... -> ACTIVE`) as §12.8 does is a category error.
- §12.6 **future model** is the only genuinely forward-looking model, and it gets the least text.

The client's note — *"the ml pipeline is confused in plan, so there is to predict the future mind
it"* — is correct and is the single most important correction in this document.

### Decision: four models, four contracts

| ID | Name | Kind | Trained on | Predicts | Lifecycle | Where it surfaces |
|---|---|---|---|---|---|---|
| **M1** | Attendance Propensity | Supervised binary classifier (LightGBM) | Eligible HCP×event rows, pre-event features only | P(verified attendance) | Full champion/challenger | **Nowhere user-facing at HCP grain.** Matching input + balance diagnostics |
| **M2** | Causal Effect Estimator | Statistical estimator (panel DiD + cohort-time ATT) | *Nothing* — it is fitted per event on that event's panel | Incremental NRx/TRx **for the past** + CI | **Versioned specification**, not a model lifecycle | Event Evidence, Portfolio |
| **M3** | Future Impact Forecaster | Regression + hierarchical shrinkage + conformal intervals | Approved M2 outputs (design/context → measured lift) | Incremental NRx **for a program that has not happened** + honest PI | Full champion/challenger | **Future Simulator, Budget Planner** |
| **M4** | Attendance & Reach Forecaster | Regression (LightGBM, Tweedie) | Historical event operations | Verified attendance from a proposed design | Full champion/challenger | Future Simulator (feeds M3), Budget Planner capacity |

Two structural rules follow:

1. **M2 is never called a model version.** It gets `analysis_specs.version` +
   `model_runs.spec_version`. It never enters `PENDING_APPROVAL -> ACTIVE`. Runs are immutable
   artifacts of (data version × specification × code commit).
2. **M3 is the only thing allowed to answer "what will happen".** M1 must not be exposed as a
   forward-looking score, ever (see F-6).

### M3 — the part the brief left vague, specified properly

The forward model has a hard statistical problem the brief does not name: **its labels are
estimates, not observations.** Each training row is
`(design features, x̂ = measured lift per attendee, se(x̂))` where `se` varies by two orders of
magnitude across events. Train an ordinary regressor on that and it chases the noise of small
events. And in a cold start there are no measured events at all for a new brand×topic cell.

Implementation (this is what `analytics/forecast/` builds):

```text
Stage A — Pooled prior (always available, works at n=0 for a cell)
  Empirical-Bayes hierarchical mean over nested cells:
      global -> brand -> brand x topic -> brand x topic x format -> + region
  Cell posterior:  mu_cell = (tau^-2 * mu_parent + sum(se_i^-2 * x_i)) / (tau^-2 + sum(se_i^-2))
  tau^2 estimated by method-of-moments on between-cell variance net of within-cell noise.
  This is the transparent "category average" the brief asks for as a fallback — but shrunk,
  so a cell with 2 noisy events does not out-shout a cell with 200.

Stage B — Conditional model (needs support)
  LightGBM regressor, objective=L2, sample_weight = 1 / (se_i^2 + tau^2)
      => inverse-variance weighting; noisy events contribute proportionally less.
  Features: design + pre-event market context ONLY. No post-event anything. No named HCP.
  Monotone constraints where the business direction is not negotiable
      (e.g. non-decreasing in pre-period brand momentum).

Stage C — Blend by evidence, not by accuracy
  w = n_eff_cell / (n_eff_cell + k),  n_eff = sum of inverse-variance weights in the cell
  yhat = w * B(x) + (1 - w) * A(cell)
  k configurable (default 40 effective events). w is displayed to the user.

Stage D — Honest intervals (this is what makes it usable for budgeting)
  Split-conformal on a TEMPORAL holdout:
      residuals r_i = |y_i - yhat_i| on the calibration fold
      q = Quantile(r, ceil((n+1)(1-alpha))/n)
      PI = yhat +- q, widened by sqrt(1 + se_new^2/var(r)) for label noise
  Reported coverage is measured, not assumed. If measured coverage < nominal - 5pp,
  the model cannot be promoted to champion.

Gate — Out-of-support refusal
  A design is out of support if: cell n_eff < min_support (default 5), or any numeric feature
  outside the 1st-99th training percentile, or a categorical level unseen in training.
  Response is an explicit OUT_OF_SUPPORT payload with the offending features named.
  It is never a silent point estimate.
```

Acceptance for M3 (measured, in `tests/model_validation/`):
`MAE ≤ 0.90 × MAE(category-average baseline)` on temporal holdout, PI coverage within
±5 pp of nominal, no leakage feature present, and grouped-by-event splits verified.

### The cold-start answer the brief owed us

§12.6 says fall back below "100–200 measured supported events" — but §11's own generator was
inconsistent about how many events exist (F-2). With the resolved generator there are ~5,200
historical events, so M3 trains properly in the demo. In a **real** tenant on day one there are
zero. The product therefore ships a three-state forecast, visible in the UI:

| State | Condition | UI |
|---|---|---|
| `MODEL` | cell `n_eff ≥ 40` and global model promoted | Point + conformal PI, "model" badge |
| `POOLED` | `min_support ≤ n_eff < 40` | Point + wider pooled interval, "limited history" badge, w shown |
| `OUT_OF_SUPPORT` | `n_eff < min_support` or feature out of range | **No number.** Named reason + what data would fix it |

The Budget Planner consumes only `MODEL` and `POOLED`, applies the risk penalty to the *lower*
interval bound, and refuses to allocate to `OUT_OF_SUPPORT` candidates unless the user explicitly
funds them from a separate, capped "exploration" budget line (the brief's §7.5 exploration
allocation — now given a real mechanism).

---

## F-2 (Blocker) — §11's numbers cannot all be true

Lines in conflict:

| Source | Claim |
|---|---|
| §11 table | Historical completed events: **5,000** |
| §11 bullets | "Multiple campaigns, **250-300 historical events**" |
| §11 table | Verified attendance rows: **5,000** |
| §11 table | Invitations: **50,000** |

5,000 events × 5,000 attendance rows ⇒ **one attendee per event**, which makes per-event causal
estimation impossible by construction (§12.3 needs a treated cohort per event). 50,000 invitations
across 5,000 events ⇒ 10 invitees per event, so a 1:2 matched design cannot be built either.

The two numbers are answering different questions: 250–300 is a *demo browsing* volume, 5,000 is a
*model training* volume. Both are legitimate. The generator must satisfy the larger.

### Decision — one generator, two profiles, self-consistent

| Quantity | `smoke` (CI) | `full` (demo + training) | Brief minimum | Met |
|---|---:|---:|---:|---|
| Tenants | 2 | 2 | 2 | ✔ |
| Brands / primary tenant | 3 | 5 | 5 | ✔ |
| HCPs per tenant | 400 | 5,200 | 5,000 | ✔ |
| Campaigns | 8 | 96 | "multiple" | ✔ |
| Events (all statuses) | 260 | **5,400** | 5,000 | ✔ |
| — completed & measurable | 180 | ~4,300 | — | ✔ |
| — cancelled / proposed | 80 | ~1,100 | present | ✔ |
| Invitations (HCP×event) | 9,600 | **~216,000** | 50,000 | ✔ |
| Verified attendance | 2,300 | **~62,000** | 5,000 | ✔ |
| HCP-product-month Rx | 38,400 | **~499,000** | 250,000 | ✔ |
| Marketing/market rows | 12,000 | **~180,000** | 50,000 | ✔ |
| Event cost rows | 1 per event | 3–6 per event | ≥1 per event | ✔ |
| Propensity train rows | 9,600 | ~216,000 | 5,000 | ✔ |
| M3 event rows | 180 | ~4,300 | 5,000 events exist ⇒ measurable subset | ✔ (see note) |
| Causal analytical rows | 2,300 treated | ~62,000 treated + ~124,000 matched control | 5,000 | ✔ |

Note on the M3 row: the brief asks for "at least 5,000 measured/synthetic historical event rows
before splitting". 5,400 events exist; ~4,300 pass evidence gates and are *measurable*. Padding
the training set with events that failed their own evidence gates would poison the target — that
is exactly the mistake §12.6 warns about. The generator therefore emits 5,400 event rows and the
trainer documents that it uses the 4,300 that have finalized causal evidence, plus the shrinkage
prior which uses all of them. **The minimum is met at generation; the filter is a methodological
requirement, not a shortfall.** This is asserted and logged, not hidden.

The `full` profile carries ~1.0 M rows total. Generation is deterministic from one seed
(`SYNTHETIC_SEED`), streams to Parquet, and re-runs identically. `scripts/seed_demo` asserts every
row above and **exits non-zero** if any minimum is missed.

Ground truth (per-event true effect, latent HCP propensity drivers) is written to
`artifacts/{tenant}/ground_truth/` and is (a) never loaded by any API router, (b) never a feature,
(c) covered by a test that greps the API package for imports of the truth module.

---

## F-3 (High) — Keycloak must not be the only door

Keycloak is the right production answer and the wrong *only* answer. It needs its own database,
a realm import, ~1 GB of RAM, and 40–90 s of first-boot time; when its import fails the entire
product is unloggable-into and a reviewer sees a broken app. The brief also requires the demo to
work offline and warns "never write a bespoke production password system" — correct advice that
does not mean "have no local path".

### Decision — one auth interface, two real implementations

```text
AuthProvider (interface)
├── LocalAuthProvider     AUTH_PROVIDER=local  (default in compose)
│     invite-only, Argon2id (m=64MiB,t=3,p=4), no self-signup,
│     httpOnly+SameSite=Lax+Secure session cookies, server-side session store in
│     Postgres with rotation on privilege change, absolute + idle expiry,
│     optional TOTP MFA, lockout with backoff, forced re-auth for publish/suspend
└── OidcAuthProvider      AUTH_PROVIDER=oidc   (compose profile `oidc`)
      Authorization Code + PKCE, state/nonce, JWKS cache, discovery document,
      refresh rotation, subject→users/memberships sync, Keycloak realm shipped,
      Entra ID documented (same code path, different discovery URL + claim map)
```

Both are fully implemented and tested. Roles, tenant scopes, brand scopes and vendor scopes are
**always** resolved from the application database — never from a token claim and never from a form
field — so the two providers are interchangeable and the authorization tests are provider-agnostic.
Production guidance in `docs/runbook.md`: run `oidc`. Demo default: `local`, so a reviewer with
Docker and no internet is logged in ~15 s after `docker compose up`.

---

## F-6 (High, compliance) — the propensity score is a targeting list in disguise

§3 forbids "selecting paid speakers or invitees based on actual or predicted prescribing" and
§15 forbids "named-HCP prescribing rankings". But §9.5 stores `propensity_scores` at
`(run, event, HCP)` grain, and §13's API list does not say it is unexposed. Any endpoint that
returns those rows — or any CSV export of them — is a ranked named-HCP list, sorted by a model
trained on prescribing features. That is the prohibited artifact, produced accidentally.

### Decision

1. `propensity_scores` and `cohort_rows` are **analytics-tier only**. No router reads them at HCP
   grain. `hcp_id` never appears in an API response body outside the Data Steward identity-
   resolution screens (which show identifiers, never scores or Rx).
2. Everything the UI needs is aggregate: overlap histograms, SMD tables, retention counts,
   funnel counts. All computed in the analytics tier and stored pre-aggregated.
3. Enforced by `tests/security/test_no_hcp_grain_leak.py`, which walks every registered route,
   calls it with a seeded steward/analyst/brand-manager token, and fails if any response contains
   an `hcp_id`/`master_hcp_id` alongside a score or Rx value.
4. AI Insights refuses HCP-targeting intents *before* retrieval, and the refusal is logged.

---

## F-9 (High, methodology) — "if unavailable, use an approved target-universe rule"

That clause lets a run silently switch from a strong design (invited non-attendees) to a weak one
(everybody who looks similar) and still print a number with the same styling. Over a portfolio that
is how a measurement product loses credibility.

### Decision

`analysis_specs.control_strategy` is a stored enum with no default fallback:

| Strategy | Meaning | Max attainable evidence grade |
|---|---|---|
| `INVITED_NON_ATTENDEE` | Invited, eligible, verified non-attendance | `STRONG` |
| `TARGET_UNIVERSE` | Approved eligibility rule + verified non-exposure | `MODERATE` |
| `SYNTHETIC_CONTROL_POOL` | Reserved, not in MVP | n/a |

Choosing `TARGET_UNIVERSE` caps the grade at `MODERATE`, requires a stored justification string,
and is rendered on Event Evidence next to the estimate. The engine never changes strategy on its
own; if the selected strategy yields too few controls the run returns
`NOT_RELIABLY_ESTIMABLE / INSUFFICIENT_CONTROLS`.

---

## F-10 (Medium, methodology) — two-way fixed effects will bias the portfolio

§12.3 prescribes "monthly panel with HCP and calendar-month effects, treatment/post interaction".
With events staggered across 24 months and effects that are heterogeneous and decaying — which
§11 explicitly generates — TWFE uses already-treated HCPs as controls for later-treated ones and
the estimate becomes a weighted average with **negative weights**. The brief half-notices this
("a future scaled implementation may replace this estimator").

### Decision

Implement both, report the correct one:

- **Primary:** cohort-time ATT. For each treatment cohort *g* (event month) and period *t*, compare
  cohort *g* against its matched not-yet-treated controls; aggregate ATT(g,t) into
  (a) an overall post-event ATT and (b) an event-study path by relative month. This is the
  Callaway–Sant'Anna aggregation, implemented directly on the matched panel.
- **Secondary / diagnostic:** the TWFE interaction model. Displayed as a robustness row.
  A large primary-vs-TWFE divergence is itself a sensitivity flag.
- Uncertainty: cluster-robust at HCP level; portfolio aggregates use a block bootstrap over events.

Both are in `analytics/causal/`, both stored in `sensitivity_results`, and the synthetic-recovery
test asserts the primary estimator recovers hidden truth within the brief's 10–15 % tolerance
(measured result reported in `docs/model_card.md`).

---

## Smaller findings, decided

**F-4** — folded into F-1 Stage B/C.

**F-5 MLflow.** `ml.model_versions` / `ml.model_runs` in Postgres are authoritative — the app reads
only those, so the product has no runtime dependency on MLflow. `MLFLOW_TRACKING_URI` is optional;
when set, training also logs params/metrics/artifacts there. Compose profile `mlflow`. Rationale:
the acceptance criteria are written against the Postgres tables, and a required MLflow service is
another way for a clean-machine boot to fail.

**F-7 Charting.** ECharts only (`echarts` + a thin React wrapper), one `chartTheme(light|dark)`
derived from the same CSS custom properties as the rest of the UI, so a theme toggle repaints
charts without a reload. Plotly dropped: ~3× bundle, and its theming would need a parallel palette.
Every chart is fed from an API payload; a lint rule bans numeric literals in chart data props.

**F-8 Vendor grants.** `vendor_assignments` carries `dataset_type` **and** `access` ∈
`{write, read, read_write}`. Rx suppliers get `write`. A vendor's read of anything outside its own
`upload_batches` is denied at the repository layer and by RLS policy, and tested.

**F-11 RLS + pooling.** Every request opens one transaction, issues
`SELECT set_config('app.tenant_id', $1, true)` (`true` = transaction-local), and closes it. The
app connects as `app_rw` which owns no tables and lacks `BYPASSRLS`; migrations run as `app_migrator`.
Read-only AI/semantic queries use `app_ro` with `statement_timeout=5s` and a row cap.
`tests/security/test_rls.py` asserts cross-tenant UUID guessing returns zero rows *at the SQL
layer*, not just 403 at the API layer, and that a leaked connection cannot see anything without
tenant context set.

**F-12 Upload limits.** `UPLOAD_MAX_BYTES=262144000` and `UPLOAD_MAX_ROWS=1000000` remain the
configured ceiling; `.env.example` ships 25 MB / 200 k for the demo. Parsing is chunked
(`pyarrow.csv` / streaming `openpyxl` read-only) regardless of size, so the limit is policy, not
an architectural assumption.

**F-13 Publication scope.** `publication_state ∈ {DRAFT, UNDER_REVIEW, APPROVED, PUBLISHED,
SUPERSEDED}` on `effect_estimates` and `roi_results`; Executive Viewer resolves through
`analytics.v_published_*` views only, so an unpublished correction can never appear on an
executive screen.

**F-14 Currency.** `tenants.reporting_currency` + `core.fx_rates(from, to, rate, effective_from,
effective_to)`. Costs and assumptions store their native currency; conversion happens once, at
serving time, with the FX version recorded in lineage. No implicit conversion anywhere.

**F-15 Deletion.** A tenant/HCP deletion request writes a tombstone, deletes/shreds raw objects in
storage, and nulls identifying columns — while leaving published aggregate analytical rows and
audit events intact. Documented as a policy decision in `docs/threat_model.md`, since the two
requirements in §15 cannot both be satisfied literally.

---

## Things in the brief I am deliberately not changing

Worth saying explicitly, because they look like problems and are not:

- **No HCP-level ROI when linkage is unavailable** (§3). Correct, kept. The engine returns
  `NOT_RELIABLY_ESTIMABLE` rather than degrading to territory level silently; territory-level
  analysis is a separate, explicitly chosen `analysis_grain`.
- **LLM never computes** (§7.6). Kept and enforced structurally: the LLM receives a *finished*
  JSON fact payload and cannot reach the database. No text-to-SQL, not even the guarded variant
  §7.6 permits — an allowlisted function layer covers every stated question, so the SQL-generation
  attack surface buys nothing.
- **Evidence grade from hard gates, not a learned score** (§12.4). Kept exactly.
- **`NOT_RELIABLY_ESTIMABLE` instead of zero** (§12.3). Kept — this is the product's spine.
- **Object storage for blobs, never Postgres** (§23). Kept.

---

## What "done" means, restated as measurable checks

The brief's §21 is 20 prose criteria. They are re-expressed as executable checks in
`scripts/verify`; each maps to a test id so completion is a command's exit code, not an opinion.
See `docs/acceptance.md` for the criterion → test mapping.
