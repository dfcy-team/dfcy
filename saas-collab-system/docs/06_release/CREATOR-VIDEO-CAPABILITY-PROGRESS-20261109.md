# Creator/video capability progress

## Delivered

The existing store capability matrix now returns and displays an independent
read-only collection_progress section for TikTok stores visible through the
existing authorization scope. No connection-capability enum, database migration,
permission grant, enabled switch, task or timer is created.

Creator counts are current snapshot rows grouped by the queried store, not a
complete creator roster and not proof of creator ownership by that store. Matched
identity counts are separate. Video evidence is the 14 most recently updated
store batches; only completed batches expose their video_count as committed
evidence. No percentage or overall historical completion is invented.

The existing integrations.view permission is additionally required to query
execution evidence. Tenant and store are always passed into both queries.
Store authorization visibility still gates the parent endpoint.

## Explicit limits

- Stores absent from the existing authorization selector are not added here.
- Systemd scheduler state, job logs before batch creation, full failure causes,
  provider scope validity and full historical coverage are not in these models.
  The UI explicitly states scheduler state is unverified.
- No raw error payloads, creator identities, credentials or cursor values are
  returned by this projection.
- A stored running status is not a liveness assertion.
- This patch does not activate paused timers or perform collection.

## Verification

Four isolated query-contract tests cover non-TikTok exclusion, access restriction,
tenant/store filters, identity-count distinction and failed-batch count handling.
They mock the ORM and do not replace database/API integration testing.
Production deployment and browser acceptance are pending.
