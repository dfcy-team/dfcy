# WMS workspace credential readiness increment

This candidate is based directly on deployed `v2.44.67-deployed`, commit
`87886c3716b63f40efb8e5cc4a338cff47894862`. It replaces the business-code part of
`9ee8a2d9685d29a38d03205f171b703c92751acc`, whose parent was V2.44.66.
The release version is allocated by the architect at deployment time.

## Behavior and scope

Credentials saved through the custody service have status `configured`.
The workspace previously counted them in its configuration summary but excluded
them from job readiness and reconciliation previews. The change accepts that
existing status consistently. Authorization, capability, tenant and execution
checks remain in place; workspace readiness is not evidence of a successful live
WMS connection.
Disabled configurations are excluded from reconciliation eligibility, and negative
regressions cover disabled configurations plus expired and revoked credentials.

Runtime changes are limited to `backend/apps/integrations/workspace_service.py`.
Tests are in `backend/tests/test_warehouse_api_binding_closure.py`.
There are no frontend, schema, data migration, menu or production-control changes.
The workspace is shared by integration providers; validation includes warehouse,
capability and Shopee readiness regressions.

## Network configuration is a separate architecture operation

The original patch added `heng.jfwms.com` to backend, celery and celery-beat in
`deploy/production-control/production-compose.yml`. That change is excluded here.
It must not be treated as part of the business-code release or proof that the
active deployment Compose chain has changed. The active VM used an installed
Compose chain, not this repository template, at review time.

Before enabling WMS requests the architect must verify the actual endpoint with
the WMS configuration, obtain/store the real credentials through the existing
custody UI, bind the correct tenant/warehouse, and update the effective runtime
network configuration using the production control mechanism. Capture before/after
non-secret configuration and verify that unapproved hosts remain rejected.
Run a bounded read-only check before scheduling imports. No network or sync
enablement is implied by merging this patch.

## Verification and rollback

On the rebased isolated checkout, run:

```text
python -m pytest -q tests/test_warehouse_api_binding_closure.py tests/test_sync_capability_gate.py tests/test_shopee_production_oauth_readiness.py
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --cached --check
```

CI must run on the pushed commit. Scan the actual net diff for credentials; test
fixtures must remain synthetic. No production database is used for these tests.

Before merge, recheck that deployed tag and main still resolve to the parent above.
If they have advanced, rebuild from the new deployed parent and repeat verification.
For rollback, revert this business-code commit and rebuild through the controlled
release pipeline, or use the previously verified application image digests.
No database reverse migration or data restoration is required. Restoring the old
code restores the previous workspace readiness display.
