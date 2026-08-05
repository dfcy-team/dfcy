# A-PR2 R5 P1 remediation change log

## Scope

This change log records the fifth-round targeted remediation for
`a_pr2_arch_security_r5_review.md` (finding `A-PR2-R5-P1-001`) on branch
`feature/module-a-platform-oauth-callback`.

- Base before remediation (fixed R5 HEAD): `5111c00041a897377dc31153188bebdaeee227c7`.
- PR: #40 remains Draft and is not merged.
- Capability status: synthetic/mock only. Nothing is marked `connected`.
- No real Shopee, TikTok Shop, credential custody, or platform network request was enabled.
- No DDL or migration is introduced; all changes are service-layer locking logic and tests.

## P1 closure matrix

| Finding | Remediation | Evidence |
|---|---|---|
| A-PR2-R5-P1-001 business write boundary only locked the operation row; the shared resource lease could be taken over between fence validation and commit | `assert_operation_fence` now resolves the shared resource lease identity carried by action-bound claims (`tenant_id` + `object_type` + `object_id`). When present, it row-locks the shared `MarketplaceOAuthResourceLease` FIRST with `select_for_update()` and fails closed on missing lease, owner mismatch, bumped fence token, or expired lease, then row-locks the operation and validates the same claim fields. Because the fence runs inside the caller's transaction, the fenced business write (create/rotate/transition/reconcile) holds the shared lease row lock until commit, so `claim_oauth_action` of a new action blocks on that lock and can never issue a higher resource fence while the old owner's fenced write is open. Claims without a lease identity (callback exchange operations) keep the single operation row lock. | Fence gate unit test extended with a bumped-resource-lease-fence negative case (foreign owner, bumped operation fence, bumped lease fence, expired lease all raise `StateConflict`). Three MySQL double-worker tests rewritten around the post-fence pause point (below) prove takeover blocks on the shared lease row, the new fence is issued strictly after the old transaction ends, and the old worker leaves zero side effects. |
| Latent stale-clock issue exposed by the new blocking semantics: `claim_oauth_action` / `claim_oauth_operation` computed `now` before acquiring blocking row locks, so after waiting on the lease/operation row lock the expiry check used a stale timestamp and a takeover that legitimately waited out an expired lease was wrongly reported as "lease busy" | Both claim functions now recompute `timezone.now()` after each blocking `select_for_update()` acquisition (action row, resource lease row, operation row), so expiry decisions reflect the moment the lock is actually held. This is fail-open only for genuinely expired leases and stays fail-closed for live ones. | New MySQL double-worker tests would fail without this fix (takeover returned `claimed=False` after blocking 4.5s on the lease row); with the fix all takeover claims succeed after the old transaction ends. |

## Test pause-point correction and new double-worker coverage

- `_pause_fence_and_take_over` (paused BEFORE fence validation) is replaced by
  `_pause_after_fence_and_take_over`: the worker completes the original
  resource+operation fence validation first, then pauses while its fenced write
  transaction stays open and keeps holding the shared resource lease / operation
  row locks.
- The takeover runs in its own thread; the helper asserts the takeover is still
  blocked while the old transaction holds the row locks (blocking/serialization
  semantics), then simulates an old-worker crash inside the boundary so the old
  transaction rolls back with zero side effects; only afterwards does the blocked
  takeover proceed and issue the new fence. "New fence issued, old worker commits
  later" is structurally impossible because fence issuance waits on the same row
  lock the fenced write holds until commit/rollback.
- Rewritten MySQL tests (skipped off-MySQL):
  - `test_mysql_exchange_create_fence_holds_operation_row_until_commit`: old
    exchange worker passes its fence, pauses holding the operation row lock; the
    operation lease expires on the wall clock; takeover via `claim_oauth_operation`
    blocks then claims; old worker zero side effects (no authorization, no audit,
    attempt stays `callback_received`); recovery converges to `active`.
  - `test_mysql_refresh_rotate_fence_holds_resource_lease_until_commit`: old
    refresh worker passes fence, pauses holding lease+operation row locks; after
    wall-clock lease expiry the second refresh action's `claim_oauth_action` blocks
    then claims a higher fence; asserts old worker left
    `credential_reference_version == 1` with zero new audit rows, lease
    `fence_token` equals the new claim fence, and the new owner completes the
    rotation to version 2.
  - `test_mysql_revoke_transition_fence_holds_resource_lease_until_commit`: same
    timing for revoke; asserts authorization stays `pending`, no
    `custody_revoked` metadata, zero new audit rows, and the new owner completes
    the transition to `revoked`.

## Concurrency and lock ordering

- Unified global lock order: action row (action-management paths only) -> shared
  resource lease row -> operation row -> authorization row.
- `claim_oauth_action`, `complete_oauth_action`, and `fail_oauth_action` lock
  action -> lease -> operation; fenced business writes lock lease -> operation ->
  authorization and never lock action rows, so no new lock cycle is introduced.
- The fence must execute inside the caller's transaction; `rotate` performs it
  inside its `transaction.atomic` block, `create`/`transition`/`_set_reconcile_required`
  are already transactional, so the lease row lock is held until the fenced write
  commits.

## Files changed by this remediation

- `backend/apps/integrations/store_authorization_service.py`
- `backend/apps/integrations/oauth_services.py`
- `backend/tests/test_shopee_tiktok_auth_foundation.py`
- `docs/00_stage0/review/a_pr2_arch_security_r5_review.md` (archived review input)
- `docs/00_stage0/review/developer_a_marketplace_oauth_callback_r5_fix_change_log.md`

## Verification

| Check | Result |
|---|---|
| Django check | PASS; no issues |
| `makemigrations --check --dry-run` | PASS; no changes detected (no DDL in this round) |
| Local sqlite targeted pytest (`test_shopee_tiktok_auth_foundation.py`) | PASS; 63 passed, 5 MySQL-only skipped |
| Local sqlite backend full pytest | PASS; 473 passed, 5 MySQL-only skipped |
| MySQL 8.4 A2 targeted pytest | PASS; 68 passed |
| MySQL 8.4 backend full pytest | PASS; 478 passed |
| Frontend Vitest | PASS; 14 files, 168 tests passed (`VITE_USE_MOCK=true`) |
| Frontend production build | PASS; 1958 modules transformed; only the pre-existing `@vueuse/core` PURE annotation warning |
| `sandbox.ps1 verify integration` | PASS; `LOCAL_SANDBOX_VERIFY=PASS profile=integration` |

## Security boundary and remaining work

- No real account, password, token, cookie, session, API key, API secret, callback code, supplier,
  order, finance, bank, or other real business data was added.
- No order, refund, inventory, purchasing, payment, repricing, listing, or RPA side effect exists.
- Production network and synthetic OAuth gates remain fail closed.
- The known npm advisories from R3 (`brace-expansion`, `postcss`) remain untouched; they require a
  separately scoped dependency update and regression review.
- A fixed-HEAD independent `A-PR2-ARCH-SEC-R6` review and final remote CI are still required.
  PR #40 must remain Draft and must not be merged before P0/P1 are cleared and CI is green.
