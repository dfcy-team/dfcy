# Phase 3 API Alignment Matrix

| Module | Frontend Current Path | Backend Current Path | Final Path | Backend Change | Frontend Change | Permission | Response | Status |
|---|---|---|---|---|---|---|---|---|
| analytics overview | `/analytics/overview/` | none | compose `metrics/` plus `aggregates/` | standard list wrapper | yes | internal, analytics.view, data scope | metric/aggregate collection | frontend_change_required |
| analytics sales | `/analytics/sales/` | none | compose `metrics/` plus `aggregates/` | standard list wrapper | yes | internal, analytics.view, data scope | metric/aggregate collection | frontend_change_required |
| analytics inventory | `/analytics/inventory/` | none | compose `metrics/` plus `aggregates/` | standard list wrapper | yes | internal, analytics.view, data scope | metric/aggregate collection | frontend_change_required |
| analytics metrics | unused | `/analytics/metrics/` | `/analytics/metrics/` | standard list wrapper | yes | internal, analytics.view | count/next/previous/results | both_change_required |
| analytics aggregates | unused | `/analytics/aggregates/` | `/analytics/aggregates/` | standard list wrapper | yes | internal, analytics.view, metric permission, data scope | count/next/previous/results | both_change_required |
| aggregate mock | unused | `/analytics/aggregate-mock/` | same | no | yes | analytics.calculate, data scope | aggregate object | frontend_change_required |
| inventory alerts | `/replenishment/alerts/` | `/alerts/inventory/` | `/alerts/inventory/` | standard list wrapper | yes | alerts.view, data scope | alert collection | both_change_required |
| business alerts | `/alerts/` | `/alerts/business/` | `/alerts/business/` | standard list wrapper | yes | alerts.view, data scope | alert collection | both_change_required |
| alert actions | unused | evaluate-mock, assign, silence, close | same resource paths | no | yes | evaluator or manager | alert/action object | frontend_change_required |
| replenishment list | `/replenishment/suggestions/` | `/replenishment/recommendations/` | `/replenishment/recommendations/` | standard list wrapper | yes | replenishment.view, product scope | recommendation collection | both_change_required |
| replenishment actions | unused | detail, evaluate-mock, accept, reject | same | no | yes | evaluator or reviewer | recommendation object | frontend_change_required |
| lifecycle reviews | `/lifecycle/reviews/` | same | same | standard list wrapper | no | lifecycle.view, product scope | review collection | backend_change_required |
| lifecycle decisions | `/lifecycle/history/` | `/lifecycle/decisions/` | `/lifecycle/decisions/` | standard list wrapper | yes | lifecycle.view, product scope | decision collection | both_change_required |
| lifecycle actions | unused | evaluate-mock, confirm, reject | same | no | yes | evaluator or confirmer | review/decision object | frontend_change_required |
| config definitions | `/config/items/` | `/config/definitions/` | `/config/definitions/` | no | yes | config.view | definition collection | frontend_change_required |
| config values | `/config/versions/` | `/config/values/` | `/config/values/` | standard list wrapper | yes | config.view/manage | version collection | both_change_required |
| config logs/actions | unused | change-logs, approve, rollback | same | standard list wrapper | yes | viewer, approver, rollback manager | audit/action object | both_change_required |
| finance analytics | `/finance/analytics/overview/` | same | same | no | no | finance.view | masked read-only object | aligned |
| report catalog | unused | `/report/catalog/` | `/report/catalog/` | no | yes | report.view | catalog | frontend_change_required |
| report exports | `/report/exports/` | same | same | standard list wrapper | no | report.view/export, data scope | export collection | backend_change_required |
| export detail/status | unused | `/report/exports/{id}/` | same | no | yes | report.view, tenant, data scope | export status/audit summary | frontend_change_required |

All paths in the matrix omit the common `/api/internal`, `/api/finance`, or `/api/report` prefix for compactness. `aligned` freezes a matching path only; it does not mean the feature is already merged or connected.
