# BD Performance Cost Contract

## Scope And Meaning

This is the approved business reporting definition, not a claim about the
platform's final, all-fees settlement cost. The source supplies standard and shop
ads commissions as separate SKU money fields. There is no separately verified
official schema evidence that standard commission includes or excludes ads
commission. The human-approved definition for this report is explicitly:

`total_cost = sample_cost + actual_standard_commission + actual_ads_commission`

`cost_basis = sample_plus_actual_commissions` is returned at report level and in
every owner row and the totals. All monetary output is a Decimal-derived string
with four decimal places, or JSON null when the complete value is unavailable.
The metric `currency` identifies the requested display currency.

This change does not alter the current eligibility rule, strict per-SKU
attribution, frozen sample ownership, business-line deduplication, or sample
date scope. It adds no finance/RPA action, provider call, dataset promotion,
deployment command, or business-data backfill. Broader A/B attribution or cost
policy changes are out of scope.

## Sources And Date Scope

| Component | Source | Business date and scope |
| --- | --- | --- |
| `sample_cost` | `BdSampleAttributionSnapshot.cost_amount` | Active, non-deleted sample snapshots whose `sampled_at` is in the report window |
| `actual_standard_commission` | `AffiliateOrderSnapshot.actual_paid_commission` | Current-rule eligible attributed SKU lines whose `data_time` is in the window |
| `actual_ads_commission` | `AffiliateOrderSnapshot.actual_paid_shop_ads_commission` | The same eligible, deduplicated SKU lines, independently of other amounts |

Standard and ads commissions are direct SKU amounts. Neither is multiplied by
quantity. `actual_paid_commission = 0` remains zero; neither zero nor null ever
falls back to `estimated_paid_commission` or another commission/base amount.
Source null cannot be confirmed as zero.

Orders can retain attribution to historical samples outside the report month.
Their commissions belong to the order month; the historical sample cost does
not become a current-month sample cost merely because it generated an order.
The linked sample snapshot is still the authoritative frozen owner fact.

Eligibility remains settled plus explicitly not fully returned, using the
existing current rule version. This does not establish that all partial refunds
are excluded. Unmatched orders, stale rule versions and duplicate business lines
do not acquire new costs or owners through this change.

## FX And Independent Accumulation

Use the existing, tenant-scoped FX resolver with its approved configuration and
legacy fallback. Sample costs use the local business date of `sampled_at`;
commissions use that of order `data_time`. The resolver and Decimal addition
precision are retained. Rounding occurs at output, not once per SKU.

Each component is accumulated independently. Missing GMV/base or GMV FX failure
does not skip either commission. Missing sample cost or one commission does not
discard independently convertible values from the other components. A failed
conversion makes that component incomplete; it does not force the source amount
or currency into the display currency. Cost conversion, including explicit zero,
uses the existing FX resolver. The pre-existing zero-GMV handling is unchanged.

The numerator remains `estimated_commission_base`, without a payment/quantity
substitution. Its completeness is separate from cost completeness.

## Metrics And Completeness

Each owner and the totals expose:

| Full value | Known partial subtotal | Complete flag |
| --- | --- | --- |
| `sample_cost` | `known_sample_cost` | `sample_cost_complete` |
| `actual_standard_commission` | `known_actual_standard_commission` | `actual_standard_commission_complete` |
| `actual_ads_commission` | `known_actual_ads_commission` | `actual_ads_commission_complete` |
| `total_cost` | `known_total_cost` | `cost_complete` |

A full component is null if it is incomplete. A known subtotal includes all
independently convertible source amounts, even when the corresponding full
component is null. A `0.0000` known subtotal is not evidence that missing values
are zero. `known_total_cost` sums all three known partial components, including
partials from different owners; it does not sum only complete rows.

`sample_cost_complete` depends only on sample value and sample FX coverage,
independently of order eligibility. Both commission complete flags also require
the report's existing `eligibility_complete`. `cost_complete` is the intersection
of the three component complete flags. As before, no order facts in the range
means eligibility is not established, so final commission/total/ROI values remain
null, even when the sample subtotal is complete.

Missing-value counters count included samples or deduplicated attributed SKU
lines, not order quantities or distinct currencies:

