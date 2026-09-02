# Backend

Django REST Framework backend for the SaaS collaboration system.

## Local Python Setup

From the project root:

```powershell
cd saas-collab-system/backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python manage.py check
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Environment Variables

Copy the project-level example file and edit local values:

```powershell
cd saas-collab-system
copy .env.example .env
```

Do not commit `.env`. The example file contains placeholders only.

## Mini Program sandbox authentication

Mini Program authentication uses the dedicated `/api/miniapp/auth/*` contract.
Development defaults to a local sandbox; production forces the capability to
`disabled` until a separate WeChat credential and security review is complete.

Bind a non-RPA test user without storing the raw provider subject:

```powershell
python manage.py bind_miniapp_identity --username demo --subject device-001
```

The Mini Program can then submit `sandbox:device-001`. Internal administration
tokens and refresh tokens are rejected by the Mini Program channel.

## Release contracts

The `apps.releases` domain freezes one candidate commit, required gates,
independent approvals, one immutable artifact, optimistic versions,
idempotency digests, and immutable audit events.

Internal APIs are available under `/api/internal/releases/`. Mini Program
endpoints under `/api/miniapp/releases/` are read-only and require the
`release.contract.view` permission plus an authorized data scope. Release
actions only record controlled results; they do not call a real platform.

## Database Migrations

```powershell
cd saas-collab-system/backend
python manage.py makemigrations
python manage.py migrate
```

Migrations seed the canonical application permission catalog. Validate it in CI or after deployment with:

```powershell
python manage.py sync_permissions --check
```

To repair missing or stale permission metadata without changing role assignments:

```powershell
python manage.py sync_permissions
```

## Pytest

```powershell
cd saas-collab-system/backend
pytest
```

## Mini Program platform login

Mini Program authentication defaults to fail-closed. Local sandbox mode accepts only pre-bound test subjects. Real WeChat login requires all three server-side variables:

- `MINIAPP_AUTH_MODE=platform`
- `MINIAPP_APP_ID`
- `MINIAPP_APP_SECRET`

The Mini Program sends only the one-time `wx.login` code. The backend exchanges it through WeChat `code2Session`, hashes the returned openid for identity lookup, and discards `session_key`. AppSecret, raw openid, and `session_key` are never returned to clients or stored in the database.

Production startup rejects unsupported auth modes and rejects platform mode when either credential is missing.

## Phase 1 Test Reproducibility

For the full Phase 1 local and CI command set, see:

- `../docs/05_test/phase1_local_test_guide.md`
- `../docs/06_release/phase1_ci_checklist.md`

The guides include Windows PowerShell and bash commands for Python setup, dependency installation, Django checks, pytest, Docker Compose validation, MySQL/Redis local startup, frontend build references, RPA JSON validation, and basic security scans. Use placeholder `.env.example` values only; do not use real production `.env` files or connect to real external platforms.

## Docker Compose

From the project root:

```powershell
cd saas-collab-system
docker compose config
docker compose up -d mysql redis
docker compose ps
```

To start the backend and workers after preparing `.env`:

```powershell
docker compose up -d backend celery celery-beat
```

## MySQL

MySQL 8 is the standard database for this backend. MySQL is the final trusted business data store for tenant, account, permission, RPA task, API sync, audit, attachment, finance, and report data.

Local Docker Compose uses MySQL 8. Development variables are provided in `.env.example`:

- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_ROOT_PASSWORD`

The Django settings currently read the matching `DB_*` variables, which are also included in `.env.example`.

Production safety:

- MySQL must not be exposed to the public internet.
- Use private networking, firewall rules, and managed secrets.
- SQLite is prohibited in staging and production.
- If SQLite is ever used locally, it is only for temporary developer experiments and must not be used for staging, production, demos, shared QA, or trusted business data.

## Redis

Redis is used for Celery broker/result backend:

- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

Docker Compose keeps Redis on the internal Docker network. Production Redis must not be exposed to the public internet.

## Celery

Start a worker locally:

```powershell
cd saas-collab-system/backend
celery -A config worker -l info --pool=solo
```

Start beat locally:

```powershell
cd saas-collab-system/backend
celery -A config beat -l info
```

The `--pool=solo` option is recommended for Windows development.

## Phase 2 Mock Sync Retries

The phase 2 synchronization service is mock-only. It serializes runs per `SyncJob`, refreshes cursor and run state after a rolled-back attempt, and applies finite exponential-backoff retries.

Each run holds a renewable database lease. `SYNC_JOB_LEASE_SECONDS` defaults to 900 seconds and is clamped to 60-3600 seconds. A new run can recover an expired lease by marking the abandoned run `FAILED` with `LEASE_EXPIRED`; active leases still reject concurrent runs.

`run_sync_job()` uses a real sleep strategy by default. Tests inject a no-wait strategy so retry timing is verified without slowing the suite. Phase 2 limits the base delay to 1-5 seconds and each calculated delay to 30 seconds. A future real-platform adapter must move this boundary to Celery countdown/ETA scheduling before it can be enabled.

## Phase 3 BI Metric Aggregation

Phase 3 BI metrics are implemented in `apps.reports` as tenant-scoped metric definitions, source data points, and read-only aggregate snapshots. Aggregation only accepts quality-passed, non-missing, non-expired data from the same tenant and records definition version, source tables, source batches, calculation task references, refresh time, and quality status.

Source facts are idempotent by tenant, metric definition, source table, and stable source record ID. Re-delivery in a later batch updates the existing fact instead of double-counting it. Initial metric creation, version creation, and deactivation are service-only operations requiring `analytics.manage`, an active same-tenant internal actor, and a reason. Version creation locks the metric's version chain and leaves exactly one active latest version. Every lifecycle change writes immutable before/after evidence to `OperationLog`; model, queryset, bulk, and admin writes cannot bypass this boundary.

Aggregate JSON stores bounded source summaries and ID ranges. Complete source table, batch, and calculation-task lineage is retained in `MetricAggregateLineage`. Quality evaluation applies each definition's missing-data policy and minimum quality rate, records passed/missing/failed/expired counts, and marks incomplete results as `degraded` and non-formal unless the configured policy explicitly accepts them.

Formal aggregates are persisted only by the aggregation service. Direct model create/update and bulk writes are rejected. Aggregation captures a source ID watermark and excludes later inserts instead of locking the complete day/week/month source range.

Internal analytics endpoints:

- `GET /api/internal/analytics/metrics/`
- `GET /api/internal/analytics/metrics/{id}/`
- `GET /api/internal/analytics/aggregates/`
- `GET /api/internal/analytics/aggregates/{id}/`
- `POST /api/internal/analytics/aggregate-mock/`

Read access requires `analytics.view`; mock aggregation requires `analytics.calculate`. Aggregate queries also apply backend `DataScope` rules. The mock aggregation endpoint reads demo/test data already stored in the database and never connects to a real platform. Metrics are analysis-only and cannot trigger purchasing, product status changes, RPA execution, or financial actions.

Collection endpoints return `items` plus pagination metadata. `page_size` is limited to 100, aggregate lists accept optional `period_start` and `period_end`, and mock aggregation windows are bounded by their day/week/month granularity.
