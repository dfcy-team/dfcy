# GMV Max collection evidence in sync records

## Delivered

The sync-content selector now includes GMV Max advertising. It reads existing
`ads_gmv_max_day` audits, not BASIC reports and not synthesized SyncRun jobs.
The detail view exposes an allowlist of report date, advertiser, snapshot ID,
commit/reuse evidence and error code/type. Tokens and raw provider pages are excluded.
One saved/reused daily snapshot does not mean one new business row or campaign.

Tenant and store visibility are retained. Successful records must reference a
snapshot belonging to the currently permitted store and advertiser, preventing
old store records from being relabeled following a mapping transfer.
Unrecorded scheduler identity, trigger, timing and business-row counts remain unknown.

## Production read-only checks

- Full first page: 1,152 audits, 50 returned, 0.864 seconds.
- November 9-10 execution dates: 55 audits, 0.592 seconds.
- Historical failures: 578 audits, 0.398 seconds; these are not current failed jobs.
- Invalid store and non-TikTok platform: zero rows.
- Deployed authenticated view: GMV Max HTTP 200, 0.571 seconds, 1,152 audits.
- Existing video and creator views: HTTP 200, 575 batches / 4,970 snapshots.
- Three pure presentation tests, selector request test and frontend build passed.
- Permission checks above do not replace a full ordinary-user/role matrix test.

## Deployment

Additive backend module plus narrow changes to the workspace source dispatcher.
New versioned frontend page: `SyncExecutionRecords-gmv-45f64fe57df2.js`.
Existing capability-page import map and application entrypoint remain intact.
Only Web workers are gracefully reloaded; no Celery restart, new task,
timer change, migration, provider request or collection is performed.

Backup directory: `/opt/saas-collab/production/operations/gmv-records-20261110`.
Rollback uses `index.before.html` and the three `*.before` backend files followed
by a Web-worker reload; the unused additive module may remain.
This PR is based on the capability hotfix PR #549; merge its predecessor first.
