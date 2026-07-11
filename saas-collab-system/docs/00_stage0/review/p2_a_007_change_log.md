# P2-A-007 Change Log

## CI Quality Gates

- Added `.github/workflows/phase2-ci.yml` at the Git repository root.
- Added independent repository safety, backend, frontend build, Docker configuration, and RPA/document jobs.
- Backend CI uses Python 3.12, a temporary SQLite database, placeholder environment values, Django check, migration consistency, migrations, and the full pytest suite.
- Frontend CI uses the committed npm lockfile and runs `npm ci` plus `npm run build` without modifying frontend business code.
- Docker CI validates Compose syntax with process-scoped placeholder values and `/dev/null` instead of a project `.env`; it does not start services.
- RPA CI parses the eight JSON examples, rejects runtime output, and never starts browser automation.
- Document CI requires Phase 2 architecture/test/release documents and P2-A-001 through P2-A-007 change logs.

## Repository Guard

- Added `backend/scripts/ci_guard.py` as a locally reproducible safety gate.
- The guard rejects committed `.env`, private key/certificate files, SQLite databases, RPA screenshots/logs/downloads, and high-confidence credential patterns.
- Findings report only the rule name, file, and line number. Suspected values are never printed.
- Placeholder markers such as `demo`, `example`, `test`, `not-a-real`, and `change-me` remain allowed for tests and examples.

## Local Execution Results

- Repository guard: passed.
- Workflow YAML parse: passed using a temporary local PyYAML installation; no project dependency was added.
- `python manage.py check`: passed, 0 issues.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
- `python manage.py migrate --noinput`: passed against an in-memory temporary SQLite database.
- Full backend `pytest`: passed, 128 tests.
- `npm ci`: passed, 87 packages audited and 0 vulnerabilities reported by npm.
- `npm run build`: passed. The generated JavaScript chunk exceeded 500 kB and was recorded as a non-blocking observation.
- `docker compose config --quiet`: passed with placeholder environment values.
- RPA JSON validation: passed, 8 files parsed.
- Required Phase 2 document check: passed.

## Not Executed

- Remote GitHub Actions has not run yet because this commit has not been pushed. Its status must be recorded after push and cannot be inferred from local checks.
- Docker services were not started because this task requires configuration validation only.
- No deployment, production adapter, real RPA, real platform, bank, payment, or webhook operation was run.

## Security Boundary

- The workflow does not reference or require GitHub Secrets.
- No real `.env`, credential, account, token, API key, database password, order, supplier, financial, screenshot, or bank data was added.
- Tests and CI must remain offline from BigSeller, Shopee, TikTok, banks, payment providers, and other production systems.
- Production adapters remain disabled and CI does not claim that any real platform is connected.
