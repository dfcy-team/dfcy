# A-REAL-PLATFORM-CONNECTION REVIEW

Review date: 2026-08-07. Current result: **FAIL / REQUEST CHANGES**. This is a developer pre-review, not reviewer approval.

## Evidence identity

| Field | Value |
|---|---|
| Repository | `dfcy-team/dfcy` |
| PR | Draft #42 — `https://github.com/dfcy-team/dfcy/pull/42` |
| Branch | `feature/module-a-real-platform-connection` |
| Base | `feature/module-a-marketplace-oauth` @ `5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0` |
| Head / Review SHA | Freeze from PR #42 remote head after this evidence update |
| Commit count / changed files | PENDING commit |
| Runtime artifact / image digest | NOT AVAILABLE |
| Environment | local development only |
| Database | SQLite local; MySQL 8.4 NOT VERIFIED |
| Migration head | `integrations.0013_authorization_reauthorization_bindings` |

PR-A1 architecture/security R2 recorded PASS for its fixed scope. PR-A2 review recorded architecture/security/testing PASS for synthetic scope, with repository-hygiene and CI observations. Neither conclusion proves live connectivity.

## Review matrix

| Area | Result | Evidence / blocker |
|---|---|---|
| PR-A2 state/replay/context baseline | PASS locally | A2 + focused regressions |
| exact permissions and tenant/store isolation | PASS locally | included in 527-test backend suite |
| callback forbids token/tenant/user/internal store | PASS locally | negative tests |
| synthetic/live separation and default fail closed | PASS locally | live gate tests; no connected override |
| custody architecture | CONDITIONAL | HTTP custody reference only; approved provider/runtime absent |
| outbound allowlist/TLS/timeouts/retries | PASS in controlled tests | real egress not tested |
| callback query log suppression | PASS config test | runtime Django/container/error-report scans absent |
| refresh concurrency / revoke / reauthorization | PASS on SQLite mechanisms | MySQL dual-worker and live platform runs absent |
| audit immutability | PASS regression | live-runtime audit inspection absent |
| fresh/upgrade migration | PASS SQLite | MySQL 8.4 absent |
| backend/frontend/build | PASS | 527/2 skipped; 160; build success |
| Local Sandbox / remote CI | FAIL | Docker unavailable; final remote CI not yet verified |
| Shopee official/live flow | FAIL | contract/app/pilot/evidence absent |
| TikTok official/live flow | FAIL | app/pilot/revoke contract/evidence absent |
| DB/log/browser credential scans | FAIL | no fixed live deployment to scan |
| forbidden scope | PASS by code inspection/tests | no order/inventory/finance/webhook/RPA/platform-write implementation added |
| emergency disable | PASS design / NOT RUN | fail-closed switches and network kill switch documented |

## Resilience and consistency

Controlled tests cover 429 Retry-After with caps, 5xx, DNS, timeout and connection reset. TLS uses the default verified CA context. New custody references are revoked after identity/persistence/version failures. If old-reference revocation fails after a new reference is committed, authorization enters controlled `error` and success is not reported. A crash between database commit and external old-reference revoke remains a distributed-saga operational risk until an approved custody contract/reconciliation procedure is independently validated.

## Issues

- P0: none observed in local synthetic evidence.
- P1: no fixed Head/Review SHA or immutable artifact; dirty workspace; MySQL 8.4 and dual-worker test absent; Sandbox and remote CI absent; approved custody/runtime absent; Shopee contract absent; TikTok revoke contract absent; both real pilot flows and post-flow DB/log/browser scans absent; refresh saga recovery not validated in deployed infrastructure.
- P2: local backend test key emits an existing short-HMAC warning; outside this task's marketplace scope.

## Capability and production decision

- Shopee: `[x] pending/mock  [ ] pending/live-validation  [ ] connected`
- TikTok Shop: `[x] pending/mock  [ ] pending/live-validation  [ ] connected`
- Production: `[x] NOT APPROVED`; separate rollout review required.
- PR-A3: NOT ALLOWED by this review result.

Architecture, Security, Test and Release reviewer signatures remain blank until all P1 items are closed against one fixed remote SHA and artifact.
