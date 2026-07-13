# Phase 3 CI Release Gate

Phase 3 is eligible for architecture review or merge only when `Phase 3 CI and Data Quality Gates` passes on the exact candidate commit.

## Required Gates

| Gate | Blocking condition |
|---|---|
| Repository safety | A committed `.env`, private key/certificate, SQLite database, RPA runtime artifact, or high-confidence credential pattern is found |
| Django | System check, migration consistency, temporary migration, or permission catalog validation fails |
| Phase 3 focused tests | Any analytics, inventory alert, replenishment, lifecycle, business alert, config center, report, finance analytics, or data-quality test fails |
| Persisted data quality | Missing tenant, invalid dimension, metric version conflict, duplicate alert, expired active recommendation, illegal lifecycle transition, sensitive leakage, or unaudited export is found |
| Regression suite | Any full pytest test fails |
| Frontend observation | Locked dependency install with lifecycle scripts disabled, or the explicit frontend build, fails |
| Docker | Placeholder-only `docker compose config --quiet` fails |
| RPA and documents | JSON parsing, runtime artifact rejection, or required Phase 3 document/change-log checks fail |

## Security And Automation Boundary

- The workflow uses temporary SQLite and explicit placeholder environment values. It requires no real GitHub Secret.
- It does not access BigSeller, Shopee, TikTok/TK, banks, payment providers, or production services.
- It does not start Docker services, execute RPA, approve npm lifecycle scripts, deploy code, create purchase orders, modify product status, or perform financial actions.
- Scanner and data-quality output never includes complete suspected credentials or business payloads.
- Reports remain placeholder exports; a release candidate with an export lacking a request audit record is blocked.

## Release Decision

All jobs must be green for the proposed commit. Local results support diagnosis but do not replace GitHub Actions. Any skipped or unavailable check must be recorded with its reason and approved by architecture and security reviewers before merge. A detected real credential must be revoked outside the repository before development continues.
