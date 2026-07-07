# RPA Agent

This directory contains the placeholder structure for the RPA Agent.

Current scope:
- Directory and documentation placeholders only.
- No real browser automation is implemented.
- No real BigSeller account, password, token, or cookie is stored here.

Access rules:
- The RPA Agent must not connect to MySQL directly.
- The RPA Agent may only communicate with backend endpoints under `/api/rpa/*`.
- Business data, task assignment, task status updates, logs, and screenshots must be exchanged through backend APIs.

Future implementation notes:
- Browser automation steps should be added under `bigseller/steps/`.
- Selectors should be documented under `bigseller/selectors/`.
- Example payloads or non-sensitive samples should be placed under `bigseller/examples/`.
