# P2-B-R1-001 API integration change log

## 1. Latest main hash

- Latest `origin/main`: `51535c246b430064b782c4078591253506b16c17`
- Merge result: latest `origin/main` was merged into `feature/phase2-b-dashboard-integration` with no conflicts.
- Previous remote branch HEAD before R1: `521c065`

## 2. Development A backend API version

- Backend merge on `main`: PR #5 from `feature/phase2-a-api-status-finance`
- Relevant backend commits now included:
  - `6c37704 P2-A-001 add secure integration configuration models`
  - `a5569e7 P2-A-002 add mock API synchronization framework`
  - `38dc33d P2-A-003 add product status state machine`
  - `169430f P2-A-004 add finance reconciliation foundation`
  - `cddaf69 P2-A-005 add supplier performance statistics`
  - `3458021 P2-A-006 enhance RPA task stability controls`
  - `3346ab9 P2-A-007 add phase2 CI quality gates`
  - Follow-up fixes through `fb00be6 Add recoverable sync job leases`

## 3. Integrated API paths

### Integrations

- `GET /api/internal/integrations/configs/`
- `GET /api/internal/integrations/configs/{id}/`
- `GET /api/internal/integrations/sync-jobs/`
- `POST /api/internal/integrations/sync-jobs/{id}/run-mock/`
- `POST /api/internal/integrations/sync-jobs/{id}/disable/`
- `GET /api/internal/integrations/sync-runs/`
- `GET /api/internal/integrations/sync-runs/{id}/`

Credential display remains masked. `credential_ciphertext` is not displayed by frontend pages.

### Product status

- `GET /api/internal/products/status-recommendations/`
- `GET /api/internal/products/status-recommendations/{id}/`
- `POST /api/internal/products/status-recommendations/{id}/confirm/`
- `POST /api/internal/products/status-recommendations/{id}/reject/`
- `GET /api/internal/products/status-transitions/`
- `POST /api/internal/products/status/evaluate-mock/`

High-risk recommendations such as clearance, stopped, and archived show confirmation prompts. Backend roles and permissions remain authoritative.

### Finance reconciliation

- `GET /api/finance/statements/`
- `GET /api/finance/withdrawals/`
- `GET /api/finance/bank-receipts/`
- `GET /api/finance/reconciliation/matches/`
- `POST /api/finance/reconciliation/run-mock/`
- `POST /api/finance/reconciliation/matches/{id}/confirm/`
- `POST /api/finance/reconciliation/matches/{id}/reject/`
- `GET /api/finance/reconciliation/exceptions/`

Finance pages only call `/api/finance/*`.

### Supplier performance

- Internal pages:
  - `GET /api/internal/suppliers/performance/`
  - `GET /api/internal/suppliers/performance/{supplier_id}/`
  - `POST /api/internal/suppliers/performance/calculate-mock/`
- Supplier self-service pages:
  - `GET /api/external/supplier/performance/`
  - `GET /api/external/supplier/performance/history/`

Supplier self-service pages do not call `/api/internal/*` or `/api/finance/*`.

## 4. Pending or mock APIs

- RPA internal management remains pending/mock because latest `main` only exposes Agent execution URLs under `/api/rpa/*`.
- The frontend keeps mock fallback for:
  - `GET /api/internal/rpa/tasks/`
  - `GET /api/internal/rpa/attempts/`
  - `GET /api/internal/rpa/manual-queue/`
  - `GET /api/internal/rpa/account-locks/`
  - `GET /api/internal/rpa/page-signatures/`
- Frontend RPA management pages do not call `/api/rpa/*` Agent execution endpoints and do not simulate Agent tokens.

## 5. Path mismatch handling

- Old frontend API sync path `/api/internal/integrations/sync-tasks/` was corrected to `/api/internal/integrations/sync-jobs/`.
- Old frontend API sync log path `/api/internal/integrations/sync-logs/` was corrected to `/api/internal/integrations/sync-runs/`.
- Backend Phase 2 does not provide `GET /api/finance/reconciliation/matches/{id}/`; the frontend detail page now uses `GET /api/finance/reconciliation/matches/` collection data while confirm/reject use the backend action endpoints.
- No backend files were modified to fit frontend assumptions.

## 6. Permission boundary check

- Frontend still does not perform real permission decisions.
- Real permissions remain backend-driven by roles, permissions, and data scope.
- Finance pages only use `/api/finance/*`.
- Supplier self-service pages only use `/api/external/supplier/*`.
- RPA management pages do not access `/api/finance/*`, `/admin/`, or `/api/rpa/*` Agent execution endpoints.

## 7. Build result

Commands executed:

```bash
cd frontend
npm install
npm run build
```

Results:

- `npm install`: success, dependencies up to date.
- `npm run build`: success.
- Remaining warning: Element Plus vendor chunk is still larger than `500 kB`, about `923.28 kB`.
- Blocking: no.

## 8. Test result

Command executed:

```bash
cd frontend
npm test --if-present
```

Result:

- Exit code: success.
- No output because the frontend project does not define a test script.

## 9. API path scan

Executed scans:

- RPA frontend scan: no actual `/api/rpa/*` Agent execution URL usage in RPA management API/page files.
- Finance API scan: no non-`/api/finance/*` URL in `frontend/src/api/financeReconciliation.js`.
- Supplier self-service page scan: no `/api/internal/*`, `/api/finance/*`, or `/admin/`.
- Product/integration API scan: no `/api/external/*`, `/api/finance/*`, or `/admin/` usage in product/purchasing/integration API files.

Expected note:

- `frontend/src/api/supplierPerformance.js` contains both internal and external supplier performance functions. External supplier self-service pages import only the external functions.

## 10. Security scan result

Executed a sensitive-pattern scan across `frontend/`, `docs/00_stage0/`, `docs/03_api/`, `docs/05_test/`, and `docs/06_release/`.

Findings:

- No new real Token, Cookie, Session, API Key, API Secret, private key, or platform credential was found.
- Matches were limited to historical review/checklist examples and documentation text such as `credential_ciphertext` boundary notes.
- `frontend/dist/` and `frontend/.npm-cache/` are ignored and not tracked by Git.

## 11. Real platform boundary

- Did not connect to real BigSeller, Shopee, TikTok/TK, bank, or payment platforms.
- Did not submit real supplier, order, finance, bank, or payment data.
- Did not enable real automated repricing, clearance, replenishment, listing, delisting, or finance actions.
- Production access remains disabled or not approved in frontend placeholders.
