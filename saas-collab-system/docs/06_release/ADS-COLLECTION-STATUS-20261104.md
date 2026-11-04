# GMV Max collection status and targeted backfill

## Scope

- Three authorized Aliyun tenant 1 advertiser/day gaps only. No BASIC facts,
  influencer costs, credentials, approval configuration, timers, or mappings changed.
- Code changes are submitted for review, not deployed by this operation.
- Includes the existing production shop-summary change, rebased onto current main;
  preserves the separate BASIC/GMV Max boundary and analysis-page title.

## Investigation and production receipts

Range: 2026-10-28 through 2026-11-03, advertiser-local dates.

| Store | Mapping | Missing day | Historical failure class | Raw receipt | Success audit |
| --- | --- | --- | --- | --- | --- |
| TK1PH | 2 | 2026-11-03 | ValidationError, sanitized generic reason | 120 | 1181278 |
| TK9PH | 23 | 2026-10-31 | OperationalError | 121 | 1181279 |
| TKKJ1PH | 24 | 2026-10-30 | OAuthFlowError | 122 | 1181280 |

Each day was read successfully without committing first, then collected once using
the existing guarded run_day(commit=True), and its stored payload hash/date verified.
No blind retries, fabricated zero facts, or global refresh were used. Historical logs
do not retain enough detail to establish an exact database/OAuth underlying cause;
successful re-reads establish recovery, not a proven permanent infrastructure fix.

TKKJ1PH mapping 25 had gmv_max_store_not_verified on all seven days. It was NOT
reclassified as empty, re-bound, or included as seven successful zero-spend days.

## Behavior

- A successful official response with all existing identity, exclusive-store,
  pagination, and metric checks is either data or a verified empty report.
- A verified empty report has collection_status=no_data and null monetary/order
  metrics. It counts toward query coverage, not invented zero-spend facts.
- Non-empty zero metrics remain valid reported zeros, distinct from empty reports.
- Failed scheduled attempts append sanitized tenant/config/mapping/day evidence.
  No token, provider URL, or arbitrary exception message is recorded.
- Reading status is permission-filtered, makes no provider requests, separates
  success/no_data/failed/not_collected, and retains already verified historical facts
  even if a later refresh fails. Audit reads are bounded and fail visibly on overflow.
- Old failures existing only in journal logs remain unverified in the UI until
  another bounded collection produces evidence; absence never becomes no_data.
- No schema migration is needed: existing immutable raw payloads and audit logs
  retain the new evidence. No production code deployment is included here.

## Rollback boundary

Reverting presentation/collector code does not require deleting the three verified
reports. Do not replay old deployment scripts or replace the production dist tree.
An older reader rejects newly stored empty snapshots; deploy reader and collector
together and do not roll back only the reader after collecting empty snapshots.

## Verification

- Aliyun readback: mappings 2, 23 and 24 each have seven distinct dates in the
  stated range after backfill; verified reports retained their original USD currency.
- Backend focused regressions use an isolated in-memory SQLite test database with
  --nomigrations; they are not MySQL/migration execution evidence.
- Frontend daily-spend component/API: 13 tests passed. Production build passed with
  VITE_USE_MOCK=false. Authenticated production UI acceptance was not performed;
  the changed UI and collector have not been deployed.
