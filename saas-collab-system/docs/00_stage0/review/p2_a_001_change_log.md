# P2-A-001 Change Log

## New Models

- Added `PlatformIntegrationConfig` for tenant-scoped platform configuration metadata.
- Added `IntegrationAuditLog` for masked audit records of create, update, rotate, disable, and blocked verify actions.
- Existing Stage 0 `APIIntegrationConfig` remains available and now includes credential custody metadata.

## New Interfaces

- `GET /api/internal/integrations/configs/`
- `POST /api/internal/integrations/configs/`
- `GET /api/internal/integrations/configs/{id}/`
- `PATCH /api/internal/integrations/configs/{id}/`
- `POST /api/internal/integrations/configs/{id}/rotate/`
- `POST /api/internal/integrations/configs/{id}/disable/`
- `POST /api/internal/integrations/configs/{id}/verify/` is a mock-only guard endpoint and blocks production verification.

## Permission Boundary

- Added `IsIntegrationAdmin`, backed by integration permission codes or technical/admin roles.
- External users, supplier users, RPA users, unauthenticated users, and ordinary internal users are rejected.
- All config queries are filtered by tenant.

## Encryption Abstraction

- Added replaceable encryption provider interface.
- Test/local provider is explicitly named `test-only`.
- Production provider remains unconfigured and refuses execution.
- API responses do not include `credential_ciphertext`.
- Audit logs store masked detail only.

## Verification

- `python manage.py check`: passed, 0 issues.
- `pytest tests/test_phase2_integrations_secure_config.py tests/test_integrations_models_celery.py`: passed, 12 tests.
- Full backend `pytest`: passed, 88 tests.

## Safety Notes

- No real BigSeller, Shopee, TikTok, bank, payment, or other production platform connection was added.
- No real credentials were written. Tests use only `not-a-real-secret`, `demo`, and `placeholder` values.
