# GMV Max collection status and targeted backfill

## Scope

- Three authorized Aliyun tenant 1 advertiser/day gaps only. No BASIC facts,
  influencer costs, credentials, approval configuration, timers, or mappings changed.
- Initial PR submission did not deploy code. A later explicit user confirmation
  authorized the bounded production overlay documented below.
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
  retain the new evidence.

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
  VITE_USE_MOCK=false. Authenticated production UI acceptance was not performed.

## Authorized production overlay, November 4

- User explicitly requested preservation of the newer GMV Max-only page while
  overlaying collection-status fixes. PR #483 source was integrated into #484
  without merging either PR on GitHub or bypassing approval.
- Backend focused regressions: 68 passed; frontend component/API: 13 passed;
  the combined non-mock production build and standalone module syntax passed.
- Durable server receipts and immutable pre-change file backups:
  `/opt/saas-collab/production/hotfix-ads-collection-status-20261104-r1/`.
  Files: `plan.json`, `receipt.json`, `verification.json`, `backup/`, `after/`,
  `before-verification.txt`, `candidate-verification.txt`, `after-verification.txt`.
- Six backend files changed. AST-fenced replacements preserve other live functions;
  the report-service overlay preserves the newer advertising_store_scope permission
  integration rather than copying this branch's complete service over live code.
- Frontend adds `TikTokGmvStatus-0076d4963680.js` and
  `MarketingAdvertising-GmvStatus-ea5042807b19.js`, changes only the active main
  module's two advertising-wrapper references, and preserves index.html and all
  other entry/shared modules. No second Vue application is introduced. Existing
  browsers may need a hard refresh to discard the previously cached main module.
- Gunicorn received HUP after the entire paired reader/collector update; container
  IDs and index.html hash remained unchanged. No container restart, schema change,
  approval/mapping/credential/timer edit, provider collection, or business-data write
  occurred during this deployment. The three earlier authorized backfills remain.
- Production read-only view invocation: HTTP 200, scope GMVMax, 105 reports,
  15 shop groups, 385 status rows; 105 success, 280 not_collected, 0 no_data/failed.
  Old journal-only failures were not manufactured into database receipts. Future
  scheduled failures now append sanitized day evidence; successful empty official
  responses become no_data rather than inferred zero spend.
- Before/candidate/after financial fingerprints all match:
  `96592ae6d5d7d37c3e49c564c8003a087507d572f24b0f8b217ad09c248378c9`.
  Both new assets returned HTTPS 200 and matched staged SHA256; active files match
  the receipt. Root view verification uses a separate process and read-only SQL
  transaction, not a logged-in browser or a provider authorization test.
- Rollback: only run the new deployment script's rollback mode when every live
  target still matches its recorded after hash. It preserves report data and
  harmless unreferenced new assets. Stop if a later change is detected; never replay
  the previous November 3/GMV-only deployment scripts on this updated environment.
