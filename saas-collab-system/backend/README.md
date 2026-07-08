# Backend

Django REST Framework backend for the SaaS collaboration system.

## Local Python Setup

From the project root:

```powershell
cd saas-collab-system/backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python manage.py check
```

On macOS/Linux, activate with:

```bash
source .venv/bin/activate
```

## Environment Variables

Copy the project-level example file and edit local values:

```powershell
cd saas-collab-system
copy .env.example .env
```

Do not commit `.env`. The example file contains placeholders only.

## Database Migrations

```powershell
cd saas-collab-system/backend
python manage.py makemigrations
python manage.py migrate
```

## Pytest

```powershell
cd saas-collab-system/backend
pytest
```

## Docker Compose

From the project root:

```powershell
cd saas-collab-system
docker compose config
docker compose up -d mysql redis
docker compose ps
```

To start the backend and workers after preparing `.env`:

```powershell
docker compose up -d backend celery celery-beat
```

## MySQL

MySQL 8 is the standard database for this backend. MySQL is the final trusted business data store for tenant, account, permission, RPA task, API sync, audit, attachment, finance, and report data.

Local Docker Compose uses MySQL 8. Development variables are provided in `.env.example`:

- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_ROOT_PASSWORD`

The Django settings currently read the matching `DB_*` variables, which are also included in `.env.example`.

Production safety:

- MySQL must not be exposed to the public internet.
- Use private networking, firewall rules, and managed secrets.
- SQLite is prohibited in staging and production.
- If SQLite is ever used locally, it is only for temporary developer experiments and must not be used for staging, production, demos, shared QA, or trusted business data.

## Redis

Redis is used for Celery broker/result backend:

- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

Docker Compose keeps Redis on the internal Docker network. Production Redis must not be exposed to the public internet.

## Celery

Start a worker locally:

```powershell
cd saas-collab-system/backend
celery -A config worker -l info --pool=solo
```

Start beat locally:

```powershell
cd saas-collab-system/backend
celery -A config beat -l info
```

The `--pool=solo` option is recommended for Windows development.
