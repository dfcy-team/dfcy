# Tenant 1 nightly recovery, 2026-11-09

## Scope and actual operations

- No application image deployment. PR 517 was NOT deployed.
- Existing video timers remain 20:00 and 22:10 Asia/Shanghai.
- Revalidated video model ASTs against the prior two-shop branch. All five video
  models match. Video sync, dataset API and dataset reader match the approved
  two-shop manifest. Old full-store manifest had the older video sync hash.
- Updated both video manifests with backups and hash fences. Changed existing
  all-store runner from repeated 30-day refresh to seven complete days without
  refresh, pause ten seconds; completed batches are skipped by business key.
- Restored TK3PH mappings through ads_capability_api.capability with actor 1,
  after validate_mapping(require_enabled=False) passed. Existing jobs
  179, 197, 209 retained. No new advertising job and no direct credential edits.
  No post-recovery advertising success observed yet at the last verification.
- Added host timers: affiliate 23:00, creator 00:30 Asia/Shanghai. Shared existing
  video worker lock, single added workload, load guard, nice 10, no service restart.
- Affiliate reuses 16 enabled manual jobs. Four disabled jobs remain disabled.
  Each night covers last three complete shop-local days; existing successes and
  idempotency keys are not fetched again. Busy jobs and failed existing keys are
  isolated, not reset. Failed schema/identity validation is NOT bypassed.
- BD refresh consumes pending receipts in batches of twenty and preserves pending
  on failure; completed recalculation is not proof of successful BD attribution.
- Creator limit 100 per run, trusted numeric ID, unambiguous approved-market
  business lookup, missing snapshot only, five seconds between calls, three
  consecutive exceptions stop. No main identity or sample-status edits.
- Initial affiliate and creator services submitted behind the running video
  service (systemd ordering); queued is NOT completed.

## Last verified result

Video: seven completed TK6PH day batches (Nov 2..8), 412 video-day rows,
database readback verified. Next video batch running.
Affiliate and creator new ingestion counts are not yet available.
These counts are a dated receipt, not a live dashboard.

## Validation

- Existing video rate quarantine tests: 6 passed.
- New offline load/deadline/creator-skip/identity-count tests: 6 passed.
- Affiliate preflight for all sixteen enabled manual jobs: passed.
- systemd unit validation passed (pre-existing cloudmonitor warnings unrelated).
- Timer list confirms next affiliate Nov 9 23:00 and creator Nov 10 00:30.
- Production end-to-end affiliate/creator execution remains pending.

## Known remaining work

- Historical September/October affiliate backfill is NOT restarted here.
- Missing identities, AWAITING PAYMENT and zero-order parser behavior still need
  their own approved repair. This recovery does not claim those gaps are fixed.
- BD daily dispatcher already exists at 19:00 UTC; this runner handles its own
  pending affiliate receipts. No duplicate standalone BD scheduler was created.
- Paired backup service separately reports IMAGE_CHANGED_REVALIDATION_REQUIRED;
  it was not modified in this ingestion task.
- Sources are pinned in a server-side hash manifest. Future application release
  requires deliberate revalidation; do not overwrite hashes without checking.

## Rollback and handoff

Operational root: /opt/saas-collab/production/nightly-recovery-20261109
Existing video root: /opt/saas-collab/production/hotfix-tk-video-sync-20261031
Backups end with .before-20261109. Do not restore while a worker holds the lock.
Do not rerun install_nightly.py: exclusive file creation deliberately refuses
to overwrite deployed state. Disabling timers does not cancel active ingestion.
Inspect per-item journal entries and database receipts before retrying failures.
No credentials belong in this PR.
