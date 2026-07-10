# P2-A-005 Change Log

## Scope

- Added `SupplierPerformanceSnapshot`, uniquely scoped by tenant, supplier, and reporting period.
- Added a reusable performance calculator based only on existing supplier tasks and shipment records.
- Added internal performance list, supplier detail, and mock calculation APIs.
- Added external supplier current-performance and history APIs.
- Added the required internal supplier route include in `config/urls.py`; no other configuration behavior changed.

## Metrics And Idempotency

- Metrics cover on-time tasks, overdue tasks, exception tasks, shipment accuracy, and timely feedback.
- Rates and the weighted total score are calculated in `performance_services.py`, not in views.
- Empty datasets produce zero metrics and a zero score.
- Repeated calculation for the same tenant, supplier, and period updates the existing snapshot.

## Access Boundaries

- Internal access requires the `suppliers.performance.view` permission and is constrained by `DataScope` (`all` or custom `supplier_ids`).
- External users always derive `supplier_id` from their authenticated profile and cannot request another supplier's data.
- RPA users cannot access internal or external supplier performance APIs.
- Responses contain performance metrics only and do not include purchase prices, payment terms, bank data, or finance amounts.
- No real WeChat, mini-program, supplier platform, finance platform, or external API was connected.

## Verification

- `python manage.py check`: passed, 0 issues.
- `pytest tests/test_phase2_supplier_performance.py tests/test_purchasing_suppliers_api.py`: passed, 16 tests.
- Full backend `pytest`: passed, 118 tests.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
