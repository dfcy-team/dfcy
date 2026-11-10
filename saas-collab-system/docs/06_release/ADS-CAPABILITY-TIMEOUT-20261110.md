# TK Ads capability query hotfix

## Scope

- Reuse runtime configuration within the GET request only. PUT retains fresh validation.
- Reuse the binding evidence returned by successful mapping validation; failed validation still performs the evidence-only check for display.
- Distinguish loading, failed query and genuinely empty results. Preserve stale rows on refresh failure and disable mutations until a successful read.
- No timeout increase, authorization bypass, task creation, collection switch changes or database migration.

## Verification

- Frontend regression tests: 2 passed. Production frontend build passed.
- Tenant 1 read-only capability endpoint: 55 mappings, 51 verified, 47 read-enabled before and after.
- Observed elapsed time: 24.052s before; 11.648s with runtime scope; 8.472s after eliminating duplicate successful evidence checks.
- This is one measurement per stage, not a latency guarantee under peak load. The 10-second frontend deadline remains unchanged.

## Release and rollback

- Backend target: `/app/apps/integrations/ads_capability_api.py` in `production-backend-1`.
- Backup: `/opt/saas-collab/production/operations/ads-capability-20261110/ads_capability_api.before.py`.
- Only Gunicorn Web workers are gracefully reloaded. Celery and collection processes are not restarted.
- Frontend is published under a new content-hashed page name, preserving the main entrypoint and the existing sync-record import-map entry.
- Frontend rollback: restore `index.before.html` from the same operation directory. Original page assets remain present.
- Merge this PR after its base `fix/collection-progress-v395`; it intentionally excludes unrelated local creator/video collection changes.
