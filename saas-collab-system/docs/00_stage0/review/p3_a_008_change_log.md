# P3-A-008 Change Log

## Scope

Added Phase 3 CI and data-quality gates without changing frontend or RPA business code and without connecting any real platform.

## CI Checks

- Added `.github/workflows/phase3-ci.yml`.
- Added focused test execution for BI metrics, inventory alerts, replenishment, lifecycle, business alerts, config center, reports, finance analytics, and data quality.
- Retained Django check, migration drift detection, temporary migration, permission catalog validation, full pytest, frontend build, Docker Compose parsing, RPA JSON/document validation, and repository safety scanning.
- Frontend dependency installation uses `npm ci --ignore-scripts`; no npm lifecycle script approval is automated.

## Data Quality Checks

Added `python manage.py check_phase3_data_quality` for:

- missing tenant ownership;
- invalid metric dimensions;
- metric definition version conflicts;
- duplicate alert deduplication keys;
- expired active replenishment recommendations;
- illegal lifecycle recommendations or decisions;
- unmasked sensitive Phase 3 output;
- report exports without request audit records.

The command reports only check names, counts, and generic details. It does not print record values or suspected credentials.

## Security Boundary

- Uses only temporary SQLite and demo/placeholder values.
- Does not require or read a real `.env`.
- Does not call BigSeller, Shopee, TikTok/TK, banks, payment providers, or any production endpoint.
- Does not run RPA, generate sensitive report files, or perform purchase, product-state, or financial actions.

## Verification

- Django check: passed.
- Migration consistency: passed; no changes detected.
- Phase 3 focused pytest suites including data quality: `94 passed`.
- Full pytest: `244 passed`.
- Fresh temporary SQLite migration: passed.
- Permission catalog validation: passed.
- Persisted data-quality command on the fresh database: passed.
- Frontend locked install with lifecycle scripts disabled and production build: passed; the existing large-chunk warning remains non-blocking.
- Docker Compose placeholder configuration: passed; no services were started.
- RPA JSON parsing: passed; no RPA was executed.
- Repository credential and forbidden-file guard: passed.
- Remote GitHub Actions result is recorded after this commit is pushed.
