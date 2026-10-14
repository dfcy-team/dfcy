# BD Performance Code Handoff In PR 304

## Scope

This delivery combines the independent influencer archive changes with the
completed BD report, CSV import, cost breakdown, and exchange-rate configuration
changes. It preserves the latest main historical-sample value protections.

It does not include TikTok credential delivery, creator lookup, dataset staging,
or the new daily API ingestion adapter. Those integrations are a separate
delivery. No live records, CSV exports, database dumps, reconciliation snapshots,
runtime credentials, or one-off production repair operators belong in this PR.

## Business Contract

- Samples are counted from sample attribution facts in the requested sample-date
  range, excluding deleted fulfillments. Outreach-task ownership, creation date,
  lifecycle, and deletion do not gate sample or order statistics.
- Orders must have an independent settled affiliate status and an explicit
  non-full-refund marker. Fulfillment completion is not settlement evidence.
  Missing or unrecognized eligibility information remains unknown.
- Strict mode matches normalized creator account, shop, and product per SKU
  line, using the latest eligible historical sample before the order date.
  Fallback mode matches creator and shop. This patch does not switch to
  whole-order A+B ownership or reassign historical owners.
- The amount is estimated_commission_base once per selected order/SKU line,
  never payment_amount or estimated_paid_commission, and never multiplied by
  quantity. Order count is deduplicated separately from SKU count.
- Costs are sample_cost, actual_standard_commission (actual_paid_commission),
  and actual_ads_commission (actual_paid_shop_ads_commission).
  total_cost is the sum after conversion to the requested report currency.
- ROI is estimated_commission_base / total_cost. Missing eligibility, amount,
  cost or conversion evidence, or a nonpositive denominator, prevents a
  complete ROI. Known subtotals and missing counts are returned separately;
  NULL is not silently converted into a business zero.
- Original-currency amounts remain available. Frontend and backend CSV exports
  expose the amount basis, cost components, completeness, and totals.

## Exchange-Rate Configuration

The tenant-scoped key is influencers.bd.exchange_rates. Each row defines
currency, rate (one foreign-currency unit in CNY), effective_from, and optional
note. CNY remains identity 1.

Authorized saves create a new immediately effective version without approval.
Other configuration approval policies are unchanged. The report chooses the
most recent applicable business-date rate from the current saved schedule.
Changing a historically applicable rate changes subsequent historical queries,
not the original native amounts or stored configuration audit history.

Uncovered currencies or earlier dates use existing tenant ExchangeRate facts.
Saving an empty schedule explicitly restores that fallback without deleting
history. Missing both sources remains unknown; no market rate is invented.
Old pending versions are not automatically enabled when opening the page.

## Deployment Boundary

Additive influencer migrations follow the archive chain:

0032_profile_reference_plain_text
-> 0033_affiliate_estimated_commission_base
-> 0034_affiliate_settlement_status
-> 0035_seed_bd_exchange_rates
-> 0036_affiliate_actual_ads_commission
-> 0037_bd_exchange_rates_direct_save.

0033 adopts a compatible nullable decimal(20,4) schema-only hotfix if present.
0034 and 0036 add nullable facts without backfilling business amounts or
inferring settlement from order_status. 0035 and 0037 change only the dedicated
BD FX configuration definition, preserving existing values and version history.

The new migration set is not covered by the previously registered production
release digest. Do not bypass that gate or reuse the old approved artifact.
Obtain the release-specific validation and approval before production rollout.

Before deployment, verify the actual running SHA/images, tenant, migration
graph, existing columns, backup, workers, and recoverable previous images.
VM34 contains separate API experiments; this main-based PR must not be used to
erase those migration dependencies or overlay the host blindly.

Existing order snapshots need explicit source settlement/refund facts and
amounts to become complete. Schema migration alone does not fill those facts.
Import only the approved scope, protect original creator/sample/owner identity,
quarantine conflicts, and reconcile before versus after counts.

## Attribution Refresh

Use the bounded command refresh_bd_order_attributions with tenant, mode and
start/end dates (at most 31 days per run), or a bounded explicit order-ID list.
The rule version is bd-attribution-v2-settlement-strict/fallback. Rebuild the
approved date range after canonical fact or sample changes.

The daily attribution compensation task retains tenant isolation and performs
bounded recent processing plus historical cursor batches. It is not the daily
API acquisition task and does not prove that API facts are being ingested.

Deletion limits remain enforced for invalid attribution rows. A request to
publish this PR does not authorize table deletion, business-data clearing,
large historical refresh, or deployment to VM10/VM34.

## Acceptance

Run isolated synthetic migrations, model drift checks, permission synchronization,
archive/CAS and historical-sample regressions, sample-only performance regressions,
settlement/amount/cost/FX tests, frontend tests, production build, and current PR CI.
Do not reuse test counts from the VM34-only snapshot as proof of this combined
main-based branch. Financial source NULL semantics and real API ingestion remain
separate integration acceptance boundaries.
