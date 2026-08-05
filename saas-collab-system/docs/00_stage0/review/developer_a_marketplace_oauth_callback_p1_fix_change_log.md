# A-PR2-P1-FIX change log

## Scope

- Branch: `feature/module-a-platform-oauth-callback`
- Parent implementation commit: `e903cf6`
- Review source: `a_pr2_arch_security_r1_review.md`
- Real Shopee/TikTok Shop network calls remain disabled. Synthetic mode is the only executable mode in development.
- PR #40 remains Draft and must not be merged before independent R2 review.

## P1 closure mapping

### A-PR2-R1-P1-001: idempotency scope and raw state

- Added durable `MarketplaceOAuthAction` with tenant, internal user, action, session hash, request fingerprint and unique idempotency scope.
- Initiate idempotency now scopes the key by tenant, user and action; a different user cannot receive another user's attempt or authorization URL.
- Removed raw authorization URL from Django cache and database action results.
- Added a process-local synthetic secret vault containing only the transient state needed to rebuild a URL for an immediate same-process replay. It has the same five-minute expiry and is never enabled as a production OAuth path.
- Durable action response data contains no `authorization_url`, state, code or credential fields.

### A-PR2-R1-P1-002: expired callback rollback

- Callback consumption now persists `expired` and `consumed_at` under the row lock without raising inside the transaction.
- A second callback receives the consumed-state error instead of re-entering the expired path.
- Added regression coverage for persisted expiry and audit behavior.

### A-PR2-R1-P1-003: saga and recovery state

- Added durable `MarketplaceOAuthOperation` ledger with hashed operation ID, phase, status, safe metadata and error code.
- Synthetic custody operations are idempotent by operation ID and expose compensation hooks for exchange and refresh.
- Revoke now blocks local use with `revoking` before custody revoke. External failure or local completion failure moves the authorization and operation to `reconcile_required`.
- Added compensation/reconciliation paths for exchange and refresh local failures.
- Added explicit authorization status transitions for `revoking` and `reconcile_required`.

### A-PR2-R1-P1-004: durable action idempotency and failure audit

- Refresh, revoke and retry now use durable action records and operation IDs instead of five-minute cache entries.
- Same action key and fingerprint replays the stored safe result; a different fingerprint returns a stable conflict.
- Action and operation records retain only safe response fields, hashes, stable error codes and operation phases.
- Custody failures and local failures update the durable action/operation state and append a failure audit record.

### A-PR2-R1-P1-005: frontend permission and state matrix

- OAuth route/menu access accepts any of the four exact action permissions; each action button checks its own exact permission and backend authorization remains authoritative.
- Authorization targets are selected from a server-scoped list; the page no longer asks users to type an arbitrary authorization ID.
- Added polling for initiated/callback-received/pending attempts, terminal status handling, callback error-code consumption, loading/error/empty/offline states and stable API error formatting.
- Added frontend OAuth contract tests for permission boundaries, URL handling, forbidden paths and state/error UI.

## Files

- Backend models, migration, OAuth service, synthetic custody adapter, authorization state machine and tests.
- Frontend integration API/mock, OAuth page, route/menu capability contract and OAuth frontend tests.
- This change log.

## Validation

- `manage.py check`: PASS.
- `makemigrations --check --dry-run`: PASS.
- A2 backend targeted tests: `36 passed, 1 skipped`.
- Backend full pytest: `446 passed, 1 skipped`.
- Frontend tests: `164 passed`.
- Frontend build: PASS; 1957 modules, no chunk-size warning. Existing third-party `@vueuse/core` PURE-comment notices remain non-blocking.
- Local Docker Desktop Linux engine recovery: PASS. The failed backend left the Docker WSL runtime without `dockerd`, `containerd` or the Docker socket; a targeted `docker-desktop` runtime restart and clean Docker Desktop restart restored the engine without resetting Docker data. Verified server `29.5.3`, Linux/amd64.
- `sandbox.ps1 verify integration`: PASS against local MySQL 8.4. Backend `447 passed`, Phase 3 data quality checks passed, frontend `164 passed`, production build passed with 1957 modules, and the script emitted `LOCAL_SANDBOX_VERIFY=PASS profile=integration`.
- MySQL 8.4 fresh migration: PASS on a new isolated database from all migrations through `integrations.0011`.
- MySQL 8.4 upgrade and failure rerun: PASS. An approved synthetic legacy record plus one unknown legacy record caused `integrations.0008` to fail closed; the approved record remained unchanged. After the unknown record was remediated, rerun succeeded through `integrations.0011`, the approved reference was migrated, and all legacy credential columns were removed.
- MySQL 8.4 row-lock concurrency: PASS; `test_concurrent_store_reference_rotation_serializes_on_mysql` completed as `1 passed` with no skip.
- The two isolated migration probe databases were removed after verification. No Docker image, volume or Local Sandbox business database was reset or removed.

## Security boundary

- No real platform endpoint, account, password, token, cookie, session, API key or secret was added.
- No raw callback query, authorization code or credential material is stored in the business database, logs, audit details, frontend storage or action response data.
- Production explicitly disables both marketplace OAuth network calls and synthetic OAuth execution.
- No order, inventory, purchasing, payment, refund, RPA or webhook side effect was introduced.

## R2 gate

The fixed HEAD requires independent `A-PR2-ARCH-SEC-R2` review. PR #40 remains Draft and no Sandbox/Production or `connected` status is authorized by this change.
