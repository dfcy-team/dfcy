# TK API Main Integration

## Scope

This change integrates the VM34 TikTok API implementation with the current
`main` source tree. It is not an export of the VM34 database. Existing mainline
Shopee, Lazada, warehouse, finance, supplier and influencer functionality is
retained rather than replaced with the older deployed snapshot.

- Shop OAuth: signed browser return, same-store legacy callback recovery,
  replay protection, exact shop verification and sanitized failure diagnostics.
- Ads OAuth: independent credentials, account discovery, multi-account binding,
  account metadata verification and mapping-backed capabilities.
- Standard Ads sync: tenant-scoped jobs, bounded complete natural-day windows,
  explicit-zero evidence and currency-separated reports. This is auction spend,
  not a claim of complete GMV Max or total financial settlement coverage.
- Affiliate sync: complete-day validation, idempotent updates, preserved unknown
  money, revision history, resumable checkpoints and scoped attribution refresh.
  Previous-month refresh on day 28 remains part of the explicit job policy;
  source absence never means deleting existing facts.
- Product and sales fields: parent-linked categories, absent-field preservation,
  exact amounts, distinct delivery/completion dates and verified refund lines.
- Dataset observations: separate PARTIAL/raw-only staging, count evidence and
  identity gates. Staged observations are excluded from formal BD/GMV totals.
- Proxy selection is TikTok-specific. No global proxy or other-platform OAuth
  configuration is enabled by this source change.

## Schema Delivery

Historical migration files from both branches remain in source control. New
merge migrations join their leaves; changing a migration number is not a valid
way to reconcile an already deployed database.

The TK additions include creator profile snapshots, dataset batches/partitions/
records, Ads advertiser mappings and daily spend, Ads OAuth sessions, job mapping
references and nullable sales delivery timestamps. Affiliate payment remains
nullable when the platform has not supplied a proven paid amount. Existing
`estimated_commission_base`, `actual_paid_commission` and
`actual_paid_shop_ads_commission` facts remain independent amounts.

An upgrade must support both a mainline database with Shopee advertising jobs
and a VM34 database with the historical TK migration chain already applied.
Inspect the migration plan, take a protected database/structure backup and test
both upgrade paths before applying the integrated release. No table drop or
business-data deletion is authorized by this PR.

## Data And Secrets Excluded

Only application code, synthetic tests, schema migrations and documentation are
delivered. Sales orders, affiliate records, creator profiles, raw provider
responses, CSV/Excel exports, database dumps, production environment files,
custody files, tokens, OAuth codes, keys and VPN subscriptions are not delivery
inputs. Schema migrations are not permission to import business rows.

Runtime settings and custody references are provisioned separately. Merely
deploying this code does not enable network access, approve a connection, turn
on a sync job or create an automatic schedule.

## Release Gates

Bind review and test results to the final commit, not the old VM34 snapshot.
Run isolated fresh migrations, both upgrade-path regressions, migration-drift
checks, TK API tests, other-platform regression tests, permission-manifest and
frontend gates. Do not reuse a historical build manifest or migration digest.

The VM34 Nginx DNS configuration is an independently validated frontend-only
fix. Preserve the deployed static assets and callback routing; verify the final
entrypoint-generated config, including any template that replaces default.conf.

Production activation requires checking the current container baseline and the
complete migration plan. Never overwrite concurrent releases, replay uncertain
OAuth exchanges or substitute a successful HTTP query for verified ingestion.
