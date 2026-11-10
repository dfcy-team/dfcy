# Sync record collection evidence hotfix

## Scope

Same `/integrations/sync-runs` page: system runs, video batches, creator latest snapshots.
This does NOT migrate scheduling to Celery, create SyncJobs, start collection, or
change timers, tokens, order collection, BD snapshots or renewal policy.

## Evidence contract

- Video rows use TikTokVideoSyncBatch. Completed video_count is stored evidence,
  not new/updated row counts. Detail successes/failures remain separate.
- Creator rows use TikTokCreatorProfileSnapshot. One latest snapshot per creator
  and shop is not historical query count. Identity mismatch is not verified success.
- Unknown fetched/created/updated/failed counts remain null. No synthetic job IDs.
- Query requires both integration and store-view scopes, filters tenant and shop,
  paginates in SQL, and explicitly labels timestamps and evidence provenance.
- Existing system SyncRun list and its cleanup operation remain unchanged.
- No tokens, raw payloads, or raw error summaries are exposed.

## Validation

Production staged helper SELECT-only check: 575 video batches, 4970 creator
snapshots visible to tenant 1 administrator at verification time. Checks cover
two-row pagination, no page overlap, other platform excluded, inaccessible shop
excluded, incompatible job filter empty, future date empty, unknown counters.
Frontend production build and menu registry check passed. These checks do not
prove native scheduling or end-to-end browser acceptance.

## Release

Use `frontend/build-sync-evidence-hotfix.mjs LIVE_ASSETS_DIRECTORY` then
`frontend/deploy-sync-evidence-hotfix.py` preflight and explicit `--apply`.
The matching `deploy-sync-evidence-query.py` adds and validates record_source in
the existing API query allowlist. Both backend changes are required. These are
one-time CAS deployment scripts, not general idempotent release commands.
Guard live hashes and dependency exports/CSS; never overwrite index.html or root
bundle. Add standalone presentation helper only under its content-hashed filename.
Patch live workspace_service wrapper only; preserve other online hotfixes.
Backup directory: `/opt/saas-collab/production/operations/sync-evidence-20261109/backup`.
Reload API gracefully only; do not restart collection workers.

Rollback: restore backed-up workspace_service.py and page JS to their original
container paths and gracefully reload API. New unreferenced helper assets may
remain. No database rollback is required because deployment has no DB writes.

Do NOT deploy unrelated unfinished model/adapter/collector work in this branch.
Do NOT deploy the separate automatic-renewal policy change with this hotfix.

## Actual deployment verification

Deployed 2026-11-09: live workspace wrapper, allowlist, new read-only helper and
SyncExecutionRecords-CQKzcVFv.js only (plus a standalone presentation asset).
Latest live dependencies and CSS were verified before replacement. Root bundle,
index.html and all existing collection workers/timers were left unchanged.
DRF endpoint checks: video and creator HTTP response objects 200, invalid source
400; returned totals 575 and 4970. Public page JS returned HTTP 200 and contains
both new selectors. Browser click-through has not been independently verified.
Rollback must also restore backup/views.py with workspace_service.py.

## 2026-11-10 blank-page correction

The initial asset mapper normalized different application entry hashes as if
they were equivalent. Some selected component dependencies imported
index-C6T8h0h3.js, a second complete application entrypoint. Browser reproduction
confirmed a second mount, `nextSibling` on null, and an empty document body.
HTTP 200 and a successful build had not detected this runtime failure.

Corrected the mapping to exclude the foreign entrypoint, and recursively verify
the static dependency closure rather than just direct imports. Kept the current
v404 root and its compatibility aliases unchanged. Deployed only the repaired
SyncExecutionRecords-CQKzcVFv.js using hash guards and a backup at
`/opt/saas-collab/production/operations/sync-evidence-deps-20261110/before.js`.

Verified in a fresh headless Edge browser through the actual public site, both
with the staged page and again after deployment: module imported successfully,
login body text length remained 203 before and after import, no page errors and
no foreign entrypoint requests. This reproduces the original failure and checks
its repair, but is not an authenticated click-through of every table filter.
No backend, token, task, timer or business data changed in this repair.
