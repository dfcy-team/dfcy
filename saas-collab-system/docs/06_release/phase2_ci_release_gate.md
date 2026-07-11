# Phase 2 CI Release Gate

Phase 2 is eligible for merge or release review only when the `Phase 2 CI Quality Gates` workflow passes on the candidate commit.

## Required Gates

| Gate | Blocking criteria |
|---|---|
| Repository safety | No committed `.env`, private key/certificate, SQLite database, RPA runtime output, or high-confidence credential pattern |
| Backend | Dependency install, Django check, migration consistency, temporary SQLite migration, and full pytest suite pass |
| Frontend | Locked dependency install and production build pass; chunk warnings are recorded observations |
| Docker | `docker compose config --quiet` passes with placeholder values and no project `.env` |
| RPA | JSON examples parse and no screenshots, logs, downloads, or browser automation execute in CI |
| Documents | Phase 2 architecture/test/release documents and P2-A-001 through P2-A-007 change logs exist |

## Security Boundary

- CI uses repository-defined placeholder environment values only. No GitHub Secret is required by this workflow.
- Production adapters remain disabled and tests must not access BigSeller, Shopee, TikTok, banks, payment providers, or other production systems.
- CI does not start Docker services, deploy production code, run RPA browser automation, or perform financial operations.
- Scanner output never includes the suspected value. It reports only a rule name and source location.
- A real credential discovered during review must be revoked outside this repository before the commit can proceed.

## Release Decision

All blocking gates must be green on the exact commit proposed for merge. Remote GitHub Actions execution must be recorded after push; local equivalents do not replace the remote status. Any intentionally skipped check requires a written reason and architecture/security approval before release.
