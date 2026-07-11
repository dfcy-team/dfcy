# P2-A-004 Change Log

## Scope

- Added finance reconciliation foundation models for platform statements, withdrawals, masked bank receipt imports, reconciliation matches, exceptions, and finance audit logs.
- Added demo/manual-only import services and mock reconciliation suggestion flow.
- Added finance-only APIs for listing/importing demo data, running mock reconciliation, confirming/rejecting suggested matches, and listing exceptions.

## Boundaries

- All finance APIs use `IsFinanceUser`.
- Ordinary internal, external, supplier, and RPA users are rejected.
- Auto reconciliation only creates suggestions; final confirmation requires finance authorization.
- Bank account data is stored only as masked demo placeholder text.
- No real bank API, payment API, platform statement API, card number, bank flow, or fund operation was added.

## Verification

- `python manage.py check`: passed, 0 issues.
- `pytest tests/test_phase2_finance_reconciliation.py tests/test_finance_permissions.py`: passed, 12 tests.
- Full backend `pytest`: passed, 110 tests.
- `python manage.py makemigrations --check --dry-run`: passed, no changes detected.
