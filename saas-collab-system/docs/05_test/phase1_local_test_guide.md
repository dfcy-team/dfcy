# Phase 1 Local Test Guide

This guide defines reproducible local checks for Phase 1 backend development. It uses placeholder environment values only and must not connect to real platforms.

## Safety Rules

- Do not use a real `.env` from production or staging.
- Do not commit `.env`, real passwords, real tokens, real API keys, real platform accounts, or real screenshots.
- Do not connect to real BigSeller, Shopee, TikTok, WeChat service accounts, mini programs, banks, or payment providers.
- MySQL and Redis are for local Docker development only and must not be exposed to the public internet in production.

## Recommended Versions

- Python: 3.12 is recommended for local and CI reproducibility.
- Node.js: use the version required by `frontend/package.json` and lockfile.
- Docker Desktop: current stable version with Docker Compose v2.

## Windows PowerShell

Run from the repository root that contains the inner `saas-collab-system/` directory:

```powershell
cd saas-collab-system
```

Prepare a local backend environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run Django checks and tests:

```powershell
python manage.py check
pytest
pytest tests/test_rpa_models_api.py
pytest tests/test_products_api.py
pytest tests/test_purchasing_suppliers_api.py
python manage.py makemigrations --check --dry-run
```

Validate Docker Compose and start only the minimum local services:

```powershell
cd ..
docker compose config
docker compose up -d mysql redis
docker compose ps
```

Stop local services:

```powershell
docker compose down
```

Frontend build reference:

```powershell
cd frontend
npm install
npm run build
```

RPA JSON validation reference:

```powershell
cd ..
Get-ChildItem docs\04_rpa\examples,rpa-agent\tasks\examples -Filter *.json -Recurse |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
```

Basic safety scan:

```powershell
git grep -n -I -E "AKIA|BEGIN (RSA|OPENSSH|PRIVATE) KEY|SECRET_KEY=|PASSWORD=|TOKEN=|API_KEY=|BIGSELLER|SHOPEE|TIKTOK" -- .
git status --short
```

The scan can match placeholder examples. Confirm matches are placeholders only and never real credentials.

## Bash

Run from the repository root that contains the inner `saas-collab-system/` directory:

```bash
cd saas-collab-system
```

Prepare a local backend environment:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Run Django checks and tests:

```bash
python manage.py check
pytest
pytest tests/test_rpa_models_api.py
pytest tests/test_products_api.py
pytest tests/test_purchasing_suppliers_api.py
python manage.py makemigrations --check --dry-run
```

Validate Docker Compose and start only the minimum local services:

```bash
cd ..
docker compose config
docker compose up -d mysql redis
docker compose ps
```

Stop local services:

```bash
docker compose down
```

Frontend build reference:

```bash
cd frontend
npm ci
npm run build
```

RPA JSON validation reference:

```bash
cd ..
find docs/04_rpa/examples rpa-agent/tasks/examples -name "*.json" -print0 |
  xargs -0 -I {} python -m json.tool "{}" >/dev/null
```

Basic safety scan:

```bash
git grep -n -I -E 'AKIA|BEGIN (RSA|OPENSSH|PRIVATE) KEY|SECRET_KEY=|PASSWORD=|TOKEN=|API_KEY=|BIGSELLER|SHOPEE|TIKTOK' -- .
git status --short
```

The scan can match placeholder examples. Confirm matches are placeholders only and never real credentials.

## Expected Phase 1 Backend Results

The backend checks should pass before a Phase 1 backend task is committed:

- `python manage.py check`
- `pytest`
- `python manage.py makemigrations --check --dry-run`

Docker checks should at least prove that Compose syntax is valid and local MySQL/Redis can start:

- `docker compose config`
- `docker compose up -d mysql redis`
- `docker compose ps`

Frontend and RPA commands are references for cross-team reproducibility. They must continue to avoid real platform access.
