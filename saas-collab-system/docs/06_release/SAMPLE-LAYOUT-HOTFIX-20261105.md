# Sample fulfillment layout hotfix - 2026-11-05

## Fluid wrapping follow-up (current)

User requested controls to use the remaining first-row space instead of forcing
two rows. Use flex-wrap with non-growing, bounded control widths. Date controls
and buttons flow into remaining space or wrap naturally. Keep the one-SKU default.
Source row wrappers use display: contents; no data or permission changes.

- Current SHA256: 2575e6a1b7a765939e6e139a0d39edad7e081951032df48c76a8b88ca42f5002
- Backup: /opt/saas-collab/production/hotfix-sample-layout-20261105/before-fluid.js
- Backup SHA256: 93c070a5ed5e46432212cb938ee8bd72bcb329066d6d658467a139676957bef7
- Restore only if the live hash still matches this current hash.
- Authenticated browser visual acceptance remains pending.

## One SKU follow-up (latest)

At user request, show one SKU by default; more than one item shows +N where
N is item count minus one. Expand/collapse keeps all items available. The compact
toolbar and live date filters remain unchanged.

- Latest SHA256: 93c070a5ed5e46432212cb938ee8bd72bcb329066d6d658467a139676957bef7
- Backup: /opt/saas-collab/production/hotfix-sample-layout-20261105/before-one-sku.js
- Backup hash: d01e3c55f85ade345179d14ac0ee647a5483c413d69865c37629b0c80e52510a
- Syntax checked; compare the latest live hash before any rollback.

## Compact width follow-up

User requested smaller controls after viewing the deployed layout. Search is
320px, standard selectors 160px, dates 142px, action buttons 72/100px on wide
screens; two rows and narrow-screen wrapping remain. Source selector widths
were updated in the same open PR. No release/build process was observed before
this bounded CSS-only follow-up; the live baseline hash was checked again.

- New SHA256: d01e3c55f85ade345179d14ac0ee647a5483c413d69865c37629b0c80e52510a
- Previous backup: /opt/saas-collab/production/hotfix-sample-layout-20261105/before-compact.js
- For rollback of this follow-up verify the new hash, then restore that backup.
- JavaScript syntax checked; authenticated browser visual acceptance pending.

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
