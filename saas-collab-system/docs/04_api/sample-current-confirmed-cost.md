# Sample Records: Current Confirmed Product Cost

## Agreed Business Rule

The sample-record cost source is exclusively `products.ProductCostVersion.confirmed_cost` (the product-cost page's confirmed product cost). This applies to new samples, item edits, source imports and explicitly executed historical repricing, including samples older than the cost version.

- Match the same tenant, active SKU (exact standard code, then unique exact legacy code) and active warehouse in the shop country. A caller-selected SKU remains subject to tenant/activity/identity checks.
- For imports/historical records without a selected warehouse, use it only when exactly one active country warehouse exists. Ambiguity is not resolved by guessing or choosing the cheapest warehouse.
- Select confirmed cost versions whose start time is not in the future. Prefer an open-ended version, then highest version number and primary key, matching the ledger's current-row ordering within eligible confirmed rows. Pending rows do not hide a confirmed version. If the selected confirmed row has a NULL amount, cost is unknown; do not fall back to an older amount. The sample's historical date is not a pricing constraint.
- Unit cost comes from `confirmed_cost`, currency from that same row, and item cost is unit cost multiplied by the recorded positive quantity. A confirmed zero is valid. Zero-quantity placeholders, missing SKU/cost, invalid currency, or conflicting country/warehouse remain unknown, not zero.
- Do not use `ProductSKU.purchase_price`, purchase-order cost, system-estimated cost, source-import monetary amounts, fuzzy SKU matches or cross-country costs as fallback.
- A sample total is available only if all items are known and have one currency. Otherwise the total is NULL, never a partial subtotal. No FX conversion is invented when aggregating items.

## Runtime And Compatibility

`apps/influencers/sample_costs.py` owns version selection, derived cost fields and total completeness. Normal create/item-edit and controlled Feishu import services share this logic. Import cost parameters remain accepted for caller compatibility, but cannot override ledger pricing. Source row identities, dates, quantities, raw event payloads and personnel rules remain source-owned.

The cost version ID, unit cost, currency and amount are persisted as traceable snapshots. A GET does not write or reprice. Editing a product-cost version does not silently rewrite all historic samples: a sample edit/import or the historical command below must refresh them. Even a notes-only sample edit refreshes costs in place, without replacing item IDs. Existing processed import rows are updated in place; unchanged source and cost data produces no write.

BD sample snapshots refresh monetary amount/currency only. Owner, influencer, shop, sample date, order attribution, GMV and actual-commission rules remain unchanged. Consequently historical BD investment/ROI may change after repricing; the attribution rule itself does not change.

No product/master data, cost versions, purchase orders, stock quantities or other modules' date-based cost resolvers are changed. No schema migration or recurring job is added.

## Historical Repricing

`reprice_sample_confirmed_costs` is deliberately separate from the older fill-only command. It includes existing known costs and zeros, not only unmatched items. It can replace old imported amounts and inconsistent sample/BD totals with ledger-derived values. Unresolvable old amounts become NULL, with their previous values retained in the audit/preview, rather than continuing to masquerade as verified costs.

Use an active internal tenant superuser. Take a database backup and reconcile protected source populations before applying. Never execute as an automatic migration/startup step. Each page processes at most 100 whole fulfillments, preserving all child IDs and quantities.

```sh
python manage.py reprice_sample_confirmed_costs \
  --tenant-id TENANT_ID --actor-id INTERNAL_SUPERUSER_ID \
  --batch-size 100 --after-fulfillment-id 0 \
  --report-path /private/sample-cost-plan-001.json
```

Review every row's old/new item amounts, cost-version IDs, total and unmatched count. Files must be private because they contain business identifiers and amounts. Use a fresh report filename; existing files are never overwritten.

```sh
python manage.py reprice_sample_confirmed_costs \
  --tenant-id TENANT_ID --actor-id INTERNAL_SUPERUSER_ID \
  --batch-size 100 --after-fulfillment-id 0 \
  --apply --expected-plan /private/sample-cost-plan-001.json \
  --report-path /private/sample-cost-applied-001.json
```

The same tenant, actor, cursor, batch size and exact plan are required. Source/cost changes abort the entire page with no committed writes. Locks follow tenant, fulfillment, items, BD snapshot order. Item/header/snapshot updates and the before/after operation log share the transaction. A failed audit aborts the page. Deleted samples are excluded. No business rows are deleted or newly imported.

Continue from `next_after_fulfillment_id` while `has_more` is true, generating and reviewing a new plan for each page. Do not reuse a pre-apply plan as a retry after a successful apply; recapture the page. A fresh preview after a successful apply should show `changed=0` for unchanged ledger/source data, while unresolved counts can remain positive.

After completion, compare item count/IDs, owners, tasks, dates, quantities, orders and attribution identities against the backup; reconcile known item sums with sample/BD totals and currencies. Report unmatched SKU/warehouse/cost rows separately. A complete code change does not mean all historical amounts have been repaired, and missing SKU data cannot be recovered from a cost table alone.

## Release Boundary

This change delivers code and a separately invoked repricing command. Publishing or merging the PR does not itself execute bulk historical repricing or deploy to VM34/VM10. Approval to use current costs defines the business rule, not evidence of a completed production data rewrite. Deployment and historical data updates require a backup, reviewed plan and reconciliation as described above.
