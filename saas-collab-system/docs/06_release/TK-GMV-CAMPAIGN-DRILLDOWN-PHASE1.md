# GMV Max campaign drilldown - Phase 1

## Delivery and deployment boundary

Implemented locally only. This change does not deploy to production, modify production configuration, initiate collection, or migrate database tables. Preserve existing production hotfixes when preparing a later release.

## Implemented behavior

- The advertising performance shop summary opens a stored campaign list for the selected shop.
- The existing daily-spend endpoint accepts `report_type=gmv_max_campaigns` and requires a store ID. Existing user, tenant and store visibility filtering remains in use.
- Campaign rows are extracted from validated stored GMV Max daily snapshots, not from BASIC advertising records or new provider requests.
- Campaign details show daily cost, reported revenue, order count, snapshot ID and collection timestamp.
- Aggregation keeps store, advertiser, platform store identity, currency and report timezone separate. ROI is total revenue divided by total cost; cost per order is total cost divided by total orders. Zero denominators remain unknown.
- Coverage refers to available account snapshot dates. A missing campaign on a date is not fabricated as a zero-spend campaign row.
- Filter changes invalidate selected details and stale responses. Errors and snapshot safety limits are surfaced rather than displayed as zero data.

## Known source limitations

Current validated daily snapshots contain campaign IDs and metrics, but no reliable campaign names or product/live classification. These fields remain unknown. Product/live filter options do not infer classification from IDs, names or revenue. Reliable metadata ingestion is required before those categories can contain classified campaigns.

Independent product, live-session and video-creative detail data is outside this phase. Campaign totals must not be reused as those independent detail metrics.

## Changed areas

- backend/apps/integrations/gmv_max_read.py
- backend/apps/integrations/gmv_max_campaigns.py
- backend/apps/integrations/test_gmv_max_campaigns.py
- backend/apps/reports/tiktok_ads_services.py
- backend/apps/reports/tiktok_ads_views.py
- frontend/src/components/TikTokAdsDailySpendOverview.vue
- frontend/src/components/TikTokGmvCampaignDrilldown.vue
- frontend/tests/tiktok-daily-spend.spec.js
- frontend/tests/tiktok-gmv-campaigns.spec.js

## Verification

- Backend pure unit tests: 5 passed (`python -m unittest apps.integrations.test_gmv_max_campaigns`).
- Frontend tests: 13 passed (`npx vitest run tests/tiktok-gmv-campaigns.spec.js tests/tiktok-daily-spend.spec.js`).
- Production frontend build passed with explicit `VITE_USE_MOCK=false`. The initial build without that variable was correctly rejected by the existing production safety guard; the guard was not changed.
- Menu permission prebuild check: 125 menus and 160 routes passed.
- No authenticated production UI acceptance or live provider verification was performed. Backend tests cover pure aggregation boundaries, not a full Django database-backed permission integration suite.

## Later release acceptance

Review this branch against the current production release before deployment. Use an authorized test account to verify store scoping, campaign drilldown, missing metadata, date changes and source evidence. Verify cross-tenant denial through the database-backed API test suite before production release. Do not enable additional collection tasks as part of this UI release.
