# Creator/video system scheduler migration

User decision: migrate collection to system scheduling; disable the corresponding
external timers only at cutover. Preserve affiliate/ad task scheduling.

## Delivered prerequisite

`apps/integrations/collection_cutover.py` is a pure admission planner. It does
not create jobs or execute shell commands. It proposes disabled new jobs,
reuses exact tenant/authorization/resource jobs, rejects duplicates or mismatched
configurations, and checks complete shared-timer coverage. Active or unknown
in-flight execution prevents timer shutdown. Verified system execution and a
cutover fence are both required. Ten offline tests pass.

## Not implemented / not deployed

- SyncJob resource choices, serializer/scope validation and UI labels for creator
  profiles and video metrics are not registered yet.
- Collector execution adapters, durable per-unit receipts, result counters and
  system-scheduler routing are not implemented.
- No system jobs were created, enabled or scheduled. No external timer stopped.
- The planner's evidence inputs are not automatically loaded from production.
  Do not treat a caller-supplied boolean as deployment verification.

## Execution integration requirements

Video currently uses `tiktok_video_sync.run_day` and its own leased batch. Creator
lookup uses `lookup_tiktok_creator` and writes snapshots within that service.
The generic synchronization engine persists normalized pages inside a database
transaction. Calling these collectors from its persist hook would hold a page
transaction across network requests. Calling them from fetch without durable
receipts could commit data without a matching SyncRun count after a crash.

Implement durable unit receipts and lease fencing before enabling resources.
Keep API calls outside database transactions. Store identity matching outcomes
separately from saved snapshot counts; partial video detail failures must not be
reported as complete. Preserve existing business permission/capability gates.
Freeze window/selection per run and checkpoint successful units so retries do not
recollect completed work. Validate actor, tenant, authorization and source at
every persisted unit. Use a single collection concurrency slot initially.

Before cutover, inventory exact subjects of both the all-shop video timer and
the two-shop video timer. A shared timer may stop only when every subject is
covered. Disable external dispatch, drain active work, then transfer ownership
under a shared fence before enabling native schedules. Retain prior records;
do not manufacture historical SyncRun successes or replay old windows merely
to populate the page. Record rollback and live acceptance evidence separately.
