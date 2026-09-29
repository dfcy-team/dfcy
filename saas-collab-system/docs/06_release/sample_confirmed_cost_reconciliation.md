# Sample confirmed-cost reconciliation

The sample cost is a snapshot, not a live join to the product-cost page. New or edited sample items use the confirmed cost version for the same tenant, SKU, and warehouse effective at `shipped_at` (or `sample_sent_at` when no shipment timestamp exists). If there is no such version, they use the latest confirmed version whose `effective_from` falls in the preceding calendar month in the application timezone. A missing or ambiguous SKU/warehouse stays unmatched. Purchase prices and zero placeholders are never substituted.

Existing matched snapshots are not repriced. To fill only historical items that were explicitly marked `product_cost_version_unmatched`, run the management command against the **same database** that serves the product-cost and sample pages:

```text
python manage.py backfill_sample_confirmed_costs --tenant-id <tenant> --actor-id <internal-user> --batch-size 100
```

The default is dry-run. Inspect `matched`, `no_sku`, `warehouse_ambiguous`, `no_version`, and `currency_conflict`. Review representative item IDs, SKU/warehouse mapping, confirmed versions, effective timestamps, and the database backup before applying. A sample without a stored warehouse can be inferred only when exactly one active warehouse has the same country as its store. Mixed-currency fulfillments are skipped rather than summed. Apply one bounded batch at a time only after review:

```text
python manage.py backfill_sample_confirmed_costs --tenant-id <tenant> --actor-id <internal-user> --batch-size 100 --after-item-id <cursor> --apply
```

Use the returned `next_after_item_id` as the next cursor while `has_more=true`. Each applied item writes an operation log, and rerunning the same range does not overwrite a matched snapshot. The command does not create cost versions, alter source documents, or change any database schema. If the dry-run reports no eligible records, investigate the source status and SKU/warehouse links rather than force-writing costs.
