# A-PR2 R4 P1 remediation change log

## Scope

This change log records the fourth-round remediation for
`a_pr2_arch_security_r4_review.md` on branch
`feature/module-a-platform-oauth-callback`.

- Base before remediation: `3c1577d321c46449aa91bf1bcf9565888e08746d`.
- PR: #40 remains Draft and is not merged.
- Capability status: synthetic/mock only. Nothing is marked `connected`.
- No real Shopee, TikTok Shop, credential custody, or platform network request was enabled.
- No DDL or migration is introduced; all changes are service-layer logic, write gates, and tests.

## P1 closure matrix

| Finding | Remediation | Evidence |
|---|---|---|
| A-PR2-R4-P1-001 fencing did not cover business side-effect boundaries | Added `assert_operation_fence`: inside the caller's transaction it row-locks the durable operation (`select_for_update`) and fails closed on owner mismatch, bumped fence, or expired lease, holding the lock until the fenced business write commits. `create_store_authorization`, `transition_store_authorization`, and `rotate_store_authorization_references` accept an `operation_claim` and run the fence check before any business write; `rotate` runs it inside its `transaction.atomic` block before locking the authorization row (global lock order: operation -> authorization). `_complete_exchange`, `refresh_authorization`, `revoke_authorization`, and `_set_reconcile_required` now pass the claim through every create/rotate/transition/reconcile boundary, and the attempt terminal write inside exchange is also fence-checked. After a takeover the old owner performs zero business writes. | Fence gate negative test (foreign owner, bumped fence, expired lease); direct stale-claim exchange-create probe with zero-side-effect assertions; three MySQL double-worker pause/expire/takeover boundary tests covering exchange create, refresh rotate, and revoke transition, each asserting `StateConflict`, zero authorization/audit/attempt side effects, and that the new owner still completes. |
| A-PR2-R4-P1-002 action and operation terminal states diverged; recovery window not closed | `complete_oauth_action` and `fail_oauth_action` now commit the operation terminal state in the same transaction and under the same claim/fence validation as the action terminal write: success sets `SUCCEEDED` with an action-specific terminal phase (`initiate_completed`, `refresh_completed`, `revoke_completed`, `retry_completed`, `completed`), failure sets `FAILED`/`RECONCILE_REQUIRED` with phase `action_failed` and the error code; both release execution owner and lease atomically. `recover_oauth_operation` gained a Window-B convergence branch: when the action is already terminal but the operation is not, recovery claims the operation with a fresh fence and converges it to the matching terminal state idempotently, so initiate/retry operations can never stay `pending` forever and recovery always reaches a terminal result. | Initiate/retry/fail terminal-state tests asserting action and operation reach matching terminal status and phase with owner released; two crash-window tests simulating process death between action and operation commits, asserting recovery converges the operation and a second recovery call stays idempotent for the success window. |

## Hardening applied alongside P1

- `MarketplaceOAuthResourceLease` (R4 P2-1) is now protected by a dedicated `oauth_lease_write`
  service gate: model `save`/`delete` and QuerySet `update`/`bulk_create`/`bulk_update` fail
  closed outside the OAuth service layer; the lease create path inside `claim_oauth_action`
  runs under the same gate.
- The lease create/update path inside `claim_oauth_action` is fully wrapped by the lease gate,
  so no lease mutation exists outside the guarded service boundary.

## Concurrency and lock ordering

- Global lock order is operation row -> authorization row; `complete`/`fail` only touch
  action -> resource lease -> operation and never lock authorization rows, so no new lock
  cycle is introduced.
- The fence check must execute inside the caller's transaction; `rotate` performs it inside
  its `transaction.atomic` block so the operation row lock is held until commit.
- Takeover bumps the operation fence and owner; any in-flight old owner blocks on the row
  lock and observes the stale claim at release, raising `StateConflict` with zero writes.

## Files changed by this remediation

- `backend/apps/integrations/models.py`
- `backend/apps/integrations/oauth_services.py`
- `backend/apps/integrations/store_authorization_service.py`
- `backend/tests/test_shopee_tiktok_auth_foundation.py`
- `docs/00_stage0/review/developer_a_marketplace_oauth_callback_r4_fix_change_log.md`

## Verification

| Check | Result |
|---|---|
| Django check | PASS; no issues |
| `makemigrations --check --dry-run` | PASS; no changes detected (no DDL in this round) |
| MySQL 8.4 A2 targeted pytest | PASS; 68 passed (baseline 57 + 11 new) |
| MySQL 8.4 backend full pytest | PASS; 478 passed (baseline 467 + 11 new) |
| Frontend Vitest | PASS; 168 passed (run with `VITE_USE_MOCK=true`; the container runtime env sets `VITE_USE_MOCK=false` for the dev server, which the mock-gate unit test intentionally requires to be overridden) |
| Frontend production build | PASS; built without error |
| `sandbox.ps1 verify integration` | PASS; `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |

## Security boundary and remaining work

- No real account, password, token, cookie, session, API key, API secret, callback code, supplier,
  order, finance, bank, or other real business data was added.
- No order, refund, inventory, purchasing, payment, repricing, listing, or RPA side effect exists.
- Production network and synthetic OAuth gates remain fail closed.
- The known npm advisories from R3 remain untouched; they require a separately scoped dependency
  update and regression review.
- A fixed-HEAD independent `A-PR2-ARCH-SEC-R5` review and final remote CI are still required.
  PR #40 must remain Draft and must not be merged before P0/P1 are cleared and CI is green.
