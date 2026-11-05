# Sample fulfillment layout hotfix - 2026-11-05

Target: https://xtsy.dingfengchuangyu.com (production-frontend-1).

Source changes: two toolbar rows; show the first two SKU items with a +N toggle.
No backend, permission, database, numbering, or service restart changes.

Production has an additional date-filter patch not present in main. Do not
replace the whole frontend bundle with the main build. The live patch preserves
all existing imports, date inputs, and request logic. It adds scoped grid CSS
for the existing toolbar and a reactive per-row SKU expand/collapse toggle.
Keep the production date controls in the second toolbar row when reconciling
the source change with production.

## Receipt

- Asset: /usr/share/nginx/html/assets/SampleFulfillmentList-dates-a64957eb7b14.js
- Original SHA256: a64957eb7b149ffbe8e4c329b217a114d77dd20d8b66f7a3b95098d1d48151e0
- Published SHA256: 2142b3dc3564a7ebd8797a8a6d7d67e171f9d9abb67f8db2985e678e3bef0e81
- Backup: /opt/saas-collab/production/hotfix-sample-layout-20261105/original.js
- Remote original hash checked before replacement; container and public HTTPS
  asset hashes match the published hash.
- Existing asset URL retained to avoid replacing shared parent chunks. Clients
  may need a hard refresh. Container replacement will require normal release
  reconciliation; this is not a persistent image rebuild.

## Verification

Frontend tests: 12 passed. Production build with VITE_USE_MOCK=false passed.
Live patched module: node --check passed. Public asset downloaded successfully.
Authenticated browser visual/interaction acceptance is not yet verified.

## Rollback

First verify the live hash still matches the published hash above. If it has
changed, stop and reconcile concurrent hotfixes instead of overwriting them.
Then restore the backup using docker cp to the asset path above and verify the
original hash. No restart is required.
