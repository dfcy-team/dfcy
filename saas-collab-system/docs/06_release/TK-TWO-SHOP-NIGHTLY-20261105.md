# Two-shop video scheduler and creator binding handoff

## Release scope

- New hotfix PR; no release version number is created.
- Base: e0a3227ab3b0b9304d659508e2c493713513dbb5.
- Only tenant 1 stores 15 (TKKJ3MY, authorization 48) and 67 (TKKJ7PH, authorization 49).
- No frontend/backend business source overwrite, token rotation, sample state update, ad changes, or database migration.
- Production release workflow was completed at inspection. V384 candidate PR #501 was running CI, not authorized for auto-deploy. This hotfix must be included/checked before the next release.

## Deployment performed

Files from deploy/: tk_two_shop_nightly.py, tk_two_shop_manifest.json,
saas-tk-two-shop-nightly.service, saas-tk-two-shop-nightly.timer.

Server directory: /opt/saas-collab/production/tk-two-shop-nightly-20261105/.
New systemd unit: saas-tk-two-shop-nightly.timer, 22:10 Asia/Shanghai daily.
Persistent=false: missed timer occurrences do not cause catch-up on restart.
The runner processes the previous complete shop-local day only, sequentially.
No --refresh, --all-authorized, or multi-day backfill. Existing completed batches are skipped.
It shares the original video worker flock; a busy lock fails closed without dispatch.
Existing database leases, authorization, tenant checks and batch deduplication remain in force.

The old saas-tk-video-nightly timer and its 30-day policy are NOT changed or repaired by this PR.
It was failing with source-drift detection. Do not restore that all-shop runner without separately
reviewing the date scope, because it could include these two stores and perform unwanted backfill.

## Version validation

The old manifest's video-sync SHA 10e41318... is the CRLF working-copy hash.
The running LF source matches repository source: b285ede2....
The new runner pins repository-derived SHA256 values for six relevant modules and
normalizes CRLF to LF only. Real content differences still refuse execution.
This does not update the old manifest or silently accept arbitrary live hashes.

## Verification

- Two unittest cases pass: line-ending equivalence/content drift, exact two-store one-day command scope.
- Server --check passed for all six pinned modules.
- systemd-analyze verify passed for new units (unrelated existing cloudmonitor warnings retained).
- Manual systemd run returned already_completed for batch 487/store15 and batch488/store67;
  no duplicate API collection was needed for November 4.
- Video batch487: 1480 videos and daily metric rows, completed, database_verified=true.
- Video batch488: 7 videos and daily metric rows, completed, database_verified=true.
- First scheduled nighttime execution remains to be observed; manual idempotency is not proof of future execution.

## Creator lookup: blocked pending approval

Production configuration v39, ID43, submitted through the normal API as root, based on
effective v38/ID41. Only two exact creator_query_bindings were appended; other settings preserved.
This is pending_approval, NOT effective. Do not approve under the submitter's identity or
replace other production configuration changes. An administrator must compare the current
effective version against base41 before approval; regenerate the candidate if unrelated settings changed.

No new creator profile was written. Existing video creator usernames/open IDs must not be
treated as verified numeric TikTok creator IDs. After approval, resolve trusted IDs from
existing evidence, then use the business lookup entry. Missing/conflicting IDs stay candidates.
Creator automatic scheduling is NOT enabled by this PR; it requires validated identity inputs
and a bounded, deduplicated worker. Video success is not creator completion.

## Rollback and next release

Disable only saas-tk-two-shop-nightly.timer with systemctl disable --now; do not stop other timers
or delete already imported data. If a run is active, let it finish rather than killing it.
Retain the deployed files for audit. The pending config can remain unapproved.
Before the next version release, incorporate this PR, check six source hashes against the
candidate source and the deployed code, and validate the timer without forcing collection.
Do not create a separate hotfix release version or reuse an already released PR.
