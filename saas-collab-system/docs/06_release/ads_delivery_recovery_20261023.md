# Ads delivery recovery (2026-10-23)

Orphan queued-dispatch recovery for automatic schedules (interval, hourly, daily, or weekly) is default-off in this batch. The setting `SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED` is intentionally undefined here; only an explicit boolean `True` in an approved controlled Django configuration opts in. A missing setting, false value, or non-boolean value (including an environment string such as `"true"`) leaves recovery off. No configuration is changed by this batch.

When explicitly enabled, the scheduler retires an orphan queued dispatch only after its enqueue timestamp is at least 30 minutes old and two independent, complete broker snapshots both show its scheduled idempotency fence absent. Rows without an enqueue timestamp remain for manual review. Snapshot errors, partial scans, visible messages, associated or active runs, started dispatches, active locks, disabled jobs, and paused jobs all leave the dispatch untouched. Manual and cron jobs are excluded. The scheduler rechecks the job and dispatch under row locks before changing the existing dispatch to `dispatch_failed`.

Recovery preserves the dispatch row and its scheduled timestamp, writes a reason and finish time, leaves `next_run_at` unchanged, and never sends another queue message. This also fences a late original message: the worker checks for `queued` while holding the job lock and returns `not_executed` for a terminal dispatch. A future `next_run_at` remains future; an expired slot follows the configured catch-up policy on the normal scheduler tick.

This change covers all automatic interval/hourly/daily/weekly schedules when explicitly enabled; it does not add the separate nightly 3–7 day correction or extend alerting.
