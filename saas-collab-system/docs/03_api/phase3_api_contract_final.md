# Phase 3 Final API Contract

## Scope

This contract freezes Phase 3 API naming between Development A and Development B. After this document merges, both teams update their own branches. PR #12 and PR #10 remain Draft until their work and R1 integration review are complete.

All paths use `/api` as the root. Internal APIs require an internal user, tenant filtering, and data scope. Finance APIs additionally require independent finance permission. External users and RPA agents cannot access internal, finance, or report export APIs.

## Response And Errors

Every successful response is:

```json
{"success": true, "code": "OK", "message": "success", "data": {}}
```

Every collection response is:

```json
{"success": true, "code": "OK", "message": "success", "data": {"count": 0, "next": null, "previous": null, "results": []}}
```

Standard query parameters are `page` and `page_size`. Detail and action APIs return an object in `data`. Error semantics are fixed: 400 malformed request, 401 unauthenticated, 403 permission or data scope denied, 404 resource absent, 409 duplicate operation or state conflict, and 422 business-rule or field validation failure.

Development A changes existing `items/pagination` list wrappers to this structure. Development B parses `data.results`. No duplicate compatibility URL is added.

## Final Resources

### Analytics

No `/overview/`, `/sales/`, or `/inventory/` backend endpoint is added. The dashboard, sales, and inventory views compose permitted metrics and aggregates:

- `GET /api/internal/analytics/metrics/`
- `GET /api/internal/analytics/metrics/{id}/`
- `GET /api/internal/analytics/aggregates/`
- `GET /api/internal/analytics/aggregates/{id}/`
- `POST /api/internal/analytics/aggregate-mock/`

The frontend queries metric code, time range, granularity, and permitted dimensions. Backend metric permission, tenant, and data scope apply; finance metrics additionally require `finance.view`. `aggregate-mock` only creates mock aggregation output.

### Alerts

- `GET /api/internal/alerts/inventory/`
- `GET /api/internal/alerts/inventory/{id}/`
- `POST /api/internal/alerts/inventory/evaluate-mock/`
- `POST /api/internal/alerts/inventory/{id}/assign/`
- `POST /api/internal/alerts/inventory/{id}/silence/`
- `POST /api/internal/alerts/inventory/{id}/close/`
- `GET /api/internal/alerts/business/`
- `GET /api/internal/alerts/business/{id}/`
- `POST /api/internal/alerts/business/evaluate-mock/`
- `POST /api/internal/alerts/business/{id}/assign/`
- `POST /api/internal/alerts/business/{id}/silence/`
- `POST /api/internal/alerts/business/{id}/close/`

Inventory and business are separate resources. Alert actions require management permission and audit; they do not trigger real platform, RPA, or finance actions.

### Replenishment

- `GET /api/internal/replenishment/recommendations/`
- `GET /api/internal/replenishment/recommendations/{id}/`
- `POST /api/internal/replenishment/evaluate-mock/`
- `POST /api/internal/replenishment/recommendations/{id}/accept/`
- `POST /api/internal/replenishment/recommendations/{id}/reject/`

Use `recommendations`, never `suggestions`. Inventory alerts remain in alerts/inventory. Accept/reject records a human review only and never creates a purchase order, contacts a real supplier, or triggers RPA.

### Lifecycle

- `GET /api/internal/lifecycle/reviews/`
- `GET /api/internal/lifecycle/reviews/{id}/`
- `POST /api/internal/lifecycle/evaluate-mock/`
- `POST /api/internal/lifecycle/reviews/{id}/confirm/`
- `POST /api/internal/lifecycle/reviews/{id}/reject/`
- `GET /api/internal/lifecycle/decisions/`

Lifecycle history uses `decisions`, never `history`. Confirm/reject requires authorized internal users and audit; no automatic clearance, stop-sale, archive, delist, or repricing is allowed.

### Config

- `GET /api/internal/config/definitions/`
- `GET|POST /api/internal/config/values/`
- `POST /api/internal/config/values/{id}/approve/`
- `POST /api/internal/config/values/{id}/rollback/`
- `GET /api/internal/config/change-logs/`

Use definitions, values, and change-logs, never items or versions. Sensitive configuration returns reference or masked summaries only; plaintext platform credentials, token, cookie, and session values are prohibited.

### Finance Analytics And Report Exports

- `GET /api/finance/analytics/overview/`
- `GET /api/finance/analytics/reconciliation/`
- `GET /api/finance/analytics/exceptions/`
- `GET /api/report/catalog/`
- `GET|POST /api/report/exports/`
- `GET /api/report/exports/{id}/`

Finance results are masked, read-only, and finance-permission gated. Export detail contains export status, data scope, and audit summary; no separate duplicate audit endpoint is needed. Exports are audited placeholder requests filtered by tenant, data scope, report permission, and sensitive-field rules.

## Ownership And Safety

Development A owns URL, serializer fields, response wrapper, pagination, errors, tenant/data scope, permissions, and API tests. Development B owns API paths, request parameters, response/pagination parsing, error display, field mapping, and pending/mock/connected status.

Everything remains pending until backend and frontend changes merge and R1 verifies real requests and authorization failures. No real platforms, credentials, automatic purchase, clearance, stop-sale, archive, repricing, payment, transfer, or withdrawal is permitted.
