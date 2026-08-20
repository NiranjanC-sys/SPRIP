# Speaker Program ROI Intelligence Platform

A **multi-tenant, enterprise SaaS platform** that measures the causal commercial impact of pharmaceutical speaker programs, grades the evidence behind every number, converts credible impact into ROI, and forecasts the impact of programs that have not happened yet.

Built for pharma companies to manage Healthcare Professional (HCP) speaker programs end-to-end: from event planning and campaign execution through financial modelling to causal analytics and ROI reporting — all under strict multi-tenant isolation, RBAC, MFA enforcement, and a seven-year append-only audit trail.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Key Features](#key-features)
- [Security Model](#security-model)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Testing](#testing)
- [Configuration Reference](#configuration-reference)
- [CLI Reference](#cli-reference)
- [Development](#development)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Frontend          Next.js 15 · React 19 · TypeScript · Tailwind v4    │
│                    Radix UI · ECharts · Dark/Light theme               │
├──────────────────────────────────────────────────────────────────────────┤
│  API Server        FastAPI · Pydantic v2 · async SQLAlchemy 2.0        │
│                    TOTP MFA · Argon2 · Session Cookies · RBAC          │
│  Background Worker Celery · Redis broker (analysis, ingestion, training)│
├──────────────────────────────────────────────────────────────────────────┤
│  Domain Core       ORM models (76) · Enums (54) · Config · Errors      │
│                    Tenant isolation · DB session management             │
│  Analytics Engine  Causal estimators · Forecasters · Optimizer          │
│                    Synthetic data factory · Model registry              │
├──────────────────────────────────────────────────────────────────────────┤
│  PostgreSQL 16     Row-Level Security · 69 RLS policies · 6 schemas    │
│  Redis 7           Rate limiting · Celery broker · Cache               │
│  MinIO (S3)        Upload/export/artifact buckets · Presigned URLs     │
└──────────────────────────────────────────────────────────────────────────┘
```

### How It Works

1. **Multi-tenant isolation** — Every business table carries `tenant_id`. PostgreSQL Row-Level Security policies enforce isolation at the database level. The application role (`app_rw`) does **not** hold `BYPASSRLS`, so no application-level bug can produce a cross-tenant read.

2. **Transaction-local GUCs** — `session_scope()` binds `app.tenant_id` via `set_config(..., true)` at the start of each transaction. Every RLS policy reads this GUC. When the transaction ends, the GUC disappears automatically.

3. **Identity GUC for login** — During authentication (before a tenant is known), `app.identity_user_id` is bound so the user can read their own memberships across tenants without a tenant context.

4. **Audit trail** — Every state-changing action writes an append-only `audit.audit_events` row within the same transaction. The audit insert uses a savepoint so a failure doesn't poison the business transaction. Critical actions (permission denials, publication) make audit failure fatal.

5. **Optimistic concurrency** — All updates carry a `row_version` column. PATCH endpoints require the current version; a stale version returns `412 Precondition Failed` instead of silently overwriting.

---

## Tech Stack

| Layer | Technology | Version |
| --- | --- | --- |
| **Language** | Python | 3.11+ |
| **API Framework** | FastAPI | 0.115+ |
| **Validation** | Pydantic v2 | 2.x |
| **ORM** | SQLAlchemy (async) | 2.0 |
| **Migrations** | Alembic | 1.14+ |
| **Database** | PostgreSQL (with RLS) | 16+ |
| **Password Hashing** | Argon2 (argon2-cffi) | — |
| **MFA** | TOTP via pyotp | — |
| **Cache / Queue** | Redis | 7+ |
| **Object Storage** | S3-compatible (MinIO for dev) | — |
| **Background Jobs** | Celery | 5.x |
| **Analytics** | scikit-learn, LightGBM, statsmodels, scipy | — |
| **Frontend** | Next.js 15, React 19, TypeScript | — |
| **UI Components** | Radix UI, Tailwind CSS v4 | — |
| **Charts** | ECharts | — |
| **Observability** | structlog, Prometheus, OpenTelemetry | — |
| **Linting** | Ruff | — |
| **Testing** | pytest, pytest-asyncio, httpx (ASGI transport) | — |

---

## Key Features

### Authentication & Session Management
- **Email + password login** with Argon2 hashing and transparent cost upgrade
- **TOTP-based MFA** with enrolment flow, recovery codes, and per-role enforcement
- **Session cookies** (`sr_session`) — HttpOnly, Secure, SameSite=Lax, scoped to API prefix
- **Constant-time login** — unknown emails still run the hash to prevent timing-based enumeration
- **Account lockout** (per-account) + **rate limiting** (per-identifier and per-IP)
- **Session management** — list active sessions, revoke individual sessions, re-authentication for sensitive operations
- **Tenant switching** — users with multiple memberships can switch active tenant mid-session

### Role-Based Access Control (RBAC)
- **9 roles**: `PLATFORM_ADMIN`, `PHARMA_ADMIN`, `VENDOR_CONTRIBUTOR`, `DATA_STEWARD`, `ANALYTICS_LEAD`, `FINANCE_REVIEWER`, `COMPLIANCE_REVIEWER`, `BRAND_MANAGER`, `EXECUTIVE_VIEWER`
- **41 granular permissions** covering brands, campaigns, events, HCPs, Rx data, uploads, analysis, finance, forecasting, scenarios, and platform administration
- Permissions are computed from role membership at session creation and cached in the principal
- Vendor contributors are scoped to a specific vendor and cannot see other vendors' data

### Master Data Management
- **Brands & Products** — CRUD with optimistic locking, deactivation cascades (retiring a brand retires its products)
- **HCPs** — Healthcare Professional registry with speciality, tier, and active/inactive lifecycle
- **Vendors** — Vendor management with status transitions and data access grants
- **Taxonomy** — Configurable classification values (therapeutic areas, specialties, etc.)

### Campaign & Event Tracking
- **Campaigns** — planning, budgeting, and status lifecycle (draft → active → completed → cancelled)
- **Events** — event creation with brand association, date/venue, speaker assignment, and attendance tracking
- **Speaker management** — add/remove speakers to events, track honoraria and roles

### Financial Modelling
- **Event costs** — per-event cost tracking (venue, travel, honoraria, materials)
- **Finance assumptions** — configurable assumptions per brand for ROI calculations
- **ROI results** — computed ROI with evidence grades and confidence intervals

### Analytics & Forecasting
- **Analysis runs** — trigger causal analysis jobs with configurable parameters
- **Event impact** — causal estimates of commercial impact per event
- **Forecasting** — predict future impact of planned programs
- **Scenario planning** — create and compare what-if scenarios
- **Optimizer** — suggest optimal speaker/event allocations given budget constraints

### Data Ingestion
- **Upload sessions** — track multi-file upload batches with validation
- **Validation issues** — surface data quality issues before commit
- **Data versions** — publish validated datasets as immutable snapshots

### Audit & Compliance
- **Append-only audit trail** — every state change recorded with actor, before/after state, correlation ID
- **Partitioned by month** — for retention management (7-year default)
- **No patient-level data** — by design, the system never ingests patient names, phone numbers, or ABHA identifiers
- **Vendor isolation** — vendors cannot see Rx outcomes, ROI, or other vendors' submissions

### API Design
- **Keyset pagination** — no `OFFSET`, stable cursors, no duplicate/missing rows
- **Error envelope** — structured `{"error": {"code", "message", "remediation", "correlation_id", "fields", "context", "retryable"}}`
- **Strict input validation** — Pydantic `extra="forbid"` rejects unknown fields (422, not silent ignore)
- **Version tokens** — optimistic concurrency on all mutable resources
- **Idempotency** — POST endpoints accept idempotency keys

---

## Security Model

### Multi-Tenant Isolation (RLS)

Every business table carries `tenant_id`. PostgreSQL Row-Level Security policies enforce isolation:

```sql
-- Standard tenant isolation policy (69 tables)
CREATE POLICY tenant_isolation ON core.brands
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

The application role (`app_rw`) does **not** hold `BYPASSRLS`. Even if the application code has a bug that fails to filter by tenant, the database will enforce isolation.

Special policies:
- **`auth.memberships`** — split into `identity_read` (SELECT, matches by user_id OR tenant_id for login-time reads) and strict write policies (INSERT/UPDATE/DELETE require exact tenant match)
- **`audit.audit_events`** — `tenant_write` allows `tenant_id IS NULL` for platform-scope audit events

### Authentication

| Feature | Implementation |
| --- | --- |
| Password hashing | Argon2id (time=3, memory=64MB, parallelism=4) |
| Timing safety | Unknown emails still execute hash comparison |
| MFA | TOTP (RFC 6238) with encrypted secret storage |
| MFA enforcement | `PLATFORM_ADMIN` and `PHARMA_ADMIN` must complete MFA on every session |
| Session storage | Database-backed, absolute + idle timeout |
| Cookie attributes | HttpOnly, Secure, SameSite=Lax, Path=/api/v1 |
| Account lockout | 5 failures → 15-minute lockout (configurable) |
| Rate limiting | Per-identifier and per-IP sliding windows via Redis |

### Input Validation & Output Safety

- Pydantic `extra="forbid"` — unknown request fields return 422
- CSV formula injection prevention — values starting with `=`, `+`, `-`, `@` are neutralized
- File upload validation — rejects macros and executables
- No raw SQL in any user-facing path — all queries use the ORM or parameterized `text()`

### Compliance Boundaries (plan.md §15)

- No patient names, phone numbers, addresses, or ABHA identifiers ever enter the system
- No named-HCP prescribing rankings for speaker/attendee selection
- Vendors cannot see prescription outcomes, ROI, or other vendors' data
- Tenant/role scope is never accepted from browser form data as proof of authorization
- Secrets stay in environment/secret storage; never committed to code

---

## Project Structure

```
speaker-roi/
├── packages/
│   └── core/                      # Shared domain library
│       └── src/speaker_roi_core/
│           ├── config.py           # Pydantic-based settings (8 groups)
│           ├── context.py          # Request context (tenant, principal, correlation)
│           ├── enums.py            # 54 enums (roles, actions, statuses, ...)
│           ├── errors.py           # Error taxonomy (40+ typed exceptions)
│           ├── logging.py          # structlog configuration
│           ├── storage.py          # S3/MinIO abstraction
│           ├── db/
│           │   ├── base.py         # SQLAlchemy declarative base + mixins
│           │   ├── ddl.py          # RLS policy generation
│           │   └── session.py      # session_scope(), bind_tenant(), error translation
│           └── models/             # 76 ORM models across 6 modules
│               ├── auth.py         # User, Membership, Session, ApiKey, ...
│               ├── core.py         # Tenant, Brand, Product, Hcp, Event, Campaign, ...
│               ├── analytics.py    # AnalysisRun, EventImpact, Forecast, Scenario, ...
│               ├── audit.py        # AuditEvent, ErasureRequest, ExportLog, ...
│               ├── ingestion.py    # UploadSession, DataVersion, ValidationIssue, ...
│               └── ml.py           # ModelSpec, ModelVersion, FeatureStore, ...
│
├── apps/
│   ├── api/                       # FastAPI application
│   │   └── src/speaker_roi_api/
│   │       ├── main.py             # Application factory + middleware stack
│   │       ├── deps.py             # FastAPI dependencies (auth, DB sessions, pagination)
│   │       ├── routers/            # 12 router modules, 80+ endpoints
│   │       │   ├── auth.py         # Login, MFA, sessions, password management
│   │       │   ├── master_data.py  # Brands, products, vendors, taxonomy
│   │       │   ├── hcps.py         # HCP registry
│   │       │   ├── campaigns.py    # Campaign lifecycle
│   │       │   ├── events.py       # Events + speaker assignment
│   │       │   ├── finance.py      # Costs, assumptions, ROI results
│   │       │   ├── analyses.py     # Analysis runs, impacts, forecasts, scenarios
│   │       │   ├── ingestion.py    # Upload sessions, data versions
│   │       │   ├── audit_router.py # Audit event viewer
│   │       │   ├── tenants.py      # Platform admin: tenant management
│   │       │   └── users.py        # User management within tenant
│   │       ├── schemas/            # Pydantic request/response models
│   │       ├── services/           # Business logic (auth, crud, audit, bootstrap)
│   │       ├── security/           # RBAC, MFA, password hashing, tokens
│   │       └── middleware/         # Context, observability, rate limiting, security headers
│   │
│   ├── web/                       # Next.js frontend
│   │   └── src/
│   │       ├── app/                # Next.js App Router pages
│   │       ├── components/         # React components (Radix UI based)
│   │       ├── lib/                # API client, utilities
│   │       └── styles/             # Tailwind configuration
│   │
│   └── worker/                    # Celery background worker
│
├── analytics/                     # Pure-Python analytics library
│   ├── estimators/                 # Causal impact estimators
│   ├── forecasters/                # Time-series forecasting
│   ├── optimizer/                  # Budget/speaker allocation optimizer
│   └── synthetic/                  # Synthetic data factory
│
├── migrations/
│   └── versions/
│       └── 20260101_0000_0001_initial_schema.py  # 3,400-line initial schema
│
├── tests/
│   ├── unit/                      # Pure logic tests (no DB)
│   ├── integration/               # Full-stack API tests (httpx ASGI transport)
│   └── security/                  # RLS, redaction, storage isolation tests
│
├── scripts/devtools/              # Developer tooling
│   ├── pg.py                       # Embedded PostgreSQL management
│   ├── services.py                 # Redis + MinIO management
│   ├── init-db.sql                 # Docker entrypoint (roles, databases)
│   └── check_schema.py            # Schema integrity validator
│
├── compose.yaml                   # Docker Compose (PostgreSQL, Redis, MinIO)
├── Makefile                       # Development workflow targets
├── pyproject.toml                 # Python project configuration
├── .env.example                   # All settings with safe placeholders
└── plan.md                        # 25-section design brief
```

---

## Getting Started

### Prerequisites

| Tool | Version | Purpose |
| --- | --- | --- |
| Python | 3.11+ (3.12 recommended) | API server, analytics |
| PostgreSQL | 16+ | Primary data store |
| Redis | 7+ | Rate limiting, Celery broker, cache |
| MinIO | Latest | S3-compatible object storage (dev) |
| Node.js | 20+ | Frontend only |

### Option A: Docker Compose (Recommended)

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Create Python environment and install
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

pip install -U pip
pip install -e ".[dev]"

# 3. Run database migrations
# Windows PowerShell:
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi"
# macOS / Linux:
export MIGRATION_DATABASE_URL="postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi"

alembic upgrade head

# 4. Bootstrap a demo tenant
speaker-roi admin bootstrap \
  --tenant-code demo \
  --tenant-name "Demo Pharma India" \
  --email admin@demo.example \
  --display-name "Demo Admin" \
  --password "change-me-on-first-login"

# 5. Start the API server
uvicorn speaker_roi_api.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
```

### Option B: Embedded Dev Tools (No Docker)

```bash
# Start PostgreSQL embedded on port 54329
python scripts/devtools/pg.py start

# Start Redis (63799) + MinIO (9100)
python scripts/devtools/services.py start

# Then follow steps 2-5 from Option A
```

### Option C: Makefile (Windows with Git Bash or WSL)

```bash
make setup          # Create venv + install
make services       # Start PostgreSQL, Redis, MinIO
make migrate        # Run Alembic migrations
make bootstrap      # Create demo tenant + admin
make run            # Start API server on port 8000
```

### First Login Flow

`PHARMA_ADMIN` requires MFA. The first login is a three-step process:

```bash
# Step 1: Login — returns mfaRequired: true, mfaEnrolmentRequired: true
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@demo.example", "password": "change-me-on-first-login"}'

# Step 2: Start MFA enrolment — returns TOTP secret + QR URI
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/mfa/enrol

# Step 3: Confirm with a TOTP code from your authenticator app
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/mfa/enrol/confirm \
  -H "Content-Type: application/json" \
  -d '{"code": "123456"}'
# → Returns recovery codes (save them!) — session is now MFA-satisfied

# Now all endpoints are accessible:
curl -b cookies.txt http://localhost:8000/api/v1/brands
```

### Start the Frontend (Optional)

```bash
cd apps/web
npm install
npm run dev
# UI at http://localhost:3000 — expects API at http://localhost:8000
```

---

## API Reference

All endpoints are under `/api/v1`. Authentication is via the `sr_session` cookie. Health probes are at the root level without authentication.

### Health Probes (no auth)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/livez` | Process liveness (always 200 if running) |
| `GET` | `/readyz` | Readiness for traffic (checks DB + Redis) |
| `GET` | `/healthz` | Detailed health (DB connectivity, RLS status, Redis, storage) |

### Auth (`/auth`) — 14 endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| `POST` | `/auth/login` | Authenticate with email + password | None |
| `POST` | `/auth/mfa/verify` | Verify TOTP code to satisfy MFA | Pending MFA |
| `POST` | `/auth/mfa/recovery` | Use a recovery code instead of TOTP | Pending MFA |
| `POST` | `/auth/mfa/enrol` | Start MFA enrolment (get TOTP secret) | Enrolling |
| `POST` | `/auth/mfa/enrol/confirm` | Confirm enrolment with first code | Enrolling |
| `POST` | `/auth/mfa/recovery-codes` | Regenerate recovery codes | MFA satisfied |
| `POST` | `/auth/logout` | Revoke current session + clear cookie | Authenticated |
| `POST` | `/auth/switch-tenant` | Change active tenant | Authenticated |
| `POST` | `/auth/password` | Change own password | Authenticated |
| `POST` | `/auth/reauthenticate` | Re-verify for sensitive operations | Authenticated |
| `POST` | `/auth/password/reset` | Request password reset (always 202) | None |
| `POST` | `/auth/password/reset/confirm` | Complete password reset with token | None |
| `GET` | `/auth/sessions` | List user's active sessions | Authenticated |
| `DELETE` | `/auth/sessions/{id}` | Revoke a specific session | Authenticated |

### Current User (`/me`) — 2 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/me` | Signed-in user profile, memberships, permissions, active tenant |
| `POST` | `/me/acknowledge-notice` | Dismiss a notice |

### Master Data — 21 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/brands` | List brands (keyset pagination) |
| `POST` | `/brands` | Create a brand |
| `GET` | `/brands/{id}` | Get brand detail |
| `PATCH` | `/brands/{id}` | Update brand (requires `version` for optimistic lock) |
| `POST` | `/brands/{id}/deactivate` | Retire brand (cascades to products) |
| `GET` | `/products` | List products |
| `POST` | `/products` | Create a product (linked to a brand) |
| `GET` | `/products/{id}` | Get product detail |
| `PATCH` | `/products/{id}` | Update product |
| `POST` | `/products/{id}/deactivate` | Retire a product |
| `GET` | `/vendors` | List vendors |
| `POST` | `/vendors` | Create a vendor |
| `GET` | `/vendors/{id}` | Get vendor detail |
| `PATCH` | `/vendors/{id}` | Update vendor |
| `POST` | `/vendors/{id}/status` | Change vendor status |
| `POST` | `/vendors/{id}/grants` | Create a data access grant |
| `DELETE` | `/vendors/{id}/grants/{gid}` | Revoke a data grant |
| `GET` | `/taxonomy` | List taxonomy values |
| `POST` | `/taxonomy` | Create a taxonomy value |
| `PATCH` | `/taxonomy/{id}` | Update a taxonomy value |
| `POST` | `/taxonomy/{id}/deactivate` | Deactivate a taxonomy value |

### HCPs — 5 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/hcps` | List HCPs (paginated) |
| `POST` | `/hcps` | Create an HCP |
| `GET` | `/hcps/{id}` | Get HCP detail |
| `PATCH` | `/hcps/{id}` | Update an HCP |
| `POST` | `/hcps/{id}/deactivate` | Deactivate an HCP |

### Campaigns — 5 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/campaigns` | List campaigns (paginated) |
| `POST` | `/campaigns` | Create a campaign |
| `GET` | `/campaigns/{id}` | Get campaign detail |
| `PATCH` | `/campaigns/{id}` | Update a campaign |
| `POST` | `/campaigns/{id}/deactivate` | Cancel a campaign |

### Events — 8 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/events` | List events (paginated, filterable) |
| `POST` | `/events` | Create an event |
| `GET` | `/events/{id}` | Get event detail |
| `PATCH` | `/events/{id}` | Update an event |
| `POST` | `/events/{id}/deactivate` | Cancel an event |
| `GET` | `/events/{id}/speakers` | List speakers for an event |
| `POST` | `/events/{id}/speakers` | Assign a speaker to an event |
| `DELETE` | `/events/{id}/speakers/{sid}` | Remove a speaker from an event |

### Finance — 8 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/events/{id}/costs` | List costs for an event |
| `POST` | `/events/{id}/costs` | Add an event cost |
| `PATCH` | `/events/{id}/costs/{cid}` | Update an event cost |
| `GET` | `/finance/assumptions` | List finance assumptions |
| `POST` | `/finance/assumptions` | Create a finance assumption |
| `PATCH` | `/finance/assumptions/{id}` | Update a finance assumption |
| `GET` | `/roi/results` | List ROI results |
| `GET` | `/roi/results/{id}` | Get ROI result detail |

### Analytics — 10 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/analyses/runs` | List analysis runs |
| `GET` | `/analyses/runs/{id}` | Get analysis run detail |
| `POST` | `/analyses/runs` | Trigger a new analysis run |
| `GET` | `/analyses/impacts` | List event impact estimates |
| `GET` | `/analyses/impacts/{id}` | Get impact detail |
| `GET` | `/forecasts` | List forecasts |
| `GET` | `/scenarios` | List scenarios |
| `POST` | `/scenarios` | Create a what-if scenario |
| `GET` | `/scenarios/{id}` | Get scenario detail |
| `PATCH` | `/scenarios/{id}` | Update a scenario |

### Data Ingestion — 6 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/uploads/sessions` | List upload sessions |
| `GET` | `/uploads/sessions/{id}` | Get upload session detail |
| `POST` | `/uploads/sessions` | Create an upload session |
| `GET` | `/uploads/sessions/{id}/issues` | List validation issues |
| `GET` | `/data-versions` | List data versions |
| `POST` | `/data-versions/{id}/publish` | Publish a data version |

### Audit — 2 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/audit/events` | List audit events (paginated, filterable) |
| `GET` | `/audit/events/{id}` | Get audit event detail |

### Tenants (Platform Admin) — 6 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/tenants` | List all tenants |
| `GET` | `/tenants/{id}` | Get tenant detail |
| `POST` | `/tenants` | Create a new tenant |
| `PATCH` | `/tenants/{id}` | Update tenant settings |
| `POST` | `/tenants/{id}/suspend` | Suspend a tenant |
| `POST` | `/tenants/{id}/activate` | Reactivate a tenant |

### Users (Tenant-Scoped) — 5 endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/users` | List users in current tenant |
| `GET` | `/users/{id}` | Get user detail |
| `POST` | `/users/invite` | Invite a new user |
| `PATCH` | `/users/{id}/role` | Change user role |
| `POST` | `/users/{id}/deactivate` | Deactivate a user |

### Error Responses

All errors follow a consistent envelope:

```json
{
  "error": {
    "code": "PRECONDITION_FAILED",
    "message": "This record was changed by someone else since you loaded it.",
    "remediation": "Reload the record and re-apply your change.",
    "correlation_id": "abc123-...",
    "context": {"current_version": 3, "submitted_version": 1},
    "retryable": false
  }
}
```

Common error codes: `NOT_AUTHENTICATED`, `MFA_REQUIRED`, `FORBIDDEN`, `NOT_FOUND`, `PRECONDITION_FAILED`, `CONFLICT`, `RATE_LIMITED`, `TENANT_SCOPE_REQUIRED`, `VALIDATION_ERROR`, `IMMUTABLE_RESOURCE`.

---

## Database Schema

The database uses **6 schemas** with **76 tables** and **69 RLS policies**. The initial migration is a single 3,400-line file that creates everything atomically.

### Schema Organization

| Schema | Purpose | Key Tables |
| --- | --- | --- |
| **`auth`** | Identity & access | `users`, `memberships`, `sessions`, `api_keys`, `invitations`, `brand_scopes`, `vendor_scopes`, `delegated_access_grants` |
| **`core`** | Business domain | `tenants`, `brands`, `products`, `hcps`, `campaigns`, `events`, `event_speakers`, `attendance`, `event_costs`, `finance_assumptions`, `rx_panel`, `portfolio_aggregates`, `market_factors`, `taxonomy_values` |
| **`ingestion`** | Data pipeline | `dataset_contracts`, `upload_sessions`, `upload_objects`, `data_versions`, `validation_issues`, `quarantine` |
| **`analytics`** | Analysis results | `analysis_runs`, `cohorts`, `causal_estimates`, `event_impacts`, `evidence_gates`, `roi_results`, `review_comments`, `forecasts`, `scenarios`, `scenario_events`, `optimizer_runs` |
| **`ml`** | Model registry | `model_specs`, `model_versions`, `model_metrics`, `feature_store`, `conformal_calibrations`, `drift_reports`, `model_ab_tests` |
| **`audit`** | Compliance trail | `audit_events` (partitioned by year), `erasure_requests`, `export_log`, `retention_policy_runs` |

### Database Roles

| Role | Purpose | RLS |
| --- | --- | --- |
| `postgres` | Superuser (Docker init only) | Bypasses |
| `app_migrator` | Owns tables, runs DDL | Bypasses (table owner) |
| `app_rw` | Application read-write | Subject to RLS |
| `app_ro` | Read-only analytical queries | Subject to RLS |

### Row-Level Security Policies

Most tables use a standard `tenant_isolation` policy:

```sql
CREATE POLICY tenant_isolation ON <table>
    USING (tenant_id = current_setting('app.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
```

Special cases:
- **`auth.memberships`** — uses split policies: `identity_read` (SELECT, matches by tenant OR user identity), separate `tenant_insert`/`tenant_modify`/`tenant_delete` (strict tenant match)
- **`audit.audit_events`** — `tenant_write` allows `NULL` tenant_id for platform-scope events
- **Platform-scope tables** — `auth.users`, `core.tenants` use platform-aware policies

---

## Testing

### Test Categories

| Suite | Directory | DB Required | What It Tests |
| --- | --- | --- | --- |
| **Unit** | `tests/unit/` | No | Pure logic — synthetic data determinism, model utilities |
| **Integration** | `tests/integration/` | Yes | Full API stack via httpx ASGI transport — auth flow, CRUD, pagination, isolation, concurrency |
| **Security** | `tests/security/` | Yes | RLS policy correctness, PII redaction, storage isolation |

### Running Tests

```bash
# All tests (unit + integration + security)
python -m pytest tests -q

# Unit tests only (no external services needed)
python -m pytest tests/unit -q

# Integration tests (PostgreSQL must be running)
python -m pytest tests/integration -q

# Security tests (PostgreSQL must be running)
python -m pytest tests/security -q

# Single test with verbose output
python -m pytest tests/integration/test_master_data_api.py::test_brand_lifecycle -v

# With Makefile
make test              # All tests
make test-unit         # Unit only
make test-integration  # Integration only
```

### Integration Test Architecture

Integration tests use **httpx's ASGI transport** — the FastAPI app is tested in-process with no socket or port. This means:
- Tests are fast (~50s for the full suite)
- No port conflicts or race conditions
- The test database is migrated once per session and cleaned via unique tenant codes per test
- Cookie-based auth works with `AUTH_COOKIE_SECURE=false` (httpx uses `http://testserver`)
- Rate limiter state is reset between tests

### Key Integration Tests

- `test_first_login_requires_and_permits_enrolment` — full login → MFA enrol → MFA confirm → access flow
- `test_second_enrolment_attempt_needs_a_satisfied_session` — prevents MFA re-enrolment without existing factor
- `test_brand_lifecycle` — create → read → patch → deactivate with version tokens
- `test_stale_version_is_refused_with_412` — optimistic concurrency enforcement
- `test_another_tenants_brand_is_not_found` — cross-tenant isolation (404, not 403)
- `test_cursor_pages_the_whole_set_exactly_once` — keyset pagination correctness
- `test_corrupt_cursor_is_refused` — invalid cursor detection (400, not silent page-1)
- `test_retiring_a_brand_retires_its_products` — cascade correctness
- `test_product_cannot_reference_another_tenants_brand` — foreign-key isolation

---

## Configuration Reference

Settings are loaded from environment variables via Pydantic. Copy `.env.example` for a full reference. **Never commit a populated `.env` file.**

### Root Settings (no prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `local` | Environment (`local`, `staging`, `production`) |
| `DEBUG` | `false` | Debug mode |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed origins |
| `RATE_LIMIT_ENABLED` | `true` | Master switch for rate limiting |
| `API_PREFIX` | `/api/v1` | URL prefix for all API routes |

### Database (`DB_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |
| `DB_NAME` | `speaker_roi` | Database name |
| `DB_USER` | `speaker_roi_app` | Application role |
| `DB_PASSWORD` | — | Application role password |
| `DB_MIGRATION_USER` | — | Migration role (table owner) |
| `DB_POOL_SIZE` | `10` | Connection pool size |
| `DB_MAX_OVERFLOW` | `5` | Max overflow connections |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | Query timeout (ms) |
| `DB_LOCK_TIMEOUT_MS` | `5000` | Lock acquisition timeout (ms) |
| `DB_ECHO_SQL` | `false` | Log all SQL statements |

### Redis (`REDIS_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `REDIS_ENABLED` | `true` | Enable Redis (falls back to in-memory if false) |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | — | Redis password |
| `REDIS_BROKER_DB` | `0` | Celery broker database |
| `REDIS_RESULT_DB` | `1` | Celery result database |
| `REDIS_CACHE_DB` | `2` | Application cache database |
| `REDIS_USE_TLS` | `false` | Use TLS for Redis connection |

### Object Storage (`STORAGE_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `STORAGE_ENDPOINT_URL` | `http://localhost:9000` | S3/MinIO endpoint |
| `STORAGE_ACCESS_KEY` | — | S3 access key |
| `STORAGE_SECRET_KEY` | — | S3 secret key |
| `STORAGE_REGION` | `us-east-1` | S3 region |
| `STORAGE_UPLOAD_BUCKET` | `speaker-roi-uploads` | Upload bucket name |
| `STORAGE_EXPORT_BUCKET` | `speaker-roi-exports` | Export bucket name |
| `STORAGE_ARTIFACT_BUCKET` | `speaker-roi-artifacts` | Artifact bucket name |
| `STORAGE_USE_PATH_STYLE` | `true` | Use path-style access (required for MinIO) |
| `STORAGE_PRESIGN_TTL_SECONDS` | `900` | Pre-signed URL lifetime |
| `STORAGE_MAX_UPLOAD_BYTES` | `209715200` | Max upload size (200MB) |

### Authentication (`AUTH_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `AUTH_SECRET_KEY` | *(generated)* | Encryption key for TOTP secrets |
| `AUTH_SESSION_TTL_SECONDS` | `43200` | Absolute session lifetime (12h) |
| `AUTH_SESSION_IDLE_TIMEOUT_SECONDS` | `3600` | Idle timeout (1h) |
| `AUTH_COOKIE_SECURE` | `true` | Require HTTPS for cookies |
| `AUTH_COOKIE_DOMAIN` | — | Cookie domain |
| `AUTH_COOKIE_SAMESITE` | `lax` | SameSite attribute |
| `AUTH_PASSWORD_MIN_LENGTH` | `12` | Minimum password length |
| `AUTH_MAX_FAILED_LOGINS` | `5` | Failures before lockout |
| `AUTH_LOCKOUT_SECONDS` | `900` | Lockout duration (15min) |
| `AUTH_ARGON2_TIME_COST` | `3` | Argon2 time parameter |
| `AUTH_ARGON2_MEMORY_COST_KIB` | `65536` | Argon2 memory (64MB) |

### AI / Governed Narration (`AI_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `AI_ENABLED` | `false` | Enable AI-powered narration |
| `AI_PROVIDER` | `none` | Provider (`anthropic`, `azure_openai`, `none`) |
| `AI_API_KEY` | — | API key for AI provider |
| `AI_MODEL` | `claude-sonnet-4-5` | Model identifier |
| `AI_MAX_OUTPUT_TOKENS` | `1500` | Max tokens per response |
| `AI_DAILY_REQUEST_QUOTA` | `500` | Daily request cap |

### Observability (`OBS_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `OBS_LOG_LEVEL` | `INFO` | Log level |
| `OBS_LOG_FORMAT` | `console` | Log format (`json` for production) |
| `OBS_METRICS_ENABLED` | `true` | Enable Prometheus metrics |
| `OBS_TRACING_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `OBS_OTLP_ENDPOINT` | — | OTLP collector endpoint |
| `OBS_SENTRY_DSN` | — | Sentry DSN for error tracking |

### Analytics Engine (`ANALYTICS_` prefix)

| Variable | Default | Description |
| --- | --- | --- |
| `ANALYTICS_DEFAULT_PRE_WINDOW_MONTHS` | `12` | Pre-event observation window |
| `ANALYTICS_DEFAULT_POST_WINDOW_MONTHS` | `3` | Post-event observation window |
| `ANALYTICS_BOOTSTRAP_ITERATIONS` | `500` | Bootstrap iterations for CI |
| `ANALYTICS_ANALYSIS_TIMEOUT_SECONDS` | `3600` | Analysis job timeout |

---

## CLI Reference

The `speaker-roi` CLI is the operator interface:

```
speaker-roi admin bootstrap         Create tenant + first admin + taxonomy seed
speaker-roi admin reset-password    Reset a user's password and revoke sessions
speaker-roi config show             Display resolved configuration
speaker-roi config validate         Check configuration for problems
speaker-roi db migrate              Run pending Alembic migrations
speaker-roi db check-rls            Verify RLS policies match the code
speaker-roi storage check           Verify object storage connectivity
speaker-roi models train            Train/retrain ML models (M1 propensity, M2 causal, M3 forecast)
speaker-roi version                 Print the platform version
```

### Bootstrap Example

```bash
speaker-roi admin bootstrap \
  --tenant-code acme-pharma \
  --tenant-name "Acme Pharma India" \
  --email admin@acme-pharma.example \
  --display-name "Acme Admin" \
  --country IN \
  --currency INR \
  --synthetic  # seed with taxonomy data
```

---

## Development

### Makefile Targets

```bash
make help              # Show all targets
make setup             # Create venv + install dependencies
make services          # Start PostgreSQL, Redis, MinIO
make migrate           # Run Alembic migrations
make bootstrap         # Create demo tenant + admin user
make run               # Start API server (port 8000, hot reload)
make test              # Run all tests
make test-unit         # Run unit tests only
make test-integration  # Run integration tests only
make lint              # Run Ruff linter with auto-fix
make format            # Run Ruff formatter
make reset-db          # Drop + recreate databases + migrate
make train-models      # Train ML models on synthetic data
```

### Code Quality

```bash
# Lint (auto-fix enabled)
ruff check --fix .

# Format
ruff format .

# Type check (optional, uses pyright)
pyright
```

### Adding a New Endpoint

1. **Model** — Add the SQLAlchemy model in `packages/core/src/speaker_roi_core/models/`
2. **Migration** — Create an Alembic migration with RLS policy
3. **Schema** — Add Pydantic request/response schemas in `apps/api/src/speaker_roi_api/schemas/`
4. **Router** — Create the router in `apps/api/src/speaker_roi_api/routers/`
5. **Register** — Add the router to `routers/__init__.py`
6. **Permission** — Add the permission to `security/rbac.py` and the role matrix
7. **Test** — Add integration tests

### Adding a New Tenant-Owned Table

1. Add `TenantMixin` to the model class
2. The migration must include `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` and a `tenant_isolation` policy
3. Grant `SELECT, INSERT, UPDATE, DELETE` to `app_rw` and `SELECT` to `app_ro`
4. No `FORCE ROW LEVEL SECURITY` — isolation is enforced by `app_rw` not being the table owner

---

## Documentation

| Document | Status |
| --- | --- |
| [`plan.md`](plan.md) | Complete — 25-section design brief |
| [`README.md`](README.md) | Complete — this file |
| [`.env.example`](.env.example) | Complete — all settings with safe placeholders |
| [`docs/PLAN_REVIEW.md`](docs/PLAN_REVIEW.md) | Complete — design contradictions + resolutions |

---

## Security Note

`key.txt` in this working directory contains a live API token. It is listed in `.gitignore` and must never be committed, echoed, or logged. If it has been exposed, rotate it immediately.

---

## Licence

Proprietary. All rights reserved.
