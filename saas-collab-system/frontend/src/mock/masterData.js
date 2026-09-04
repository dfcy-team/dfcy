import { successResponse } from './index';

const page = (results) => ({ status: 'mock', count: results.length, next: null, previous: null, results });

const migrationRows = [
  {
    store_id: 2,
    store_code: 'legacy-store-sg',
    store_name: '旧新加坡店铺',
    platform_id: 3,
    platform_name: 'Shopee',
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
    platform_id: 3,
    platform_name: 'Shopee',
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
    platform_id: 3,
    platform_name: 'Shopee',
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
  platformCatalog: () => successResponse({ count: 8, results: [
    { value: 'shopee', canonical_code: 'SHOPEE', label: 'Shopee', platform_category: 'MARKETPLACE', option_group: '销售渠道/独立站', priority_level: 'P0', connector_key: 'shopee', connector_name: 'Shopee', connector_status: 'ACTIVE', connector_hint: '' },
    { value: 'tiktok', canonical_code: 'TIKTOK_SHOP', label: 'TikTok Shop', platform_category: 'SOCIAL_COMMERCE', option_group: '销售渠道/独立站', priority_level: 'P0', connector_key: 'tiktok', connector_name: 'TikTok Shop', connector_status: 'ACTIVE', connector_hint: '' },
    { value: 'lazada', canonical_code: 'LAZADA', label: 'Lazada', platform_category: 'MARKETPLACE', option_group: '销售渠道/独立站', priority_level: 'P0', connector_key: 'lazada', connector_name: 'Lazada', connector_status: 'TESTING', connector_hint: '' },
    { value: 'amazon', canonical_code: 'AMAZON', label: 'Amazon', platform_category: 'MARKETPLACE', option_group: '销售渠道/独立站', priority_level: 'P0', connector_key: '', connector_name: 'Amazon', connector_status: 'NOT_IMPLEMENTED', connector_hint: '' },
    { value: 'warehouse_owned', canonical_code: 'WAREHOUSE_OWNED', label: '自营仓服务', platform_category: 'WAREHOUSE_SERVICE', option_group: '仓储服务分类', is_business_category: true, priority_level: 'P3', connector_key: '', connector_name: '按具体服务商识别', connector_status: 'UNMAPPED', connector_hint: '业务分类，连接器按具体服务商编码或名称识别。' },
    { value: 'warehouse_third_party', canonical_code: 'WAREHOUSE_THIRD_PARTY', label: '三方仓服务', platform_category: 'WAREHOUSE_SERVICE', option_group: '仓储服务分类', is_business_category: true, priority_level: 'P3', connector_key: '', connector_name: '按具体服务商识别', connector_status: 'UNMAPPED', connector_hint: '业务分类，连接器按具体服务商编码或名称识别。' },
    { value: 'warehouse_platform', canonical_code: 'WAREHOUSE_PLATFORM', label: '平台仓服务', platform_category: 'WAREHOUSE_SERVICE', option_group: '仓储服务分类', is_business_category: true, priority_level: 'P3', connector_key: '', connector_name: '按具体服务商识别', connector_status: 'UNMAPPED', connector_hint: '业务分类，连接器按具体服务商编码或名称识别。' },
    { value: 'other', canonical_code: 'OTHER', label: 'Other', platform_category: 'OTHER', option_group: 'ERP/其他', priority_level: 'P3', connector_key: '', connector_name: 'Other', connector_status: 'NOT_IMPLEMENTED', connector_hint: '' }
  ] }),
  sites: () => successResponse(page([
    { id: 1, tenant_id: 1, code: 'TH-SHOPEE', name: '泰国 Shopee', country_code: 'TH', platform: 'shopee', status: 'active' },
    { id: 2, tenant_id: 1, code: 'MY-SHOPEE', name: '马来西亚 Shopee', country_code: 'MY', platform: 'shopee', status: 'active' }
  ])),
  platformSites: () => successResponse(page([
    {
      id: 101, tenant_id: 1, platform_id: 3, platform_code: 'shopee', platform_type: 'shopee',
      site_code: 'SG', name: '新加坡站点', country_code: 'SG', currency_code: 'SGD', timezone: 'Asia/Singapore', status: 'active'
    },
    {
      id: 102, tenant_id: 1, platform_id: 3, platform_code: 'shopee', platform_type: 'shopee',
      site_code: 'MY', name: '马来西亚站点', country_code: 'MY', currency_code: 'MYR', timezone: 'Asia/Kuala_Lumpur', status: 'active'
    },
    {
      id: 103, tenant_id: 1, platform_id: 3, platform_code: 'shopee', platform_type: 'shopee',
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
    { id: 1, tenant_id: 1, code: 'demo-marketplace', name: '示例平台', platform_type: 'other', platform_category: 'OTHER', connector_key: '', connector_name: 'Other', connector_status: 'NOT_IMPLEMENTED', connector_hint: '当前平台类型尚未匹配连接器。', status: 'active' },
    { id: 2, tenant_id: 1, code: 'myjf', name: '马来极风', platform_type: 'warehouse_third_party', platform_category: 'WAREHOUSE_SERVICE', connector_key: 'jifeng_wms', connector_name: '极风 WMS', connector_status: 'ACTIVE', connector_hint: '已按平台编码或名称识别为极风 WMS，支持库存 API 接入。', status: 'active' },
    { id: 3, tenant_id: 1, code: 'shopee', name: 'Shopee', platform_type: 'shopee', platform_category: 'MARKETPLACE', connector_key: 'shopee', connector_name: 'Shopee', connector_status: 'ACTIVE', connector_hint: '已接入 Shopee 店铺授权与只读同步能力。', status: 'active' }
  ])),
  stores: () => successResponse(page([
    {
      id: 1, tenant_id: 1, platform_id: 3, platform_name: 'Shopee', code: 'demo-store-sg', name: '新加坡示例店铺',
      platform_site_id: 101, platform_site_name: '新加坡站点', external_store_id: 'demo-store-sg',
      seller_entity_id: 'seller-sg-001', business_model: 'cross_border', fulfillment_modes: ['third_party_warehouse'],
      settlement_currency: 'SGD', country_code: 'SG', currency: 'SGD', timezone: 'Asia/Singapore', status: 'active'
    }
  ])),
  warehouses: () => successResponse(page([
    {
      id: 1,
      tenant_id: 1,
      code: 'MY-WMS-01',
      name: '马来极风仓',
      country_code: 'MY',
      warehouse_type: 'third_party',
      service_platform_id: 2,
      service_platform_code: 'myjf',
      service_platform_name: '马来极风',
      service_platform_type: 'warehouse_third_party',
      api_access_available: true,
      status: 'active'
    }
  ])),
  suppliers: () => successResponse(page([
    {
      id: 1, tenant_id: 1, code: 'demo-supplier', name: '示例供应商', contact_alias: '联系人A',
      contact_email_masked: 'd***@example.com', contact_phone_masked: '***8800', status: 'active'
    }
  ]))
};
