# saas-collab-system

SaaS collaboration system monorepo.

## Project Structure

```text
saas-collab-system/
├── backend/              # Django REST Framework backend
├── docker-compose.yml    # Local development services
└── .env.example          # Example environment variables
```

Current stage focuses on the backend foundation:

- tenant and account models
- role, permission, and data scope models
- RPA task center models and placeholder APIs
- API sync center models and Celery setup
- audit log and attachment models
- internal JWT authentication APIs
- unified response and error handling
- pytest baseline

## Backend

See `backend/README.md` for local Python, Docker Compose, MySQL, Redis, Celery, migrations, and pytest commands.

## Environment

Copy `.env.example` to `.env` for local development and replace every `change-me-*` value. Never commit `.env`.

Production safety:

- Do not expose MySQL or Redis to the public internet.
- Use private networking, firewall rules, and managed secrets in production.
- Do not store real API keys, tokens, passwords, or object storage credentials in source control.
