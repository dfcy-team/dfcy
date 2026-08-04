# A-PR2 R2 P1 remediation change log

## Scope

This change log records the second-round remediation for `a_pr2_arch_security_r2_review.md`.
The implementation remains synthetic/mock only. No real Shopee, TikTok Shop, Sandbox, banking,
credential custody, or production network request was enabled.

Base before this remediation: `724e51458e7f373f4a8764716627ade47c062f95`.
Branch: `feature/module-a-platform-oauth-callback`.
PR #40 remains Draft and is not merged.

## P1-001: raw state lifecycle

- Removed the process-global raw state vault from the OAuth service.
- Only the SHA-256 state hash is persisted. The raw state is returned inside the server-generated
  synthetic authorization URL and is consumed from the callback request; it is not stored in
  action responses, callback records, logs, or audit data.
- Added `expire_oauth_attempts()` and the `expire_marketplace_oauth_attempts` management command.
  Callback processing performs bounded proactive expiration cleanup while excluding the current
  state so the callback retains the contract-defined expired response.
- The callback remains one-time and atomic through the row lock and `consumed_at` transition.

## P1-002: tenant and binding consistency

- `MarketplaceOAuthAction` and `MarketplaceOAuthOperation` now validate tenant consistency for
  the internal user, attempt, and authorization at the model boundary.
- The existing cross-tenant/store/platform checks remain in the service and scoped query paths.
- Existing expired callback and cross-tenant replay tests continue to pass.

## P1-003: durable callback handoff and recovery

- Callback creates the durable exchange operation before consuming the callback state.
- After atomic state consumption, the operation is advanced to `callback_received` before adapter
  validation and custody exchange.
- Added `recover_marketplace_oauth_operation <operation_id_hash>` as an explicit recovery entry
  point. An interrupted exchange is moved to `reconcile_required` with a stable error code; a
  refresh or revoke operation can resume through the service layer with the durable operation key.
- Callback failures update the operation and attempt with sanitized stable error codes only.

## P1-004: action idempotency and ownership

- Action fingerprints now include HTTP method, request path, action, object type, object ID, and
  normalized request body.
- The database uniqueness scope includes object type and object ID, and a reused key across
  resources is rejected with `409 STATE_CONFLICT`.
- Added durable `running`, `execution_owner`, and `lease_expires_at` fields. Mutating refresh,
  revoke, and retry actions claim a row lease; other workers wait for the durable terminal result
  rather than executing the same action concurrently.
- Removed the synthetic custody gateway process-local result cache. Synthetic results are
  deterministic from the durable operation/authorization identifiers, so restart or multiworker
  behavior does not depend on process memory.

## P1-005: exact frontend action permissions

- Added `GET /api/internal/integrations/store-authorizations/oauth/targets/?action=...`.
- The target endpoint maps each action to its exact permission and server-side data scope:
  `authorize`, `refresh`, `revoke`, and `retry`.
- `MarketplaceOAuth.vue` loads only targets for permissions held by the current user. It no longer
  requires a broad integrations view permission for the OAuth action page, and it does not persist
  authorization URL, state, callback query, code, token, or credential material.
- Added real Vue Test Utils mount coverage for authorize-only and rotate-only users.

## P1-006: production synthetic gate

- The synthetic gate now runs at every mutating public, internal, and service-layer OAuth boundary:
  initiate, callback, refresh, revoke, retry, exchange, refresh service, revoke service, operation
  creation, and recovery.
- With synthetic disabled, requests return `503 OAUTH_SYNTHETIC_DISABLED` before creating actions,
  operations, audit success records, or authorization/reference changes.
- Real network access remains disabled; production configurations cannot enable synthetic OAuth by
  changing only the network setting.

## Files changed by this remediation

- `backend/apps/integrations/models.py`
- `backend/apps/integrations/oauth_adapters.py`
- `backend/apps/integrations/oauth_services.py`
- `backend/apps/integrations/urls_internal.py`
- `backend/apps/integrations/views.py`
- `backend/apps/integrations/migrations/0012_remove_marketplaceoauthaction_uniq_oauth_action_scope_key_and_more.py`
- `backend/apps/integrations/management/commands/expire_marketplace_oauth_attempts.py`
- `backend/apps/integrations/management/commands/recover_marketplace_oauth_operation.py`
- `backend/tests/test_shopee_tiktok_auth_foundation.py`
- `frontend/src/api/integrations.js`
- `frontend/src/mock/integrations.js`
- `frontend/src/router/menu.js`
- `frontend/src/views/integrations/MarketplaceOAuth.vue`
- `frontend/tests/oauth-marketplace-mount.spec.js`

## Verification

| Check | Result |
|---|---|
| Django check | PASS |
| `makemigrations --check --dry-run` | PASS; no changes detected |
| A2 targeted pytest | PASS; 39 passed, 1 skipped |
| Backend full pytest | PASS; 449 passed, 1 skipped locally |
| Frontend `npm ci` | PASS; existing deprecation notices only |
| Frontend Vitest | PASS; 166 passed |
| Frontend production build | PASS; 1957 modules |
| Build warning | Non-blocking existing `@vueuse/core` PURE annotation warnings |
| Local Sandbox integration | PASS; MySQL 8.4 path, backend 450 passed, frontend 166 passed, build passed |
| CI guard | PASS; no forbidden files or high-confidence credential patterns |
| OAuth path boundary scan | PASS; no finance, Agent RPA, or `/admin/` path in the OAuth frontend |
| Runtime artifact scan | PASS; no tracked dist, node_modules, cache, downloads, pyc, or `.env` runtime artifact |
| npm audit | Existing issue remains: postcss reports high severity; no automatic dependency upgrade made |

## Security and status

- No real account, password, token, cookie, session, API key, API secret, callback code, screenshot,
  business data, supplier data, order data, finance data, or bank data was added.
- No real platform request, RPA execution, payment, transfer, withdrawal, purchase, repricing,
  clearance, stop-sale, archive, or inventory operation was enabled.
- OAuth capabilities remain `mock`/`pending`; none is marked `connected`.
- An independent R3 architecture/security review is still required. PR #40 must remain Draft until
  that review and the repository CI result are complete.
