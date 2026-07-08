# Stage 0 File Scope

## Project Root

The project root is `saas-collab-system/`. All project files must be created under this directory.

No project files may be created outside `saas-collab-system/`.

## Developer A Scope

Developer A may mainly modify:

- `backend/`
- `docker-compose.yml`
- `.env.example`
- `README.md`

Developer A must not modify frontend business code, RPA Agent business code, or unrelated documentation unless explicitly assigned.

## Developer B Scope

Developer B may mainly modify:

- `frontend/`
- `rpa-agent/`
- `docs/04_rpa/`
- `docs/00_stage0/`

Developer B must not modify backend business code unless explicitly assigned.

## Architect Scope

Architects may mainly modify:

- `docs/00_stage0/`
- `docs/01_architecture/`
- `docs/02_database/`
- `docs/03_api/`
- `docs/04_rpa/`
- `docs/05_test/`
- `docs/06_release/`
- root-level planning notes in `README.md`

Architects should not directly change Developer A or Developer B business code unless the task explicitly requires it.

## Prohibited Actions

- Do not create project files outside `saas-collab-system/`.
- Do not commit real secrets, tokens, account credentials, passwords, private keys, or production environment files.
- Do not allow RPA components to connect directly to the database.
- Do not let the frontend perform real permission decisions. Permission enforcement must be handled by the backend.
- Stage 0 work may only include foundation setup, directory structure, documentation, mocks, and placeholders.
- Stage 0 work must not connect to real external platforms.

## Directory Usage

- `backend/`: backend services, API implementations, authentication, permissions, database models, migrations, and backend tests.
- `frontend/`: frontend application code, UI pages, components, routes, state management, and frontend mocks.
- `rpa-agent/`: RPA Agent runtime code, local automation adapters, mock executors, and agent-side integration scaffolding.
- `docs/00_stage0/`: Stage 0 scope rules, review reports, rectification tasks, and baseline governance documents.
- `docs/00_stage0/review/`: Stage 0 audit reports and rectification tracking documents.
- `docs/01_architecture/`: system architecture, module boundaries, deployment topology, and integration principles.
- `docs/02_database/`: database design, schema notes, data model reviews, and migration planning.
- `docs/03_api/`: API specifications, route planning, request and response contracts, and mock API documents.
- `docs/04_rpa/`: RPA design, task flow, agent protocol, execution constraints, and RPA examples.
- `docs/04_rpa/examples/`: RPA examples, sample payloads, and mock execution documents.
- `docs/05_test/`: test strategy, test plans, acceptance criteria, and regression checklists.
- `docs/06_release/`: release notes, deployment plans, rollback plans, and release checklists.
