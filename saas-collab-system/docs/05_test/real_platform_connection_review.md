# A-REAL-PLATFORM-CONNECTION REVIEW

Review date: 2026-08-10. Current result: **FAIL / REQUEST CHANGES**. Offline-remediable P1 items are closed; this is still a developer pre-review, not reviewer approval.

## Evidence identity

| Field | Value |
|---|---|
| Repository | `dfcy-team/dfcy` |
| PR | Draft #42 — `https://github.com/dfcy-team/dfcy/pull/42` |
| Branch | `feature/module-a-real-platform-connection` |
| Base | `feature/module-a-marketplace-oauth` @ `5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0` |
| Code Review / CI SHA | `ea62cc791b599e9e83a68346630a27621d6e2c08` |
| Final PR Head SHA | Evidence-only successor; read from Draft PR #42 after this commit |
| Final commit count / changed files | Freeze from final PR #42 head |
| Source artifact | `a-real-platform-ea62cc7.zip` / SHA-256 `AE6731248227DAC39A15F1D38F3BB192BB75F4511DA3AA85B0A559831AF29792` / 1,548,019 bytes |
| Runtime image digest | NOT AVAILABLE |
| Environment | Local Sandbox; real-platform switches OFF |
| Database | Previous MySQL 8.4.10 Sandbox PASS; current code SHA NOT RERUN (Docker daemon timeout) |
| Migration head | `integrations.0013_authorization_reauthorization_bindings` |

PR-A1 architecture/security R2 recorded PASS for its fixed scope. PR-A2 review recorded architecture/security/testing PASS for synthetic scope, with repository-hygiene and CI observations. Neither conclusion proves live connectivity.

## Review matrix

| Area | Result | Evidence / blocker |
|---|---|---|
| PR-A2 state/replay/context baseline | PASS locally | A2 + focused regressions |
| exact permissions and tenant/store isolation | PASS locally | included in 543-test backend suite |
| callback forbids token/tenant/user/internal store | PASS locally | negative tests |
| synthetic/live separation and default fail closed | PASS locally | live gate tests; no connected override |
| custody architecture | PASS offline / deployment pending | HTTP plus operator-owned file custody; atomic write, 0700/0600 modes, cross-process conflict test |
| outbound allowlist/TLS/timeouts/retries | PASS in controlled tests | real egress not tested |
| callback query log/report suppression | PASS offline | query-free 303; callback-aware Django exception reporter/filter; non-OAuth negative tests; Nginx access off and Gunicorn path-only format; runtime log scan pending |
| refresh concurrency / revoke / reauthorization | PASS locally | current file custody dual-process conflict PASS; previous MySQL dual-worker PASS; real platform runs absent |
| audit immutability | PASS regression | live-runtime audit inspection absent |
| fresh/upgrade migration | PASS locally | current SQLite fresh/upgrade; previous MySQL 8.4.10 Sandbox migration not promoted to current SHA |
| backend/frontend/build | PASS | local backend 543/3 skipped; local frontend 163; build 1957 modules |
| Local Sandbox / remote CI | CONDITIONAL | remote CI PASS for Code Review SHA `ea62cc791b599e9e83a68346630a27621d6e2c08` in all three workflows; current-SHA Docker/MySQL and final evidence-head verification pending |
| Shopee official/live flow | FAIL | contract/app/pilot/evidence absent |
| TikTok official/live flow | FAIL | app/pilot/revoke contract/evidence absent |
| DB/log/browser credential scans | FAIL | no fixed live deployment to scan |
| forbidden scope | PASS by code inspection/tests | no order/inventory/finance/webhook/RPA/platform-write implementation added |
| emergency disable | PASS design / NOT RUN | fail-closed switches and network kill switch documented |

## Resilience and consistency

Controlled tests cover 429 Retry-After with caps, 5xx, DNS, timeout and connection reset. TLS uses the default verified CA context. New custody references are revoked after identity/persistence/version failures. If old-reference revocation fails after a new reference is committed, authorization enters controlled `error` and success is not reported. A crash between database commit and external old-reference revoke remains a distributed-saga operational risk until an approved custody contract/reconciliation procedure is independently validated.

## Issues

- P0: none observed in local synthetic evidence.
- P1 closed offline: current Shopee initiate contract; TikTok current seller contract; business-DB-free local custody; local dual-process version conflict; callback Django exception-report/log plus Nginx/Gunicorn/browser-query suppression; Django/migrations/backend/frontend/build/CI guard.
- P1 still open: immutable deployment image/digest; current-SHA MySQL 8.4; approved application/control-plane fields; TikTok platform revoke contract; both real pilot flows and post-live DB/log/browser scans; refresh saga recovery in deployed infrastructure; independent reviewer signatures.
- P2: local backend test key emits an existing short-HMAC warning; outside this task's marketplace scope.

## Capability and production decision

- Shopee: `[x] pending/mock  [ ] pending/live-validation  [ ] connected`
- TikTok Shop: `[x] pending/mock  [ ] pending/live-validation  [ ] connected`
- Production: `[x] NOT APPROVED`; separate rollout review required.
- PR-A3: NOT ALLOWED by this review result.

Architecture, Security, Test, Data and Release reviewer signatures remain blank until all P1 items are closed against one fixed remote SHA and artifact.
