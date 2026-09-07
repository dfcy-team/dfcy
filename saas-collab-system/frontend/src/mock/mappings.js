import { mockStoreAuthorizations } from './integrations';
import { masterDataMocks } from './masterData';

// Shared local rehearsal state: confirmation and the platform detail always
// read the same SKU decision. None of these handlers contacts a platform.
const copy = (value) => JSON.parse(JSON.stringify(value));
const ok = (data) => ({ success: true, code: 'OK', message: '本地演练操作已完成', data: copy(data) });
const fail = (message) => ({ success: false, code: 'MAPPING_CONFLICT', message, data: null });
const same = (a, b) => String(a ?? '') === String(b ?? '');
const now = () => new Date().toISOString();
const skus = Array.from({ length: 6 }, (_, index) => ({
  id: 11 + index, sku_code: `SKU-DEMO-00${index + 1}`, legacy_sku_code: `OLD-00${index + 1}`,
  product_id: 1, product_name: '演示商品'
}));
const stores = () => masterDataMocks.stores().data.results;
const authorizations = () => mockStoreAuthorizations().data.results;
let storeMappings;
let productMappings;
let platformDetails;

export function resetMappingMocks() {
  storeMappings = [{
    id: 301, tenant_id: 1, platform: 'shopee', store_id: 1,
    store_code: 'demo-store-sg', store_name: '新加坡示例店铺', authorization_id: 201,
    platform_store_id: 'masked-external-store-001', region: 'SG', timezone: 'Asia/Singapore',
    currency: 'SGD', status: 'active', mapping_source: 'oauth_callback', mapped_by_id: 1,
    mapped_at: '2026-09-05T01:00:00Z', last_verified_at: '2026-09-05T01:00:00Z'
  }];
  platformDetails = Array.from({ length: 6 }, (_, index) => ({
    id: 701 + index, tenant: 1, platform: 3, platform_id: 3, platform_code: 'shopee', platform_name: 'Shopee',
    store: 1, store_id: 1, store_code: 'demo-store-sg', store_name: '新加坡示例店铺',
    site: 1, site_code: 'SG', site_name: '新加坡', country_code: 'SG',
    platform_product_id: `demo-product-00${index + 1}`, platform_variant_id: `demo-variant-00${index + 1}`,
    platform_sku: `DEMO-SKU-00${index + 1}`, source_old_sku_code: `OLD-00${index + 1}`,
    internal_sku: [13, 14].includes(11 + index) ? 11 + index : null,
    internal_sku_code: [13, 14].includes(11 + index) ? skus[index].sku_code : '',
    title: ['轻便收纳包', '旅行收纳套装', '桌面置物架', '便携水杯', '防水整理袋', '折叠收纳盒'][index],
    variant: ['蓝色', '三件套', '白色', '500ml', '中号', '大号'][index],
    category_l1: '家居生活', category_l2: '收纳', category_l3: '日用收纳',
    sales_status: 'active', owner: '演示运营', leader: '演示负责人', source: 'mock',
    platform_created_at: '2026-09-01T09:00:00Z', platform_updated_at: '2026-09-05T01:00:00Z'
  }));
  productMappings = [
    { id: 401, platform_detail_id: 701, status: 'suggested', sku_id: 11, confidence: 92, manually_confirmed: false, result_code: '' },
    { id: 403, platform_detail_id: 703, status: 'conflict', sku_id: 13, confidence: 68, manually_confirmed: true, result_code: 'MAPPING_CONFLICT' },
    { id: 404, platform_detail_id: 704, status: 'mapped', sku_id: 14, confidence: 100, manually_confirmed: true, result_code: '' },
    { id: 405, platform_detail_id: 705, status: 'inactive', sku_id: 15, confidence: 80, manually_confirmed: false, result_code: 'MANUAL_DEACTIVATED' }
  ].map((row) => {
    const detail = platformDetails.find((item) => item.id === row.platform_detail_id);
    return { tenant_id: 1, platform: 'shopee', store_id: 1, store_name: detail.store_name, store_code: detail.store_code,
      store_mapping_id: 301, platform_product_id: detail.platform_product_id, platform_variant_id: detail.platform_variant_id,
      platform_sku: detail.platform_sku, product_id: 1, mapping_source: 'suggested', first_seen_at: now(), last_verified_at: now(), ...row,
      sku_code: skus.find((sku) => sku.id === row.sku_id)?.sku_code || '' };
  });
  productMappings.push({ id: 406, tenant_id: 1, platform: 'shopee', store_id: 1, store_name: '新加坡示例店铺',
    store_code: 'demo-store-sg', store_mapping_id: 301, platform_detail_id: null,
    platform_product_id: 'legacy-product-001', platform_variant_id: 'legacy-variant-001', platform_sku: 'LEGACY-001',
    sku_id: 16, sku_code: 'SKU-DEMO-006', status: 'conflict', confidence: 0, manually_confirmed: false,
    mapping_source: 'manual', result_code: 'DETAIL_NOT_FOUND', first_seen_at: now(), last_verified_at: now() });
}
resetMappingMocks();

