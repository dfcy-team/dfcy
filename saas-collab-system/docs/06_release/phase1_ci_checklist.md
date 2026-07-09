# Phase 1 CI Checklist

This checklist describes CI or release-gate checks for Phase 1. It is intentionally command-oriented so the same checks can be run locally, in GitHub Actions, or in another CI runner.

## CI Safety Rules

- CI must use generated placeholder environment variables or CI secrets scoped to non-production test resources.
- CI must not use a real `.env`.
- CI must not connect to real BigSeller, Shopee, TikTok, WeChat service accounts, mini programs, banks, or payment providers.
- CI must not print secrets, tokens, cookies, platform credentials, database passwords, or API keys.
- MySQL and Redis are service containers or Docker Compose services only; production exposure is not part of CI.

## Required Tool Versions

- Python: 3.12 recommended.
- Node.js: use the frontend lockfile-compatible version.
- Docker Compose: v2 syntax, invoked as `docker compose`.

## Backend CI Steps

PowerShell:

```powershell
cd saas-collab-system\backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py check
pytest
python manage.py makemigrations --check --dry-run
```

Bash:

```bash
cd saas-collab-system/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python manage.py check
pytest
python manage.py makemigrations --check --dry-run
```

## Docker CI Steps

PowerShell:

```powershell
cd saas-collab-system
docker compose config
docker compose up -d mysql redis
docker compose ps
docker compose down
```

Bash:

```bash
cd saas-collab-system
docker compose config
docker compose up -d mysql redis
docker compose ps
docker compose down
```

## Frontend Build Reference

PowerShell:

```powershell
cd saas-collab-system\frontend
npm install
npm run build
```

Bash:

```bash
cd saas-collab-system/frontend
npm ci
npm run build
```

Frontend build output may produce chunk-size warnings. Warnings should be recorded and handled by frontend tasks when they become blocking.

## RPA JSON Validation

PowerShell:

```powershell
cd saas-collab-system
Get-ChildItem docs\04_rpa\examples,rpa-agent\tasks\examples -Filter *.json -Recurse |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
```

Bash:

```bash
cd saas-collab-system
find docs/04_rpa/examples rpa-agent/tasks/examples -name "*.json" -print0 |
  xargs -0 -I {} python -m json.tool "{}" >/dev/null
```

RPA JSON checks validate schema readability only. They must not run browser automation or connect to real platforms.

## Security Scan

PowerShell:

```powershell
git grep -n -I -E "AKIA|BEGIN (RSA|OPENSSH|PRIVATE) KEY|SECRET_KEY=|PASSWORD=|TOKEN=|API_KEY=|BIGSELLER|SHOPEE|TIKTOK" -- .
git status --short
```

Bash:

```bash
git grep -n -I -E 'AKIA|BEGIN (RSA|OPENSSH|PRIVATE) KEY|SECRET_KEY=|PASSWORD=|TOKEN=|API_KEY=|BIGSELLER|SHOPEE|TIKTOK' -- .
git status --short
```

The scan can match `.env.example` and placeholder docs. CI or reviewer notes must confirm that matches are placeholders only.

## Minimum PASS Criteria

- Backend dependency install succeeds.
- `python manage.py check` passes.
- `pytest` passes.
- `python manage.py makemigrations --check --dry-run` reports no changes.
- `docker compose config` passes.
- `docker compose up -d mysql redis` starts the minimum local services.
- Frontend build command is documented and runnable in frontend-capable CI.
- RPA JSON validation passes.
- Security scan finds no real credentials.
- No real `.env` is present or committed.
- No real platform connection is attempted.
