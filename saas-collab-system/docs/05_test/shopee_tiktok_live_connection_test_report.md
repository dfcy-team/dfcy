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
| Head / Review SHA | Freeze from PR #42 remote head after this evidence update |
| Deployment artifact / image digest | NOT AVAILABLE |
| Database / migration head | local SQLite / `integrations.0013_authorization_reauthorization_bindings` |
| Environment | local development only; not valid live evidence |

## Local engineering evidence

| Check | Result |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS, 0 issues |
| migration drift | PASS, no changes |
| fresh SQLite migration | PASS through `0013` |
| upgrade SQLite migration | PASS, `0012 -> 0013` |
| focused OAuth/live tests | PASS, 76 passed / 1 MySQL-only skipped |
| full backend | PASS, 527 passed / 2 skipped |
| frontend | PASS, 160 passed |
| production build | PASS, 1955 modules |
| MySQL 8.4 / dual-worker refresh | NOT RUN — Docker engine unavailable |
| Local Sandbox integration | NOT RUN — Docker engine unavailable |
| remote CI | PENDING — rerun/verify against final PR #42 remote head |

Automated fake-transport tests cover fail-closed gates, synthetic/live separation, exact redirect, forbidden callback context, TikTok code exchange/authorized-shop/minimal metadata contract, custody references, cleanup after persistence/identity failure, reauthorization, version conflict, old-reference revoke failure, bounded 429/5xx/DNS/timeout/reset handling, and Nginx callback access-log suppression. They are not real-platform evidence.

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
- Result: `FAIL / REQUEST CHANGES` until fixed remote SHA/artifact, MySQL, Sandbox, CI, custody, official applications/contracts, live pilots and independent review all pass.
