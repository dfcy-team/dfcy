# A-PR2 R3 P1 remediation change log

## Scope

This change log records the third-round remediation for
`a_pr2_arch_security_r3_review.md` on branch
`feature/module-a-platform-oauth-callback`.

- Base before remediation: `8629bd83d3008c32bd2b041d38253325b29f21e1`.
- PR: #40 remains Draft and is not merged.
- Capability status: synthetic/mock only. Nothing is marked `connected`.
- No real Shopee, TikTok Shop, credential custody, or platform network request was enabled.

## P1 closure matrix

| Finding | Remediation | Evidence |
|---|---|---|
| A-PR2-R3-P1-001 callback ownership side effects | State, platform, session, expiry, and consumption state are validated under one row lock before the durable exchange operation and state consumption are committed together. Invalid state, platform, session, and duplicate fields do not change the attempt and do not create operations or audits. | Callback zero-side-effect matrix and cross-session recovery tests. |
| A-PR2-R3-P1-002 idempotency race and lease fencing | The database unique scope is now tenant, internal user, action, and idempotency-key hash, independent of resource. Full request/resource fingerprint validation still returns 409 on key reuse. A durable per-resource lease supplies monotonic fencing tokens; operation/action completion rejects stale owner or fence values. | MySQL concurrent cross-resource/same-resource key tests, resource serialization, lease takeover, and stale-owner rejection tests. |
| A-PR2-R3-P1-003 incomplete bindings | Action validation binds tenant, internal user, attempt owner, authorization, object target, store, config, and platform. Operation validation binds tenant and matching attempt/authorization store, config, and platform. Protected QuerySet updates and bulk updates reject immutable binding changes. | Same-tenant cross-user, object mismatch, cross-store authorization, and QuerySet bypass negative tests. |
| A-PR2-R3-P1-004 non-executable recovery | Exchange, refresh, and revoke persist safe custody references and durable phases. Recovery claims and fences the operation/resource, resumes idempotently, finalizes an already-successful operation's action, or compensates a failed exchange without reactivating its reference. | Crash injection after custody, before local reference write, after custody revoke, and between operation/action completion; repeated recovery reaches one terminal result. |
| A-PR2-R3-P1-005 exact permission flow | OAuth target and attempt status endpoints require internal users. Target lookup maps each action to its exact permission and data scope. A retry-only user can read only the attempt created by that user's retry action. Frontend retry safely navigates the server-provided synthetic authorization URL and starts polling. | Backend authorize/rotate/revoke/retry/external matrix and Vue mount click tests for all four actions. |
| A-PR2-R3-P1-006 service production gate | `begin`, `claim`, `complete`, `fail`, operation update/create, callback handoff, attempt failure/expiry, mutation, and recovery services fail closed through the synthetic environment gate. | Direct service test under disabled synthetic settings verifies zero action, operation, attempt, audit, authorization, and reference changes. |

## Model and migration changes

- Added action and operation execution owner, lease expiry, and fencing fields.
- Added `MarketplaceOAuthResourceLease` with a unique tenant/object resource key.
- Replaced the resource-inclusive action uniqueness constraint with the global action-key registry
  scope required by the R3 contract.
- Migration `0013` performs a read-only duplicate preflight before any DDL. Existing duplicate keys
  fail with a stable message and no migration write, allowing reconciliation and a clean rerun.
- Synthetic refresh references include authorization ID, target version, and operation hash prefix,
  so independent rotations do not reuse one identifier.

## Callback and recovery safety

- Raw state, callback code, token, secret, cookie, session value, and callback query are not stored
  in business tables, action responses, operation metadata, or audit details.
- Only state/session hashes and safe custody reference identifiers are durable.
- Invalid callback ownership cannot poison a valid attempt.
- Fencing is checked before phase updates and terminal writes; an expired owner cannot commit after
  lease takeover.
- Compensation and audit writes are idempotent by operation hash.

## Frontend behavior

- Frontend continues to use only the backend-provided `authorization_url`.
- Navigation is restricted to the synthetic allowlisted origin in this mock-only implementation.
- No authorization URL, state, callback query, code, token, or credential is placed in
  localStorage, sessionStorage, route state, analytics, or error monitoring.
- Retry-only, revoke-only, rotate-only, and authorize-only component actions are mounted and
  clicked in tests.

## Files changed by this remediation

- `backend/apps/integrations/models.py`
- `backend/apps/integrations/oauth_adapters.py`
- `backend/apps/integrations/oauth_services.py`
- `backend/apps/integrations/views.py`
- `backend/apps/integrations/migrations/0013_marketplaceoauthresourcelease_and_more.py`
- `backend/tests/test_shopee_tiktok_auth_foundation.py`
- `frontend/src/utils/oauthNavigation.js`
- `frontend/src/views/integrations/MarketplaceOAuth.vue`
- `frontend/tests/oauth-marketplace.spec.js`
- `frontend/tests/oauth-marketplace-mount.spec.js`
- `docs/00_stage0/review/developer_a_marketplace_oauth_callback_r3_fix_change_log.md`

## Verification

| Check | Result |
|---|---|
| Django check | PASS; no issues |
| `makemigrations --check --dry-run` | PASS; no changes detected |
| Local A2 targeted pytest | PASS; 55 passed, 2 MySQL-only skipped |
| MySQL 8.4 A2 targeted pytest | PASS; 57 passed |
| MySQL 8.4 backend full pytest | PASS; 467 passed |
| Frontend `npm ci` | PASS; 249 packages installed from lockfile |
| Frontend Vitest | PASS; 168 passed |
| Frontend production build | PASS; 1958 modules transformed |
| Build warning | Non-blocking existing `@vueuse/core` PURE annotation warnings |
| `sandbox.ps1 verify integration` | PASS; `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |
| CI guard | PASS; no forbidden files or high-confidence credential patterns |
| OAuth boundary scan | PASS; no finance, Agent RPA, `/admin/`, browser credential storage, or non-synthetic platform URL in production OAuth files |
| Runtime artifact scan | PASS; no tracked dist, node_modules, cache/download runtime files, pyc, or `.env` |
| `git diff --check` | PASS |
| `npm audit --audit-level=high` | NOT CLEAN; two existing high findings in `brace-expansion` and `postcss`; no automatic dependency upgrade was made in this scoped remediation |

## Security boundary and remaining work

- No real account, password, token, cookie, session, API key, API secret, callback code, supplier,
  order, finance, bank, or other real business data was added.
- No order, refund, inventory, purchasing, payment, repricing, listing, or RPA side effect exists.
- Production network and synthetic OAuth gates remain fail closed.
- The known npm advisories require a separately scoped dependency update and regression review.
- A fixed-HEAD independent `A-PR2-ARCH-SEC-R4` review and final remote CI are still required.
  PR #40 must remain Draft and must not be merged before P0/P1 are cleared.
