# Phase 3 API Alignment Matrix

| Module | Development A Current Path | Development B Current Path | Final Path | Backend Change | Frontend Change | Permission | Status |
|---|---|---|---|---|---|---|---|
| analytics overview | none | `/analytics/overview/` | `/analytics/overview/` | add tenant/data-scope aggregate endpoint | none | internal, analytics.view, data scope | backend_change_required |
| analytics sales | none | `/analytics/sales/` | `/analytics/sales/` | add tenant/data-scope aggregate endpoint | none | internal, analytics.view, data scope | backend_change_required |
| analytics inventory | none | `/analytics/inventory/` | `/analytics/inventory/` | add tenant/data-scope aggregate endpoint | none | internal, analytics.view, data scope | backend_change_required |
| analytics metrics | `/analytics/metrics/` | unused | `/analytics/metrics/` | standard list pagination | use metric configuration API | internal, analytics.view | both_change_required |
| analytics aggregates | `/analytics/aggregates/` | unused | `/analytics/aggregates/` | standard list pagination | use detail API where required | internal, analytics.view, metric permission, data scope | both_change_required |
| aggregate mock | `/analytics/aggregate-mock/` | unused | same | none | add only for authorized mock workflow | analytics.calculate, data scope | frontend_change_required |
| inventory alerts | `/alerts/inventory/` | `/replenishment/alerts/` | `/alerts/inventory/` | standard list pagination | replace path | alerts.view, data scope | both_change_required |
| business alerts | `/alerts/business/` | `/alerts/` | `/alerts/business/` | standard list pagination | replace path | alerts.view, data scope | both_change_required |
| alert actions | inventory/business action paths | unused | evaluate-mock, assign, silence, close on each resource | none | add permitted actions and error handling | evaluator or manager | frontend_change_required |
| replenishment recommendations | `/replenishment/recommendations/` | `/replenishment/suggestions/` | `/replenishment/recommendations/` | standard list pagination | replace path | replenishment.view, product scope | both_change_required |
| replenishment actions | detail, evaluate-mock, accept, reject | unused | same | none | add permitted actions | evaluator or reviewer | frontend_change_required |
| lifecycle reviews | `/lifecycle/reviews/` | same | same | standard list pagination | none | lifecycle.view, product scope | backend_change_required |
| lifecycle decisions | `/lifecycle/decisions/` | `/lifecycle/history/` | `/lifecycle/decisions/` | standard list pagination | replace path | lifecycle.view, product scope | both_change_required |
| lifecycle actions | evaluate-mock, confirm, reject | unused | same | none | add permitted actions | evaluator or confirmer | frontend_change_required |
| config definitions | `/config/definitions/` | `/config/items/` | `/config/definitions/` | none | replace path | config.view | frontend_change_required |
| config values | `/config/values/` | `/config/versions/` | `/config/values/` | standard list pagination | replace path | config.view/manage | both_change_required |
| config logs/actions | change-logs, approve, rollback | unused | same | standard list pagination | add permitted actions | viewer, approver, rollback manager | both_change_required |
| finance analytics | `/finance/analytics/overview/` | same | same | none | none | finance.view | aligned |
| finance reconciliation | `/finance/analytics/reconciliation/` | unused | same | none | add when page uses it | finance.view | frontend_change_required |
| finance exceptions | `/finance/analytics/exceptions/` | unused | same | none | add when page uses it | finance.view | frontend_change_required |
| report catalog | `/report/catalog/` | unused | same | none | add catalog API | report.view | frontend_change_required |
| report exports | `/report/exports/` | same | same | standard list pagination | parse standard list | report.view/export, data scope | both_change_required |
| export detail/status | `/report/exports/{id}/` | unused | same | none | add detail/status view | report.view, tenant, data scope | frontend_change_required |

Paths omit the common `/api/internal`, `/api/finance`, or `/api/report` prefix. `aligned` means only that the resource path is frozen; it does not mean the API is already merged or connected.
