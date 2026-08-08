# Shopee / TikTok Shop live connection test report

Task: `A-REAL-PLATFORM-CONNECTION`; date: 2026-08-07. This report contains no real credentials or complete platform subject identifiers.

## Frozen evidence

| Field | Value |
|---|---|
| Repository | `dfcy-team/dfcy` |
| Branch | `feature/module-a-real-platform-connection` |
| Base branch | `feature/module-a-marketplace-oauth` |
| Base SHA | `5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0` |
| PR | Draft #42 — `https://github.com/dfcy-team/dfcy/pull/42` |
| Code Review SHA | `bcb3281774f5166cf14e0d7346f43095ffa46b21` |
| Final PR Head SHA | Freeze from PR #42 after this evidence-only commit |
| Deployment artifact / image digest | NOT AVAILABLE |
| Database / migration head | MySQL 8.4.10 Local Sandbox / `integrations.0013_authorization_reauthorization_bindings` |
| Environment | Local Sandbox with real-platform switches OFF; not valid live evidence |

## Local engineering evidence

| Check | Result |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS, 0 issues |
| migration drift | PASS, no changes |
| fresh SQLite migration | PASS through `0013` |
| upgrade SQLite migration | PASS, `0012 -> 0013` |
| focused OAuth/live tests | PASS, 22 passed locally |
| full backend (local SQLite) | PASS, 528 passed / 3 MySQL-only skipped |
| frontend | PASS, 163 passed |
| production build | PASS, 1957 modules |
| MySQL 8.4.10 / live dual-worker refresh | PASS, one commit and one controlled conflict |
| Local Sandbox integration | PASS, backend 530 / frontend 160 / build 1955 modules |
| Sandbox DB/log raw scan | PASS, 0 findings; authorization rows were 0 |
| remote CI | PENDING — must pass against final PR #42 head |

Automated fake-transport tests cover fail-closed gates, synthetic/live separation, exact redirect, forbidden callback context, TikTok code exchange/authorized-shop/minimal metadata contract, custody references, cleanup after persistence/identity failure, reauthorization, version conflict, old-reference revoke failure, bounded 429/5xx/DNS/timeout/reset handling, and Nginx callback access-log suppression. They are not real-platform evidence.

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
- Result: `FAIL / REQUEST CHANGES` until immutable artifact, final CI, custody, official applications/contracts, live pilots, post-live scans and independent review all pass.

## Pre-live local wiring verification (2026-08-08)

This section records engineering readiness only and contains no raw credential or complete application/store identifier.

| Check | Result |
|---|---|
| Django check / migration drift | PASS |
| Backend full suite | PASS, 543 passed / 3 skipped |
| Frontend full suite | PASS, 165 passed |
| Frontend production build | PASS, 1963 modules |
| CI guard / forbidden artifact scan | PASS |
| Integration-config to live-provider binding | PASS, automated tests |
| Exact region / callback / scope binding | PASS, automated tests |
| File custody live gate | PASS, automated tests; real credential not yet written |
| Shopee approved app status / redirect domain | Read-only operator-console check PASS; identifiers omitted |
| TikTok Non-US operator login | Operator-confirmed; app configuration not yet verified |
| Real OAuth and post-flow scans | NOT RUN |

Capability remains `pending/mock` until the fixed commit is running and all required live scenarios and scans pass.
