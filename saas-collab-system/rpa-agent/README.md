# RPA Agent

This directory contains the placeholder structure for the RPA Agent.

## Directory Structure

```text
rpa-agent/
├── agents/              # Agent registration/runtime placeholders
├── bigseller/           # BigSeller RPA notes and future automation structure
│   ├── steps/           # Future browser step definitions
│   ├── selectors/       # Future selector documentation
│   └── examples/        # Non-sensitive examples
├── tasks/               # Task payload examples and task notes
│   └── examples/        # Mock task payload/result JSON files
├── screenshots/         # Runtime screenshot output placeholder
├── logs/                # Runtime log output placeholder
├── config/              # Configuration notes
├── README.md
└── .env.example
```

Current scope:

- Directory and documentation placeholders only.
- No real browser automation is implemented.
- No real BigSeller account, password, token, or cookie is stored here.

## Configuration

Use `.env.example` as the local configuration template:

```text
RPA_AGENT_NAME=local-rpa-agent
RPA_AGENT_TOKEN=YOUR_RPA_AGENT_TOKEN_HERE
RPA_API_BASE_URL=http://localhost:8000/api/rpa
BIGSELLER_LOGIN_URL=https://example.com/login
HEADLESS=true
```

Rules:

- Use only placeholder values in committed examples.
- Store real runtime values outside the repository.
- Do not commit real tokens, passwords, cookies, or account data.

## Task Payloads

Mock task payload and result examples live in:

```text
rpa-agent/tasks/examples/
```

These files describe expected task shapes for:

- `BIGSELLER_CREATE_PRODUCT`
- `BIGSELLER_UPLOAD_IMAGES`
- `BIGSELLER_MULTI_SITE_LISTING`
- `BIGSELLER_UPDATE_PRICE`
- `BIGSELLER_READ_PAGE_PRICE`
- `BIGSELLER_COLLECT_LISTING_STATUS`

They are examples only and must not contain real products, stores, accounts, or customer data.

## Screenshots

Runtime screenshots should be written under:

```text
rpa-agent/screenshots/
```

Do not commit screenshots that contain real account data, private business data, customer data, or platform secrets.

## Logs

Runtime logs should be written under:

```text
rpa-agent/logs/
```

Logs must not contain passwords, tokens, cookies, verification codes, or other sensitive credentials.

## Access Rules

- The RPA Agent must not connect to MySQL directly.
- The RPA Agent may only communicate with backend endpoints under `/api/rpa/*`.
- Business data, task assignment, task status updates, logs, and screenshots must be exchanged through backend APIs.
- BigSeller browser automation should be implemented only after task contracts and selector placeholders are reviewed.

## BigSeller Account Safety

Never write real BigSeller accounts, passwords, cookies, tokens, store private data, or verification codes into this repository.
