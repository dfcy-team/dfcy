import { successResponse } from './index';

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

const migrationRows = [
  {
    store_id: 2,
    store_code: 'legacy-store-sg',
    store_name: '旧新加坡店铺',
    platform_id: 1,
    platform_name: '示例平台',
    country_code: 'SG',
    match_status: 'exact',
    status: 'exact',
    reason: '同租户、同平台、同国家代码唯一匹配',
    confidence: 1,
    candidates: [{ id: 101, site_code: 'SG', name: '新加坡站点', country_code: 'SG' }],
    before: { platform_site_id: null, platform_site_name: null },
    after: { platform_site_id: 101, platform_site_name: '新加坡站点' },
  },
  {
    store_id: 3,
    store_code: 'legacy-store-my',
    store_name: '旧马来西亚店铺',
    platform_id: 1,
    platform_name: '示例平台',
    country_code: 'MY',
    match_status: 'ambiguous',
    status: 'ambiguous',
    reason: '同租户、同平台、同国家代码匹配到多个站点',
    confidence: 0,
    candidates: [
      { id: 102, site_code: 'MY', name: '马来西亚站点 A', country_code: 'MY' },
      { id: 103, site_code: 'MY-2', name: '马来西亚站点 B', country_code: 'MY' },
    ],
    before: { platform_site_id: null, platform_site_name: null },
    after: { platform_site_id: null, platform_site_name: null },
  },
  {
    store_id: 4,
    store_code: 'legacy-store-th',
    store_name: '旧泰国店铺',
    platform_id: 1,
    platform_name: '示例平台',
    country_code: 'TH',
    match_status: 'unmatched',
    status: 'unmatched',
    reason: '同租户、同平台下没有同国家代码站点',
    confidence: 0,
    candidates: [],
    before: { platform_site_id: null, platform_site_name: null },
    after: { platform_site_id: null, platform_site_name: null },
  },
];

const clone = (value) => JSON.parse(JSON.stringify(value));

export const masterDataMocks = {
  platformCatalog: () => successResponse({ count: 5, results: [
    { value: 'shopee', canonical_code: 'SHOPEE', label: 'Shopee', priority_level: 'P0', connector_status: 'ACTIVE' },
    { value: 'tiktok', canonical_code: 'TIKTOK_SHOP', label: 'TikTok Shop', priority_level: 'P0', connector_status: 'ACTIVE' },
    { value: 'lazada', canonical_code: 'LAZADA', label: 'Lazada', priority_level: 'P0', connector_status: 'TESTING' },
    { value: 'amazon', canonical_code: 'AMAZON', label: 'Amazon', priority_level: 'P0', connector_status: 'NOT_IMPLEMENTED' },
    { value: 'other', canonical_code: 'OTHER', label: 'Other', priority_level: 'P3', connector_status: 'NOT_IMPLEMENTED' }
  ] }),
  sites: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'TH-SHOPEE', name: '泰国 Shopee', country_code: 'TH', platform: 'shopee', status: 'active' },
    { id: 2, tenant_id: 1, code: 'MY-SHOPEE', name: '马来西亚 Shopee', country_code: 'MY', platform: 'shopee', status: 'active' }
  ])),
  platformSites: () => successResponse(page([
    {
      id: 101, tenant_id: 1, platform_id: 1, platform_code: 'demo-marketplace', platform_type: 'other',
      site_code: 'SG', name: '新加坡站点', country_code: 'SG', currency_code: 'SGD', timezone: 'Asia/Singapore', status: 'active'
    },
    {
      id: 102, tenant_id: 1, platform_id: 1, platform_code: 'demo-marketplace', platform_type: 'other',
      site_code: 'MY', name: '马来西亚站点', country_code: 'MY', currency_code: 'MYR', timezone: 'Asia/Kuala_Lumpur', status: 'active'
    },
    {
      id: 103, tenant_id: 1, platform_id: 1, platform_code: 'demo-marketplace', platform_type: 'other',
      site_code: 'MY-2', name: '马来西亚站点 B', country_code: 'MY', currency_code: 'MYR', timezone: 'Asia/Kuala_Lumpur', status: 'active'
    }
  ])),
  platformSiteMigrationPreview: () => {
    const rows = migrationRows.filter((row) => row.match_status !== 'applied').map(clone);
    return successResponse({
      status: 'mock',
      count: rows.length,
      matched: rows.filter((row) => row.match_status === 'exact').length,
      applied: 0,
      skipped: 0,
      conflicts: 0,
      rows,
      results: rows,
    });
  },
  applyPlatformSiteMigration: (payload = {}) => {
    const selected = new Set(payload.store_ids || []);
    const rows = migrationRows.filter((row) => selected.has(row.store_id) && row.match_status === 'exact');
    rows.forEach((row) => { row.match_status = 'applied'; row.status = 'applied'; });
    return successResponse({
      status: 'mock',
      matched: rows.length,
      applied: rows.length,
      skipped: Math.max(0, selected.size - rows.length),
      conflicts: 0,
      rows: rows.map(clone),
      idempotency_key: payload.idempotency_key || '',
    });
  },
  platforms: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'demo-marketplace', name: '示例平台', platform_type: 'other', status: 'active' }
  ])),
  stores: () => successResponse(page([
    {
      id: 1, tenant_id: 1, platform_id: 1, platform_name: '示例平台', code: 'demo-store-sg', name: '新加坡示例店铺',
      platform_site_id: 101, platform_site_name: '新加坡站点', external_store_id: 'demo-store-sg',
      seller_entity_id: 'seller-sg-001', business_model: 'cross_border', fulfillment_modes: ['third_party_warehouse'],
      settlement_currency: 'SGD', country_code: 'SG', currency: 'SGD', timezone: 'Asia/Singapore', status: 'active'
    }
  ])),
  warehouses: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'demo-wh-cn', name: '华南示例仓', country_code: 'CN', warehouse_type: 'owned', status: 'active' }
  ])),
  suppliers: () => successResponse(page([
    {
      id: 1, tenant_id: 1, code: 'demo-supplier', name: '示例供应商', contact_alias: '联系人A',
      contact_email_masked: 'd***@example.com', contact_phone_masked: '***8800', status: 'active'
    }
  ]))
};
