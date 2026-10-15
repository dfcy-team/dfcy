# Historical Sample Cost Backfill

The command `backfill_sample_confirmed_costs` now also considers imported `pending` items from an empty source or `legacy_shop_analytics_bd`. It never overwrites an existing unit cost, amount or cost-version reference, including a verified zero.

## Matching

- Require an exact unique active SKU or legacy-SKU mapping in the same tenant; do not use fuzzy matches.
- Require an active warehouse in the shop country. An explicit warehouse is preserved and validated; otherwise exactly one active country warehouse must exist.
- Historical `site_code` may equal the exact owning shop code. A different shop/country is rejected; arbitrary suffix matches are not used.
- Use the current confirmed product-cost ledger version, regardless of shipment/sample date. The previous-month fallback has been removed. Do not substitute purchase prices, inventory quantities or zero for unknown costs.
- Preserve existing fulfillment/snapshot totals for manual review if any are already known while an item is still missing its cost.

## Persistence

Each fulfillment is locked before its items and BD sample snapshot. New item costs equal the confirmed unit cost multiplied by the recorded quantity. Only cost-related fields are updated; sample identity, owner, shop, influencer, task, order, quantities and business dates remain unchanged.

The fulfillment total and BD sample cost are set only when all item amounts are known and currencies agree. An incomplete fulfillment retains a NULL total rather than a partial amount or an invented zero. The sample version advances so stale browser edits can be detected. Audit insertion and cost updates share a transaction.

Repeated execution does not rewrite matched items. Cursors continue to advance even if a reviewed-plan page has no selected items. A reviewed plan can be supplied with `--expected-plan`; changed source fields or cost proposals are rejected under the fulfillment lock.

## Operations

Default mode is preview. Use `--report-path` to retain a JSON receipt and `--apply` only after backup and review. Pages are limited to 500 candidate items. Live repair must compare source populations and protected fields, reconcile item/fulfillment/BD totals, and run a second preview proving no remaining safe matches.

This change does not add a scheduler, modify inventory, import orders, create cost versions or change financial approval/attribution rules.

For the explicitly approved repricing of already-valued historical samples, see `sample-current-confirmed-cost.md`. This older fill-only command still preserves existing costs/totals; it is not an all-sample repricing command.
