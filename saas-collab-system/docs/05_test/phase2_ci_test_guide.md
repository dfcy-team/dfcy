# Phase 2 CI Test Guide

This guide mirrors `.github/workflows/phase2-ci.yml`. It uses only temporary SQLite data and demo/placeholder values. It does not require a real `.env`, platform credential, bank connection, or production service.

## CI Gates

1. Repository guard rejects committed `.env` files, private keys, certificates, SQLite databases, RPA runtime output, and high-confidence credential patterns. Findings show only the rule, file, and line number.
2. Backend gate installs `backend/requirements.txt`, runs Django check, checks migration consistency, applies migrations to temporary SQLite, and runs all pytest tests.
3. Frontend gate runs `npm ci` and `npm run build` without changing frontend source. Chunk-size warnings are observations unless the build command fails.
4. Docker gate runs `docker compose config --quiet` with placeholder process variables and `/dev/null` as the environment file. It does not start services.
5. RPA and documentation gate parses JSON examples, rejects runtime screenshots/logs/downloads, and verifies Phase 2 documents and P2-A change logs.

## Bash Reproduction

Run from the Git repository root:

```bash
python saas-collab-system/backend/scripts/ci_guard.py --root .

cd saas-collab-system/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=config.settings.dev
export DJANGO_SECRET_KEY=phase2-local-placeholder-secret
export DJANGO_DEBUG=false
export DB_ENGINE=django.db.backends.sqlite3
export DB_NAME=/tmp/phase2-local.sqlite3
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python -m pytest -q

cd ../frontend
npm ci
npm run build

cd ..
find rpa-agent/tasks/examples -name '*.json' -print0 | xargs -0 -r -n 1 python -m json.tool >/dev/null

export DB_NAME=phase2_ci_demo
export DB_USER=phase2_ci_demo
export DB_PASSWORD=phase2-local-placeholder-password
export MYSQL_ROOT_PASSWORD=phase2-local-placeholder-root-password
export DB_HOST=mysql
export DB_PORT=3306
docker compose --env-file /dev/null config --quiet
```

Remove the temporary SQLite database after the local run. Do not add it to Git.

## Windows PowerShell Reproduction

Run from the Git repository root:

```powershell
py -3 saas-collab-system\backend\scripts\ci_guard.py --root .

Set-Location saas-collab-system\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:DJANGO_SETTINGS_MODULE = "config.settings.dev"
$env:DJANGO_SECRET_KEY = "phase2-local-placeholder-secret"
$env:DJANGO_DEBUG = "false"
$env:DB_ENGINE = "django.db.backends.sqlite3"
$env:DB_NAME = Join-Path $env:TEMP "phase2-local.sqlite3"
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python -m pytest -q

Set-Location ..\frontend
npm ci
npm run build

Set-Location ..
Get-ChildItem rpa-agent\tasks\examples -Filter *.json -Recurse |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }

$env:DB_NAME = "phase2_ci_demo"
$env:DB_USER = "phase2_ci_demo"
$env:DB_PASSWORD = "phase2-local-placeholder-password"
$env:MYSQL_ROOT_PASSWORD = "phase2-local-placeholder-root-password"
$env:DB_HOST = "mysql"
$env:DB_PORT = "3306"
docker compose config --quiet
```

Delete `$env:TEMP\phase2-local.sqlite3` after the run. No command in this guide runs real RPA, calls a real platform, or starts production services.

## Expected Result

Every job must pass before release review. A frontend chunk warning may be recorded as a non-blocking observation, but dependency, build, security, Django, migration, pytest, Docker syntax, RPA JSON, or document failures block the gate.
