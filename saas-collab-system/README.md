# saas-collab-system

SaaS collaboration system monorepo.

## Project Structure

```text
saas-collab-system/
├── backend/              # Django REST Framework backend
├── frontend/             # Vue 3 + Vite frontend
├── rpa-agent/            # RPA Agent placeholder structure and examples
├── docs/                 # Stage documents and API/RPA notes
├── docker-compose.yml    # Local development services
└── .env.example          # Example environment variables
```

Current stage focuses on the backend foundation plus frontend/RPA placeholders:

- tenant and account models
- role, permission, and data scope models
- RPA task center models and placeholder APIs
- API sync center models and Celery setup
- audit log and attachment models
- internal JWT authentication APIs
- unified response and error handling
- pytest baseline
- Vue 3 frontend foundation with mock pages
- RPA Agent directory and task payload examples

## Backend

See `backend/README.md` for local Python, Docker Compose, MySQL, Redis, Celery, migrations, and pytest commands.

## Frontend

See `frontend/README.md` for dependency installation, Vite development commands, mock mode, environment variables, page directories, and API wrapper notes.

The frontend currently uses mock data and must not assume backend endpoints are already connected.

## RPA Agent

See `rpa-agent/README.md` for RPA Agent directory structure, configuration notes, task payload examples, screenshot/log directories, and safety rules.

The RPA Agent must not connect to MySQL directly and may only communicate with backend endpoints under `/api/rpa/*`.

## Environment

Copy `.env.example` to `.env` for local development and replace every `change-me-*` value. Never commit `.env`.

Production safety:

- Do not expose MySQL or Redis to the public internet.
- Use private networking, firewall rules, and managed secrets in production.
- Do not store real API keys, tokens, passwords, or object storage credentials in source control.
