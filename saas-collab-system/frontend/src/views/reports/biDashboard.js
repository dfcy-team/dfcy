import { clone, datasetFilters } from './biLayout';
import { drillQuery } from './reportPresentation';
import { defaultReportFilters } from './reportContext';

export const dashboardModules = ['经营分析', '销售管理', '库存管理', '财务中心'];
export const globalFilterKeys = ['date_from', 'date_to', 'platform', 'store_id', 'currency', 'warehouse_id', 'site_code', 'sku_mode', 'mapping_as_of'];
export const componentTypes = [{ value: 'card', label: '指标卡' }, { value: 'bar', label: '柱状图' }, { value: 'line', label: '趋势图' }, { value: 'table', label: '明细表' }, { value: 'pivot', label: '透视表' }];
export function moduleDatasets(datasets, module) {
  return module === '经营分析' ? datasets : datasets.filter(dataset => dataset.module === module);
}
export function newWidget(dataset, type = 'bar', id = `widget-${Date.now()}`) {
  const config = {
    dataset: dataset.id, dimensions: [...dataset.defaults.dimensions], metrics: [...dataset.defaults.metrics], filters: defaultReportFilters(dataset),
    chart: type === 'card' ? 'table' : type, chart_metric: dataset.defaults.metrics[0], pivot: '', ordering: ''
  };
  if (type === 'pivot') {
    config.pivot = config.dimensions.find(key => key !== 'currency') || config.dimensions[0];
    config.field_layout = { rows: config.dimensions.filter(key => key !== config.pivot), columns: [config.pivot], filters: datasetFilters(dataset) };
  }
  return { id, title: `${dataset.name} · ${componentTypes.find(item => item.value === type)?.label || type}`, type, width: 6, height: 360, config };
}

// All effective conditions go back to the scoped API, never filter cached raw facts locally.
export function effectiveConfig(widget, datasets, globalFilters = {}, link = null) {
  const dataset = datasets.find(item => item.id === widget.config.dataset);
  if (!dataset) return null;
  const supported = new Set(datasetFilters(dataset));
  const config = clone(widget.config);
  config.filters = Object.fromEntries(Object.entries(config.filters).filter(([, value]) => value != null && value !== ''));
  const ignored = [];
  for (const [key, value] of Object.entries(globalFilters)) {
    if (value === '' || value == null) continue;
    if (supported.has(key)) {
      config.filters[key] = value;
      if (key === 'store_id') delete config.filters.store_ids;
      if (key === 'platform') delete config.filters.platforms;
    } else ignored.push(key);
  }
  const linked = [];
  if (link && link.source !== widget.id) for (const [key, value] of Object.entries(link.filters)) {
    if (supported.has(key) && value != null && value !== '') {
      // Warehouse stock has no store/platform mapping; date linkage on stock cannot replace its as-of cutoff.
      if (dataset.id.startsWith('inventory') && key.startsWith('date_')) { ignored.push(key); continue; }
      config.filters[key] = value;
      linked.push(key);
      if (key === 'store_id') delete config.filters.store_ids;
      if (key === 'platform') delete config.filters.platforms;
    } else ignored.push(key);
  }
  return { config, linked, ignored: [...new Set(ignored)] };
}
export function selectionLink(widget, row) {
  const common = ['platform', 'store_id', 'currency', 'warehouse_id', 'site_code'];
  const sameDataset = ['status', 'fee_category', 'match_status'];
  const filters = {};
  for (const key of common) if (widget.config.dimensions.includes(key) && row[key] != null && row[key] !== '') filters[key] = row[key];
  // These dimensions have no reliable cross-dataset mapping. Link only peers with the same dataset.
  const local = {};
  for (const key of sameDataset) if (widget.config.dimensions.includes(key) && row[key] != null && row[key] !== '') local[key] = row[key];
  if (widget.config.dimensions.includes('sku') && row.sku) local.sku = row.sku;
  if (widget.config.dimensions.includes('fee_name') && row.fee_name != null) local.raw_fee_name = row.fee_name;
  if (widget.config.dimensions.includes('date') && row.date) { local.date_from = row.date; local.date_to = row.date; }
  return { source: widget.id, dataset: widget.config.dataset, filters, local, row: clone(row) };
}
export function queryWithLink(widget, datasets, filters, link) {
  const safe = link ? { ...link, filters: { ...link.filters, ...(link.dataset === widget.config.dataset ? link.local : {}) } } : null;
  if (safe && ['sales', 'sales_skus'].includes(widget.config.dataset) && ['sales', 'sales_skus'].includes(link.dataset)) {
    for (const key of ['date_from', 'date_to']) if (link.local?.[key]) safe.filters[key] = link.local[key];
  }
  // Cost currency and transaction currency are distinct facts; there is no FX bridge.
  if (safe && (widget.config.dataset === 'inventory_value') !== (link.dataset === 'inventory_value')) delete safe.filters.currency;
  return effectiveConfig(widget, datasets, filters, safe);
}
export function drillLocation(widget, row, result, dataset) {
  const config = result.config || widget.config;
  const query = drillQuery(config.dataset, row, config);
  if (config.dataset.startsWith('inventory')) {
    query.as_of = 'true'; query.warehouse = query.warehouse_id;
    if (config.dataset === 'inventory_value') query.valuation_at = query.date_to ? `${query.date_to}T23:59:59.999999Z` : result.computed_at;
  }
  // Group-level valuation must expand to SKU before following the source route.
  if (config.dataset === 'inventory_value' && !config.dimensions.includes('sku')) return null;
  return { path: dataset.path, query };
}

