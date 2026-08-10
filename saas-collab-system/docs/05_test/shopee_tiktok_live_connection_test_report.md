# Shopee / TikTok Shop live connection test report

Task: `A-REAL-PLATFORM-CONNECTION`; updated: 2026-08-10. This report contains no real credentials or complete platform subject identifiers.

## Frozen evidence

| Field | Value |
|---|---|
| Repository | `dfcy-team/dfcy` |
| Branch | `feature/module-a-real-platform-connection` |
| Base branch | `feature/module-a-marketplace-oauth` |
| Base SHA | `5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0` |
| PR | Draft #42 — `https://github.com/dfcy-team/dfcy/pull/42` |
| Code Review SHA | `c3307626affdae78c14db66dc19ad7c65744ae39` |
| Final PR Head SHA | Freeze from PR #42 after this evidence-only commit |
| Source artifact | `a-real-platform-c3307626.zip`, SHA-256 `962cfe48451856d09b3a633fb195057037137d7eafb60e67a23b44a7b088f2f0`, 1,580,387 bytes |
| Deployment image digest | NOT AVAILABLE — Docker daemon timed out; must be built after remote SHA freeze |
| Database / migration head | Previous MySQL 8.4.10 Sandbox; current SQLite verified / `integrations.0013_authorization_reauthorization_bindings` |
| Environment | Local Sandbox with real-platform switches OFF; not valid live evidence |

## Local engineering evidence

| Check | Result |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS, 0 issues |
| migration drift | PASS, no changes |
| fresh SQLite migration | PASS through `0013` |
| upgrade SQLite migration | PASS, `0012 -> 0013` |
| focused OAuth/live/custody tests | PASS, 34 passed locally |
| local file custody dual-process rotation | PASS, one version-2 commit and one controlled conflict |
| full backend (local SQLite) | PASS, 539 passed / 3 MySQL-only skipped |
| frontend | PASS, 163 passed |
| production build | PASS, 1957 modules |
| MySQL 8.4.10 / live-reference dual-worker refresh | Previous fixed-Sandbox PASS; NOT RERUN at current SHA because Docker daemon timed out |
| Local Sandbox integration | PASS, backend 530 / frontend 160 / build 1955 modules |
| Sandbox DB/log raw scan | PASS, 0 findings; authorization rows were 0 |
| Docker Compose static config | PASS |
| CI guard / forbidden artifact scan | PASS, 0 findings |
| remote CI | PENDING — must pass against final PR #42 head |

Automated fake-transport tests cover fail-closed gates, synthetic/live separation, current Shopee/TikTok authorization parameters, exact callback/result redirect allowlists, forbidden callback context, TikTok code exchange/authorized-shop/minimal metadata contract, HTTP/local-file custody references, cleanup after persistence/identity failure, local custody dual-process rotation, reauthorization, version conflict, old-reference revoke failure, bounded 429/5xx/DNS/timeout/reset handling, and Nginx/Gunicorn callback query suppression. They are not real-platform evidence.

The callback response now immediately redirects a controlled live result to a query-free approved page and returns only `oauth`, `platform` and, on failure, a controlled error code. `Cache-Control: no-store` and `Referrer-Policy: no-referrer` are enforced. Tests assert that authorization code and state do not enter the redirect location or response body.

The SaaS pilot deployment template now records separate Shopee/TikTok callback URLs for `dingfengchuangyu.com`, Shopee pilot regions `PH/TH/MY`, and TikTok market `ROW`. Both live gates and both contract approvals remain disabled, and only custody reference placeholders are permitted. A read-only private-host probe found the project HTTP/HTTPS pilot ports reachable and the database port unreachable from the operator workstation; TLS/application health and deployment identity were not proven, so this is not deployment or live-connection evidence.

## Real platform matrix

| Scenario | Shopee | TikTok Shop |
|---|---|---|
| Approved application/contract | BLOCKED | BLOCKED |
| OAuth / callback | NOT RUN | NOT RUN |
| custody reference | NOT RUN | NOT RUN |
| authorized shop / shop_cipher | NOT RUN | NOT RUN |
| minimal read API | NOT RUN | NOT RUN |
| refresh / concurrency | NOT RUN | NOT RUN |
| revoke / reauthorization | NOT RUN | NOT RUN |
| DB/log/browser raw credential scans after live flow | NOT RUN | NOT RUN |

## Decision

- Shopee: `pending/mock`.
- TikTok Shop: `pending/mock`.
- Production synchronization: OFF / NOT APPROVED.
- Offline-remediable P1 result: PASS for current contract construction, local custody, callback query suppression, bounded networking and local regression.
- Overall result: `FAIL / REQUEST CHANGES` until immutable artifact/current-SHA MySQL+CI, official applications, live pilots, post-live scans and independent review all pass.