function filtered(rows, params = {}) {
  return rows.filter((row) => {
    if (params.unlinked && ['true', '1'].includes(String(params.unlinked)) && row.platform_detail_id != null) return false;
    for (const key of ['platform', 'status', 'store_id', 'store_mapping_id', 'platform_detail_id', 'platform_variant_id']) {
      if (params[key] && !same(row[key], params[key])) return false;
    }
    const search = String(params.search || '').trim().toLowerCase();
    return !search || Object.values(row).some((value) => String(value ?? '').toLowerCase().includes(search));
  });
}
function paginated(rows, params = {}) {
  const size = Math.min(100, Math.max(1, Number(params.page_size) || 20));
  const page = Math.max(1, Number(params.page) || 1);
  return { count: rows.length, results: rows.slice((page - 1) * size, page * size), page, page_size: size,
    next: page * size < rows.length ? page + 1 : null, previous: page > 1 ? page - 1 : null, api_status: 'mock' };
}
export const mockStoreMappings = (params = {}) => ok(paginated(filtered(storeMappings, params), params));
export const mockStoreMappingDetail = (id) => {
  const row = storeMappings.find((item) => same(item.id, id));
  return row ? ok(row) : fail('店铺关联不存在。');
};
export function mockStoreMappingOptions(params = {}) {
  const matchesStore = (row) => (!params.store_id || same(row.store_id ?? row.id, params.store_id))
    && (!params.search || `${row.name || row.store_name || ''} ${row.code || row.store_code || ''}`.toLowerCase().includes(String(params.search).toLowerCase()));
  return ok({
    stores: stores().filter(matchesStore).map((row) => ({ ...row, platform: 'shopee' })),
    authorizations: authorizations().filter((row) => matchesStore(row) && row.status === 'active' && (!params.platform || row.platform === params.platform)).map((row) => ({
      id: row.id, store_id: row.store_id, store_name: row.store_name, store_code: row.store_code,
      platform: row.platform, region: row.region, status: row.status, platform_store_id_masked: row.platform_store_id
    })),
    store_mappings: filtered(storeMappings, params), api_status: 'mock'
  });
}
export function mockCreateStoreMapping(payload = {}) {
  const auth = authorizations().find((row) => same(row.id, payload.authorization_id) && same(row.store_id, payload.store_id) && row.status === 'active');
  const store = stores().find((row) => same(row.id, payload.store_id));
  if (!auth || !store || !['shopee', 'tiktok'].includes(auth.platform)) return fail('请选择当前店铺的有效授权。');
  if (storeMappings.some((row) => row.platform === auth.platform && row.platform_store_id === auth.platform_store_id)) return fail('该授权身份已有店铺关联，请维护已有记录。');
  const row = { id: Math.max(300, ...storeMappings.map((item) => item.id)) + 1, platform: auth.platform,
    store_id: store.id, store_code: store.code, store_name: store.name, authorization_id: auth.id,
    platform_store_id: auth.platform_store_id, region: auth.region, timezone: payload.timezone || store.timezone,
    currency: payload.currency || store.currency, status: 'active', mapping_source: 'manual',
    mapped_by_id: 1, mapped_at: now(), last_verified_at: now() };
  storeMappings.push(row);
  return ok(row);
}
export function mockUpdateStoreMapping(id, payload = {}) {
  const row = storeMappings.find((item) => same(item.id, id));
  if (!row) return fail('店铺关联不存在。');
  if (payload.status && !['active', 'inactive'].includes(payload.status)) return fail('关联状态无效。');
  if (payload.status === 'active' && !authorizations().some((auth) => same(auth.id, row.authorization_id) && auth.status === 'active')) return fail('当前授权已失效，请先重新授权。');
  for (const key of ['status', 'timezone', 'currency']) if (payload[key] !== undefined) row[key] = payload[key];
  row.last_verified_at = now();
  return ok(row);
}
export const mockProductMappings = (params = {}) => ok(paginated(filtered(productMappings, params), params));
export const mockProductMappingDetail = (id) => {
  const row = productMappings.find((item) => same(item.id, id));
  return row ? ok(row) : fail('商品映射不存在。');
};
export function mockProductMappingOptions(params = {}) {
  const details = platformDetails.map((row) => ({ ...row, mapping: productMappings.find((item) => same(item.platform_detail_id, row.id)) || null }))
    .filter((row) => (!params.store_id || same(row.store, params.store_id)) && (!params.platform_detail_id || same(row.id, params.platform_detail_id))
      && (!params.variant_id || same(row.platform_variant_id, params.variant_id)) && (!params.mapping_status || (row.mapping?.status || 'unmapped') === params.mapping_status));
  const search = String(params.search || '').trim().toLowerCase();
  const detailPage = paginated(details.filter((row) => !search || `${row.title} ${row.platform_variant_id} ${row.platform_sku}`.toLowerCase().includes(search)), params);
  return ok({
    count: detailPage.count, page: detailPage.page, page_size: detailPage.page_size,
    next: detailPage.next, previous: detailPage.previous,
    platform_details: detailPage.results.map((row) => ({
      ...row, platform: row.platform_code, store_mapping_id: storeMappings.find((item) => same(item.store_id, row.store) && item.status === 'active')?.id || null,
      internal_sku_id: row.internal_sku
    })),
    skus: paginated(skus.filter((row) => !search || `${row.sku_code} ${row.legacy_sku_code} ${row.product_name}`.toLowerCase().includes(search)), params).results,
    api_status: 'mock'
  });
}
export function mockCreateProductMapping(payload = {}) {
  const detail = platformDetails.find((row) => payload.platform_detail_id ? same(row.id, payload.platform_detail_id) : same(row.platform_variant_id, payload.platform_variant_id));
  const store = storeMappings.find((row) => same(row.store_id, detail?.store) && row.status === 'active' && (!payload.store_mapping_id || same(row.id, payload.store_mapping_id)));
  if (!detail || !store) return fail('请先完成该平台商品所属店铺的有效平台关联。');
  if (productMappings.some((row) => same(row.platform_detail_id, detail.id))) return fail('该平台变体已有映射记录。');
  const row = { id: Math.max(400, ...productMappings.map((item) => item.id)) + 1, platform_detail_id: detail.id,
    platform: store.platform, store_id: store.store_id, store_name: store.store_name, store_code: store.store_code,
    store_mapping_id: store.id, platform_product_id: detail.platform_product_id, platform_variant_id: detail.platform_variant_id,
    platform_sku: detail.platform_sku, sku_id: null, sku_code: '', status: 'unmapped', confidence: null,
    manually_confirmed: false, mapping_source: 'manual', result_code: '', first_seen_at: now(), last_verified_at: now() };
  productMappings.push(row);
  return ok(row);
}
export function mockUpdateProductMapping(id, payload = {}) {
  const row = productMappings.find((item) => same(item.id, id));
  if (!row) return fail('商品映射不存在。');
  const detail = platformDetails.find((item) => same(item.id, row.platform_detail_id));
  if (payload.status === 'inactive') {
    row.status = 'inactive'; row.result_code = 'MANUAL_DEACTIVATED'; row.last_verified_at = now();
    return ok(row);
  }
  if (row.status === 'inactive') return fail('已停用映射不能继续确认，请核对历史记录。');
  if (!storeMappings.some((item) => same(item.id, row.store_mapping_id) && item.status === 'active')) return fail('店铺关联已停用。');
  const sku = skus.find((item) => same(item.id, payload.sku_id || row.sku_id));
  if (!sku) return fail('请选择有效的内部 SKU。');
  if (payload.manually_confirmed === true) {
    if (!detail) return fail('该历史映射尚未归集平台商品明细，请先核对并补齐对应的平台商品。');
    if (!['suggested', 'conflict'].includes(row.status)) return fail('请先登记映射建议，再人工确认。');
    if (detail.internal_sku && !same(detail.internal_sku, sku.id)
      && !(row.status === 'conflict' && payload.replace_existing === true && same(payload.expected_internal_sku_id, detail.internal_sku))) return fail('平台明细已关联其他 SKU，请核对旧 SKU 后明确确认更换。');
    if (productMappings.some((item) => item.id !== row.id && item.store_mapping_id === row.store_mapping_id && item.status === 'mapped' && same(item.sku_id, sku.id))) return fail('该 SKU 已关联店铺内其他平台变体。');
    Object.assign(row, { status: 'mapped', sku_id: sku.id, sku_code: sku.sku_code, product_id: sku.product_id, manually_confirmed: true, result_code: '', last_verified_at: now() });
    Object.assign(detail, { internal_sku: sku.id, internal_sku_code: sku.sku_code });
  } else {
    if (!Number.isInteger(payload.confidence) || payload.confidence < 0 || payload.confidence > 100) return fail('置信度须为 0 到 100 的整数。');
    if (row.status === 'mapped' && !same(row.sku_id, sku.id)) {
      Object.assign(row, { status: 'conflict', result_code: 'MAPPING_CONFLICT', confidence: payload.confidence });
    } else if (['unmapped', 'suggested'].includes(row.status)) {
      const conflict = detail?.internal_sku && !same(detail.internal_sku, sku.id);
      Object.assign(row, { status: conflict ? 'conflict' : 'suggested', result_code: conflict ? 'MAPPING_CONFLICT' : '', sku_id: sku.id, sku_code: sku.sku_code, product_id: sku.product_id, confidence: payload.confidence, manually_confirmed: false, mapping_source: 'suggested', last_verified_at: now() });
    } else return fail('当前状态不能登记建议。');
  }
  return ok(row);
}
export function mockPlatformProductDetails(params = {}) {
  const rows = platformDetails.map((row) => ({ ...row, mapping: productMappings.find((item) => same(item.platform_detail_id, row.id)) || null }));
  return ok(paginated(rows.filter((row) => {
    if (params.platform_id && !same(row.platform, params.platform_id)) return false;
    if (params.store_id && !same(row.store, params.store_id)) return false;
    if (params.mapping_status && (row.mapping?.status || 'unmapped') !== params.mapping_status) return false;
    return !params.search || `${row.title} ${row.platform_variant_id} ${row.platform_sku} ${row.internal_sku_code}`.toLowerCase().includes(String(params.search).toLowerCase());
  }), params));
}
export function mockCreatePlatformProductDetail(payload = {}) {
  if (!payload.platform_variant_id || !payload.store || !payload.platform) return fail('请补齐平台、店铺和平台变体。');
  if (platformDetails.some((row) => same(row.platform, payload.platform) && same(row.store, payload.store) && row.platform_variant_id === payload.platform_variant_id)) return fail('平台变体已存在。');
  const row = { ...payload, id: Math.max(700, ...platformDetails.map((item) => item.id)) + 1 };
  platformDetails.push(row);
  return ok(row);
}
export function mockUpdatePlatformProductDetail(id, payload = {}) {
  const row = platformDetails.find((item) => same(item.id, id));
  if (!row) return fail('平台商品明细不存在。');
  const controlled = productMappings.some((item) => same(item.platform_detail_id, id));
  if (controlled && ['internal_sku', 'new_sku_code', 'source_old_sku_code', 'platform', 'store', 'platform_variant_id'].some((key) => key in payload && !same(payload[key], row[key]))) return fail('该商品已纳入受控映射，请从 SKU 映射入口维护。');
  Object.assign(row, payload);
  return ok(row);
}