const specs = {
  '销售管理': [
    ['sales', 'bar', '店铺销售额（原币）', ['store_id', 'currency'], ['gross_sales', 'valid_order_count'], 'gross_sales'],
    ['sales', 'line', '订单日期趋势', ['date', 'currency'], ['valid_order_count', 'gross_sales'], 'gross_sales'],
    ['sales_skus', 'table', 'SKU 销量及映射缺口', ['store_id', 'sku', 'currency'], ['units_sold', 'gross_sales', 'unmapped_count'], 'units_sold'],
    ['refunds', 'table', '售后状态与订单关联', ['status', 'currency'], ['case_count', 'requested_amount', 'completed_amount', 'unlinked_count'], 'case_count']
  ],
  '库存管理': [
    ['inventory', 'card', '各仓库存数量', ['warehouse_id', 'site_code'], ['on_hand', 'available', 'sku_count'], 'on_hand'],
    ['inventory', 'bar', '各仓缺货 SKU', ['warehouse_id', 'site_code'], ['out_count', 'sku_count'], 'out_count'],
    ['inventory', 'table', 'SKU 库存与关联缺口', ['warehouse_id', 'sku'], ['on_hand', 'available', 'reserved', 'unmapped_count'], 'available']
  ],
  '财务中心': [
    ['finance', 'bar', '流水分类与原币净额', ['fee_category', 'currency'], ['signed_amount', 'transaction_count'], 'signed_amount'],
    ['finance', 'table', '流水匹配与分类缺口', ['store_id', 'match_status', 'currency'], ['transaction_count', 'unmatched_count', 'unknown_count', 'signed_amount'], 'unmatched_count'],
    ['inventory_value', 'card', '各仓已覆盖库存货值', ['warehouse_id', 'currency'], ['inventory_value', 'valued_count', 'missing_cost_count'], 'inventory_value'],
    ['inventory_value', 'table', '成本覆盖与零成本核对', ['warehouse_id', 'currency'], ['sku_count', 'valued_count', 'missing_cost_count', 'zero_cost_count', 'inventory_value'], 'missing_cost_count']
  ]
};
export function dashboardTemplate(module, datasets) {
  const choices = module === '经营分析' ? [specs['销售管理'][0], specs['库存管理'][0], specs['财务中心'][0], specs['财务中心'][3]] : specs[module] || [];
  const widgets = choices.flatMap(([id, type, title, dimensions, metrics, chartMetric], index) => {
    const dataset = datasets.find(item => item.id === id);
    if (!dataset) return [];
    const allowedMetrics = metrics.filter(key => dataset.metrics.some(item => item.key === key));
    const allowedDimensions = dimensions.filter(key => dataset.dimensions.some(item => item.key === key));
    if (!allowedMetrics.length || !allowedDimensions.length) return [];
    const widget = newWidget(dataset, type, `widget-${index + 1}`);
    Object.assign(widget.config, { dimensions: allowedDimensions, metrics: allowedMetrics, chart_metric: allowedMetrics.includes(chartMetric) ? chartMetric : allowedMetrics[0] });
    widget.title = title;
    return [widget];
  });
  return { kind: 'dashboard', version: 1, module, filters: {}, widgets };
}
