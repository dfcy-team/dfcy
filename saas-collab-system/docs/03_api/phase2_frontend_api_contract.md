# Phase 2 frontend API contract

## Baseline

- Latest `origin/main`: `51535c246b430064b782c4078591253506b16c17`
- Backend merge: PR #5, `feature/phase2-a-api-status-finance`
- Frontend branch: `feature/phase2-b-dashboard-integration`
- Response envelope: `{ success, code, message, data }`
- Mock fallback remains controlled by `VITE_USE_MOCK`.

## Status Rules

- `connected`: backend route exists in latest `main`, frontend API path is aligned, and frontend build passes.
- `pending`: backend route is not available or authenticated runtime verification was not completed.
- `mock`: frontend currently uses mock-only placeholder data.

## Integrations

| Capability | Method | Frontend Path | Backend Source | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| Config list | GET | `/api/internal/integrations/configs/` | `backend/apps/integrations/urls_internal.py` | connected | Does not expose `credential_ciphertext`. |
| Config detail | GET | `/api/internal/integrations/configs/{id}/` | `backend/apps/integrations/urls_internal.py` | connected | Shows masked credential fields only. |
| Sync jobs | GET | `/api/internal/integrations/sync-jobs/` | `backend/apps/integrations/urls_internal.py` | connected | Replaces old Stage0 `sync-tasks`. |
| Sync runs | GET | `/api/internal/integrations/sync-runs/` | `backend/apps/integrations/urls_internal.py` | connected | Replaces old Stage0 `sync-logs`. |
| Sync run detail | GET | `/api/internal/integrations/sync-runs/{id}/` | `backend/apps/integrations/urls_internal.py` | connected | Uses masked error/log fields. |
| Run mock sync | POST | `/api/internal/integrations/sync-jobs/{id}/run-mock/` | `backend/apps/integrations/urls_internal.py` | connected | Mock/sandbox only. |
| Disable sync job | POST | `/api/internal/integrations/sync-jobs/{id}/disable/` | `backend/apps/integrations/urls_internal.py` | connected | No real platform call. |

## Product Status

| Capability | Method | Frontend Path | Backend Source | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| Recommendations | GET | `/api/internal/products/status-recommendations/` | `backend/apps/products/urls.py` | connected | Uses backend `recommended_status` and `status` fields. |
| Recommendation detail | GET | `/api/internal/products/status-recommendations/{id}/` | `backend/apps/products/urls.py` | connected | Shows source snapshot as JSON. |
| Confirm recommendation | POST | `/api/internal/products/status-recommendations/{id}/confirm/` | `backend/apps/products/urls.py` | connected | Shows high-risk confirmation prompt. |
| Reject recommendation | POST | `/api/internal/products/status-recommendations/{id}/reject/` | `backend/apps/products/urls.py` | connected | Backend permission remains authoritative. |
| Status transitions | GET | `/api/internal/products/status-transitions/` | `backend/apps/products/urls.py` | connected | Read-only history. |
| Evaluate mock | POST | `/api/internal/products/status/evaluate-mock/` | `backend/apps/products/urls.py` | connected | Mock evaluation only. |

## Finance Reconciliation

All finance pages only use `/api/finance/*`.

| Capability | Method | Frontend Path | Backend Source | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| Statements | GET | `/api/finance/statements/` | `backend/apps/finance/urls.py` | connected | Read-only list. |
| Withdrawals | GET | `/api/finance/withdrawals/` | `backend/apps/finance/urls.py` | connected | Read-only list. |
| Bank receipts | GET | `/api/finance/bank-receipts/` | `backend/apps/finance/urls.py` | connected | Masked account display only. |
| Reconciliation matches | GET | `/api/finance/reconciliation/matches/` | `backend/apps/finance/urls.py` | connected | Collection endpoint only in Phase 2. |
| Run mock reconciliation | POST | `/api/finance/reconciliation/run-mock/` | `backend/apps/finance/urls.py` | connected | No real bank/payment call. |
| Confirm match | POST | `/api/finance/reconciliation/matches/{id}/confirm/` | `backend/apps/finance/urls.py` | connected | Backend finance permission required. |
| Reject match | POST | `/api/finance/reconciliation/matches/{id}/reject/` | `backend/apps/finance/urls.py` | connected | Backend finance permission required. |
| Exceptions | GET | `/api/finance/reconciliation/exceptions/` | `backend/apps/finance/urls.py` | connected | Read-only list. |

## Supplier Performance

| Capability | Method | Frontend Path | Backend Source | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| Internal performance | GET | `/api/internal/suppliers/performance/` | `backend/apps/suppliers/urls_internal.py` | connected | Internal dashboard only. |
| Internal detail | GET | `/api/internal/suppliers/performance/{supplier_id}/` | `backend/apps/suppliers/urls_internal.py` | connected | Internal page only. |
| Calculate mock | POST | `/api/internal/suppliers/performance/calculate-mock/` | `backend/apps/suppliers/urls_internal.py` | connected | Internal mock calculation. |
| Supplier own performance | GET | `/api/external/supplier/performance/` | `backend/apps/suppliers/urls_external.py` | connected | Supplier page does not pass other `supplier_id`. |
| Supplier own history | GET | `/api/external/supplier/performance/history/` | `backend/apps/suppliers/urls_external.py` | connected | Supplier page does not access internal or finance APIs. |

## RPA Internal Management

| Capability | Method | Frontend Path | Backend Source | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| RPA management task list/detail | GET | `/api/internal/rpa/tasks/` | `backend/apps/rpa/urls_internal.py` | connected | UI-P3 permission and data_scope filtered. |
| RPA runs | GET | `/api/internal/rpa/runs/` | `backend/apps/rpa/urls_internal.py` | connected | Canonical run resource; task/run state is separate. |
| RPA devices | GET | `/api/internal/rpa/devices/` | `backend/apps/rpa/urls_internal.py` | connected | Token and complete fingerprint never returned. |
| Device dry-run | POST | `/api/internal/rpa/devices/{id}/dry-run/` | `backend/apps/rpa/urls_internal.py` | connected | Local audit check only; no browser or platform. |
| Manual queue | GET | `/api/internal/rpa/manual-queue/` | `backend/apps/rpa/urls_internal.py` | connected | Assign/retry requires `rpa.tasks.manage`. |
| Account locks | GET | `/api/internal/rpa/account-locks/` | `backend/apps/rpa/urls_internal.py` | connected | Read-only. |
| Page signatures | GET | `/api/internal/rpa/page-signatures/` | `backend/apps/rpa/urls_internal.py` | connected | Hash is masked. |
| Stability summary | GET | `/api/internal/rpa/stability/` | `backend/apps/rpa/urls_internal.py` | connected | Separate task/run state totals. |

Frontend RPA management pages must not call these Agent execution endpoints:

- `/api/rpa/tasks/claim/`
- `/api/rpa/tasks/{id}/heartbeat/`
- `/api/rpa/tasks/{id}/logs/`
- `/api/rpa/tasks/{id}/screenshots/`
- `/api/rpa/tasks/{id}/complete/`
- `/api/rpa/tasks/{id}/fail/`

## Security Boundary

- No real BigSeller, Shopee, TikTok/TK, bank, or payment integration.
- No real Token, Cookie, Session, API Key, API Secret, account, or password.
- No real supplier, order, finance, bank, or payment data.
- Production access remains disabled or not approved.