- `missing_sample_cost_count`
- `missing_actual_standard_commission_count`
- `missing_actual_ads_commission_count`

The corresponding `missing_<component>_exchange_rate_count` counts source-known
rows whose conversion failed, once per component/row even if multiple rate legs
are missing. It does not count source nulls. `missing_amount_exchange_rate_count`
tracks numerator conversion failures. Existing report-level rate details and
missing-currency diagnostics remain available for audit.

Compatibility aliases have explicit meanings:

- `investment` is the nullable full `total_cost`, no longer sample cost alone.
- `commission` is the nullable full `actual_standard_commission`.
- `missing_cost_count` remains an alias of `missing_sample_cost_count`, not a new total-cost missing count.
- `missing_commission_count` aliases `missing_actual_standard_commission_count`.

ROI is `estimated_commission_base / total_cost`, and is returned only when
`amount_complete && cost_complete && total_cost > 0`. Zero or negative complete
total cost, missing amounts, missing costs, unknown eligibility, or applicable
FX failures yield null ROI. It is not a margin or net-profit calculation.

## Migration, Import And Audit Compatibility

`0036_affiliate_actual_ads_commission` depends on
`0035_seed_bd_exchange_rates` and adds only nullable, blank-compatible
`Decimal(20,4) actual_paid_shop_ads_commission`. There is no zero default or
migration data fill. Existing amounts, row keys and hashes are not rewritten.

CSV accepts the canonical ads name, `actual_shop_ads_commission`,
`actual_ads_commission`, `actual shop ads commission`, and the supported Chinese
actual shop ads/actual ads commission headings. Empty cells remain null; explicit
zero and four-decimal values are retained. Non-finite/oversized values are
rejected by the existing decimal parser.

Legacy CSVs with either actual-commission column absent cannot erase a known
value. Column absence is distinct from an explicitly present blank cell. A
newer explicit blank is an audited source fact under the existing freshness
rules, not an absent-column legacy import. Stale inputs are rejected.

At the same `source_updated_at`, either or both actual-commission fields may be
filled monotonically from null to known only if every other retained fact is
identical. A rewrite/clear of a known commission or any other simultaneous fact
change is a conflict. Existing isolated base/settlement null-completion behavior
is retained; it is not broadened to mixed fact changes.

`_order_values` and before/after revisions include both actual fields. The new
ads field is omitted from the canonical order hash when null, retaining legacy
hashes and archived revision verification. Known zero is included and changes
the hash. Updates use the existing tenant-first lease/row-lock transaction and
revision writer; audit failure rolls back the fact change. Replay is a no-op.

TikTok API dataset projection, staging and checkpoint changes are a separate
delivery, not included in this main-based PR. That adapter must preserve the
same null/zero and currency contracts before promoting API observations into
canonical affiliate snapshots. The CSV importer in this PR is not evidence
that daily API acquisition is enabled or complete.

## Export And Verification

The backend CSV retains both required permissions and tenant-wide data-scope
checks. Owner rows and TOTAL include all component full/known values, complete
flags, missing-value/FX counts, `currency`, `cost_basis`, aliases and ROI. Null
full values are empty cells. Existing spreadsheet-formula protection applies to
both owner and TOTAL rows. It exports only authorized aggregates, not raw
affiliate payloads, credentials or buyer data.

Focused tests are in `test_bd_cost_breakdown.py`,
`test_affiliate_actual_commissions.py`, `test_bd_cost_migration.py`, and the
sample-only performance suite. Existing settlement, FX and
fulfillment expectations are adjusted only where the cost/hash contract changed.
Run only with an isolated disposable test database and mock networking:

```text
python -m pytest --ds=config.settings.settlement_test tests/test_bd_cost_breakdown.py tests/test_affiliate_actual_commissions.py tests/test_bd_cost_migration.py tests/test_bd_settlement_rule.py tests/test_bd_settlement_migration.py tests/test_bd_exchange_rates.py tests/test_bd_performance_sample_only.py tests/test_influencer_fulfillment.py
python manage.py makemigrations --check --dry-run --settings=config.settings.settlement_test
```

The production deployment and bounded, null-only two-field backfill are separate
Main-owned operations, not implemented here. Review, isolated full regression,
and independently reconciled before/after evidence remain release requirements.
