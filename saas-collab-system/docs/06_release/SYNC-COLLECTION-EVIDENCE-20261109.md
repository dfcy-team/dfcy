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

## 2026-11-10 versioned page repair (supersedes earlier deployment)

The user still reported a blank page after the first correction. Rolled back
the page to original SHA256 0ef227fd7224be2e3ac61a0479aa8262df869ab3c24fa33ace076e65266424d0
while testing full component rendering. Reusing a static asset URL did not
reliably exclude a cached copy of the original broken page.

Published the corrected component as
`SyncExecutionRecords-evidence-63529ad8bf87.js`. An import map preceding the
existing module entry in index.html redirects only the old sync-page URL to
this new asset. The v404 application bundle, compatibility aliases, old page,
other pages, APIs, timers and business data are unchanged. This scoped HTML
change supersedes the earlier no-index-change instruction; do not replace the
root application bundle. The next formal frontend build should include the Vue
source normally and should not carry this temporary import map forward.

Deployment: `frontend/deploy-sync-evidence-versioned.py`, one-shot hash guards.
Backup: `/opt/saas-collab/production/operations/sync-evidence-versioned-20261110/index.before.html`.
Rollback restores only that index.html; versioned unreferenced assets can remain.
Deployed HTML SHA256: d5dbc72dc6f1144d8d451dd40c7fe8bfcf0c8ab2f6d2b7e0429921f0100f73d8.

`frontend/test-sync-evidence-browser.cjs` passed before and after deployment:
full page rendering, video tab, creator tab, both detail drawers, system tab,
and reload. It deliberately serves a throwing module at the old page URL to
prove the import map avoids the broken asset. Post-deployment mode uses the
actual public HTML and frontend assets. All API calls and authentication are
isolated fixtures intercepted inside a fresh browser context; no fixture token
is sent to production. This is not verification of the user's existing login
session or actual business rows. No browser-console errors were observed.

Run using the available Playwright runtime, with CANDIDATE=1 for staging or
VERIFY_DEPLOYED=1 for deployed assets. These checks never create sync jobs or
start collection. Actual session acceptance remains for the user to confirm.

## 2026-11-10 unified content selector

User requested the video and creator entries inside the existing synchronization
content dropdown, not separate radio buttons. Removed the radios; added video
collection and creator profile choices, plus a Chinese affiliate-order label.
Selection chooses the existing read-only evidence endpoint or original system
query without changing collectors. System resource choices remain available
after entering evidence views. Shop/date filters are retained; incompatible
status, trigger and task filters reset when switching content.

Production build passed with VITE_USE_MOCK=false. Staged browser tests passed
for both evidence choices, detail drawers, switching back to affiliate orders,
and reload. Fixtures intercept all APIs. A local proxy TLS failure during testing
was bypassed only for the test browser with DIRECT=1; no system proxy was changed.

Deployed page: SyncExecutionRecords-evidence-a3939a3a2d0a.js.
HTML SHA256: cfe688b7fc32a98486dc6103da8a6dc762fb1c5411ba314baa01846cace1b3ae.
Rollback HTML: /opt/saas-collab/production/operations/sync-content-selector-20261110/index.before.html.
Only the existing import-map target and new page file changed. No backend,
authorization, timer, collector or database changes were deployed.
