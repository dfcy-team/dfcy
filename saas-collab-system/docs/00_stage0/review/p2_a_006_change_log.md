# P2-A-006 Change Log

## Scope

- Added `RPATaskAttempt` for bounded attempts, heartbeat timestamps, failed steps, last successful steps, masked errors, and manual takeover state.
- Added `RPAEvidence` for demo/example screenshot metadata and payload hashes.
- Added `RPAAccountLock` for tenant-scoped serialization of tasks using the same platform and account alias.
- Added `RPAPageSignature` for detecting mock page structure changes.
- Added centralized stability services for state transitions, account lock lifecycle, heartbeat timeout handling, evidence validation, retry limits, and page signatures.

## Protocol Compatibility

- Preserved the existing claim, heartbeat, logs, screenshots, complete, and fail paths and response envelope.
- Preserved protocol status names. Existing `success` represents completed execution and `retrying` represents retry wait.
- Claim creates a numbered attempt and acquires an account lock only when payload contains both `platform` and `account_alias`.
- Heartbeat refreshes the current attempt and lock lease. A timeout or changed page signature moves the task to `manual_required`; execution is not silently resumed.
- Complete and fail only store execution results and do not update business approval decisions.

## Security And Boundaries

- RPA ownership checks remain tied to the authenticated user's `RPAAgent` record and the task's `claimed_by` agent.
- Logs, errors, result text, and claim payloads are recursively masked for credential-like fields.
- Evidence accepts only demo/example/local-placeholder references; external or real local screenshot references are rejected.
- Account locks, attempts, evidence, signatures, and task operations are tenant scoped.
- No real selector, browser automation, BigSeller connection, platform credential, screenshot, finance operation, or business approval logic was added.
- `docs/04_rpa/rpa_api_protocol.md` was read for compatibility and was not modified.

## Verification

- `python manage.py check`: passed, 0 issues.
- `pytest tests/test_rpa_models_api.py tests/test_phase2_rpa_stability.py`: passed, 24 tests.
- Full backend `pytest`: passed, 128 tests.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
