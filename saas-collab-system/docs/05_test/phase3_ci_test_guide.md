# Phase 3 CI Test Guide

This guide mirrors `.github/workflows/phase3-ci.yml`. All commands use temporary databases and demo or placeholder configuration. They do not require a project `.env`, GitHub Secrets, platform credentials, real business data, or internet access to production platforms.

## Blocking Gates

1. Repository safety rejects committed `.env`, private keys, certificates, SQLite databases, RPA runtime output, and high-confidence credential patterns. It prints only the rule and source location.
2. Backend setup runs Django check, migration drift detection, temporary SQLite migrations, and permission catalog validation.
3. Phase 3 focused tests cover analytics, inventory alerts, replenishment, lifecycle, business alerts, config center, reports, finance analytics, and persisted data quality.
4. `check_phase3_data_quality` rejects missing tenants, invalid metric dimensions, metric version conflicts, duplicate alert keys, expired active recommendations, illegal lifecycle transitions, sensitive output, and exports without request audit records.
5. The full pytest suite remains blocking, so Phase 1 and Phase 2 behavior is also protected.
6. Frontend dependencies are installed with `npm ci --ignore-scripts`; CI does not approve dependency lifecycle scripts. The explicit application build must pass.
7. Docker Compose is parsed with placeholder environment values and without loading the project `.env`. Services are not started.
8. RPA JSON is parsed and required documents are checked. RPA browser automation never runs.

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
export DJANGO_SECRET_KEY=phase3-local-placeholder-secret
export DJANGO_DEBUG=false
export DB_ENGINE=django.db.backends.sqlite3
export DB_NAME=/tmp/phase3-local.sqlite3
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py sync_permissions --check
python -m pytest -q tests/test_phase3_*.py
python manage.py check_phase3_data_quality
python -m pytest -q

cd ../frontend
npm ci --ignore-scripts
npm run build

cd ..
find rpa-agent/tasks/examples -name '*.json' -print0 | xargs -0 -r -n 1 python -m json.tool >/dev/null

export DB_NAME=phase3_ci_demo
export DB_USER=phase3_ci_demo
export DB_PASSWORD=phase3-local-placeholder-password
export MYSQL_ROOT_PASSWORD=phase3-local-placeholder-root-password
export DB_HOST=mysql
export DB_PORT=3306
docker compose --env-file /dev/null config --quiet
```

Delete `/tmp/phase3-local.sqlite3` after the run.

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
$env:DJANGO_SECRET_KEY = "phase3-local-placeholder-secret"
$env:DJANGO_DEBUG = "false"
$env:DB_ENGINE = "django.db.backends.sqlite3"
$env:DB_NAME = Join-Path $env:TEMP "phase3-local.sqlite3"
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py sync_permissions --check
python -m pytest -q tests/test_phase3_*.py
python manage.py check_phase3_data_quality
python -m pytest -q

Set-Location ..\frontend
npm ci --ignore-scripts
npm run build

Set-Location ..
Get-ChildItem rpa-agent\tasks\examples -Filter *.json -Recurse |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }

$env:DB_NAME = "phase3_ci_demo"
$env:DB_USER = "phase3_ci_demo"
$env:DB_PASSWORD = "phase3-local-placeholder-password"
$env:MYSQL_ROOT_PASSWORD = "phase3-local-placeholder-root-password"
$env:DB_HOST = "mysql"
$env:DB_PORT = "3306"
docker compose config --quiet
```

Delete `$env:TEMP\phase3-local.sqlite3` after the run. None of these commands calls BigSeller, Shopee, TikTok/TK, a bank, a payment provider, or a real RPA process.

## Data Quality Operation

`check_phase3_data_quality` exits non-zero when a finding exists. Its output contains a check name, count, and generic explanation only; record payloads and suspected secrets are never printed. Run it against the release candidate database after backup and before release approval. An empty temporary CI database proves command and schema compatibility, while the focused pytest suites exercise the corresponding validation and failure paths with demo records.
