export const filterLabels = {
  date_from: '开始日期',
  date_to: '结束 / 截止日期',
  platform: '平台',
  platforms: '多个平台（逗号分隔）',
  store_id: '店铺编号',
  store_ids: '多个店铺编号（逗号分隔）',
  region: '站点',
  currency: '币种',
  sku: 'SKU（新/旧/别名）',
  warehouse_id: '仓库编号',
  site_code: '库存站点',
  status: '业务状态',
  fee_category: '费用分类',
  match_status: '匹配状态',
  external_order_id: '平台订单号',
  sku_mode: 'SKU 查询口径',
  mapping_as_of: '别名核对日期'
};
export const money = (value) =>
  value == null || value === ''
    ? '—'
    : new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(Number(value));
export const present = (value) => (value == null || value === '' ? '未提供' : String(value));
Object.assign(filterLabels, {
  inventory_type: '商品类型',
  unmapped_only: '商品关联状态',
  cost_status: '成本状态',
  raw_fee_name: '来源费用名称'
});
export function pivotRows(rows, dimensions, pivot, metric) {
  const keys = dimensions.filter((key) => key !== pivot);
  const headings = [...new Set(rows.map((row) => present(row[pivot])))];
  const groups = new Map();
  for (const row of rows) {
    const key = JSON.stringify(keys.map((k) => row[k]));
    if (!groups.has(key)) groups.set(key, { label: keys.map((k) => present(row[k])).join(' · '), cells: {} });
    groups.get(key).cells[present(row[pivot])] = row[metric];
  }
  return { headings, rows: [...groups.values()] };
}
export function drillQuery(dataset, row, config) {
  const filters = { ...config.filters };
  for (const key of [
    'store_id',
    'platform',
    'region',
    'currency',
    'warehouse_id',
    'site_code',
    'fee_category',
    'match_status'
  ])
    if (row[key] != null && row[key] !== '') filters[key] = row[key];
  if (row.date) {
    filters.date_from = row.date;
    filters.date_to = row.date;
  }
  if (dataset === 'sales_skus' || dataset.startsWith('inventory')) {
    const sourceSku = row.source_sku || row.seller_sku || row.sku;
    if (sourceSku && filters.sku_mode === 'related') {
      filters.source_sku = sourceSku;
      if (!filters.sku) filters.sku = row.internal_sku || sourceSku;
    } else if (sourceSku) filters.sku = sourceSku;
  }
  if (!filters.sku && row.internal_sku) filters.sku = row.internal_sku;
  if (!filters.sku && config.dimensions.includes('internal_sku') && row.internal_sku == null)
    filters.unmapped_only = 'true';
  if (dataset.startsWith('inventory') && config.dimensions.includes('inventory_type')) {
    filters.inventory_type = row.inventory_type || 'unknown';
    if (row.inventory_type === 'virtual') filters.include_virtual = 'true';
  }
  if (dataset === 'finance' && row.fee_name != null) filters.raw_fee_name = row.fee_name;
  delete filters.cost_status;
  if (filters.sku) filters.sku_exact = 'true';
  if (filters.external_order_id) filters.order_exact = 'true';
  if (dataset === 'sales_skus') filters.exclude_cancelled = 'true';
  if (dataset === 'sales' && (row.status || filters.status)) filters.order_status = row.status || filters.status;
  if (dataset === 'refunds' && (row.status || filters.status)) filters.refund_status = row.status || filters.status;
  if (row.store_id) delete filters.store_ids;
  if (row.platform) delete filters.platforms;
  if (dataset.startsWith('inventory')) delete filters.currency;
  delete filters.status;
  if (dataset === 'finance')
    return { ...filters, tab: 'transactions', period_start: filters.date_from, period_end: filters.date_to };
  return filters;
}
