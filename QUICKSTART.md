# SPRIP Quick Start

Get the Speaker Program ROI Intelligence Platform running locally in under 5 minutes.

## Prerequisites

- Python 3.12+
- Node.js 20+
- All infrastructure ships embedded in `.tools/` (PostgreSQL, Redis, MinIO) — no Docker needed.

## 1. Start Infrastructure

```powershell
# PowerShell — start PostgreSQL (port 54329), Redis (63799), MinIO (9100)
python scripts/devtools/pg.py start
python scripts/devtools/services.py start
```

## 2. Install Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e ".[dev]"
```

## 3. Set Up the Database

```powershell
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://app_migrator:app_migrator_pw@127.0.0.1:54329/speaker_roi"
alembic upgrade head
```

## 4. Generate `.env`

```powershell
python scripts/devtools/pg.py env | Out-File -Encoding utf8 .env
python scripts/devtools/services.py env | Add-Content -Encoding utf8 .env

# Required for HTTP localhost — append manually:
Add-Content .env "AUTH_COOKIE_SECURE=false"
```

## 5. Bootstrap Demo Tenant

```powershell
speaker-roi admin bootstrap `
  --tenant-code demo `
  --tenant-name "Demo Pharma" `
  --email admin@demo.com `
  --display-name "Demo Admin" `
  --password "admin@123"
```

## 6. Seed Demo Data

```powershell
python scripts/seed_demo_data.py
python scripts/seed_analytics.py
```

## 7. Start the App

```powershell
# Terminal 1 — API server
uvicorn speaker_roi_api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev

# Terminal 3 — Celery worker (optional, for background analytics)
celery -A speaker_roi_worker.app worker -l info -Q analytics,ingestion,exports
```


**Login:** `admin@demo.com` / `admin@123`

MFA is disabled for the demo tenant. You go straight to the dashboard after login.

## What You Can Do

### Dashboard
Overview cards showing total events, HCPs, campaigns, and ROI metrics.

### HCPs
Browse 2,500 healthcare professionals. Click any row to see their profile, Rx history chart, and event attendance.

### Events
List of 300 speaker events across brands. Filter by brand using the dropdown. Click an event for details.

### Campaigns
Campaign management with linked events and budget tracking.

### Analytics Dashboard
Charts showing ROI trends, campaign performance, HCP engagement, and event impact scatter plots. Filter by brand.

### ROI Results
Computed ROI at event, brand, and campaign levels. Filter by brand and aggregation level.

### Forecasts
Predicted impact for upcoming events based on ML model M3.

### Import
Upload CSV files (Rx data, attendance, events) via the file upload interface. Files are validated, stored in MinIO, and processed by the Celery worker.

### Data Steward
Review upload sessions, validation issues, and data quality metrics.

## Architecture at a Glance

```
Frontend (React 19 + Vite + Tailwind v4 + recharts)
    ↓ REST
API Server (FastAPI + async SQLAlchemy + Pydantic v2)
    ↓ SQL (RLS-enforced)
PostgreSQL 16 (6 schemas, 76 models, 69 RLS policies)
    ↑
Celery Worker → Redis broker → MinIO (file storage)
```

## Stopping Everything

```powershell
python scripts/devtools/services.py stop   # Redis + MinIO
python scripts/devtools/pg.py stop         # PostgreSQL
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| All pages show loading spinners | Ensure `.env` has `AUTH_COOKIE_SECURE=false` and restart the API |
| Port 8000 already in use | `taskkill /F /IM python3.12.exe` then restart |
| Login fails | Verify password is `admin@123` — the `@` matters |
| Celery tasks not running | Check Redis is up: `redis-cli -p 63799 ping` |
| File upload fails | Check MinIO is up and buckets exist: `python scripts/devtools/services.py start` |
