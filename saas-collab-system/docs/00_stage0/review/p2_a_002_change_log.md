# P2-A-002 Change Log

## Scope

- Added tenant-scoped sync job, sync run, sync cursor, and webhook event models.
- Added platform adapter protocol with mock, sandbox placeholder, and disabled production adapters.
- Added sync service helpers for idempotency, cursor paging, finite retry records, backoff calculation, masked logs, and mock webhook event de-duplication.
- Added internal sync job and sync run APIs.

## Interfaces

- `GET /api/internal/integrations/sync-jobs/`
- `POST /api/internal/integrations/sync-jobs/`
- `GET /api/internal/integrations/sync-runs/`
- `GET /api/internal/integrations/sync-runs/{id}/`
- `POST /api/internal/integrations/sync-jobs/{id}/run-mock/`
- `POST /api/internal/integrations/sync-jobs/{id}/disable/`

## Boundaries

- Only `MockPlatformAdapter` can be executed through `run-mock`.
- `SandboxPlaceholderAdapter` is present as a no-real-platform placeholder.
- `DisabledProductionAdapter` rejects execution.
- No real platform HTTP request, SDK, webhook secret, credential, order, or finance data was added.
- Logs use sanitized payloads and do not print credentials or full payloads.

## Verification

- `python manage.py check`: passed, 0 issues.
- `pytest tests/test_phase2_sync_framework.py tests/test_phase2_integrations_secure_config.py tests/test_integrations_models_celery.py`: passed, 20 tests.
- Full backend `pytest`: passed, 96 tests.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
