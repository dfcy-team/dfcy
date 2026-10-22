import { datasetFilters } from './biLayout';
import { filterLabels } from './reportPresentation';
import { displayReportValue, filterChoices } from './reportDisplay';
import { completedDateRange } from '../sales-management/overviewTrend';

export function defaultReportFilters(dataset, now = new Date()) {
  const supported = datasetFilters(dataset);
  let defaults = {};
  if (['sales', 'sales_skus', 'refunds', 'advertising'].includes(dataset?.id)) {
    const [date_from, date_to] = completedDateRange(30, now);
    defaults = { date_from, date_to };
  } else if (dataset?.id === 'finance') {
    const date_to = now.toISOString().slice(0, 10);
    defaults = { date_from: `${date_to.slice(0, 7)}-01`, date_to };
  } else if (dataset?.id?.startsWith('inventory')) defaults = { date_to: now.toISOString().slice(0, 10) };
  return Object.fromEntries(Object.entries(defaults).filter(([key]) => supported.includes(key)));
}

export function queryScope(config, dimensionLabels = {}) {
  const filters = config?.filters || {};
  const parts = [];
  if (filters.date_from || filters.date_to) parts.push(`日期：${filters.date_from || '不限开始'} 至 ${filters.date_to || '不限结束'}`);
  else parts.push(config?.dataset?.startsWith('inventory') ? '快照：当前可用截止' : '日期：全部历史');
  for (const [key, value] of Object.entries(filters)) {
    if (['date_from', 'date_to', 'include_virtual', 'report', 'include_summary', 'include_quality', 'compact', 'page', 'page_size'].includes(key) || value == null || value === '') continue;
    if (key === 'grouping') { parts.push(`汇总方式：${{ store: '店铺商品编码', product: '内部商品编码' }[value] || '待核对'}`); continue; }
    if (key === 'unmapped_only') { parts.push(`商品关联状态：${filterChoices.unmapped_only.find(item => item.value === String(value))?.label || '待核对'}`); continue; }
    if (key === 'ordering') {
      const field = String(value).replace(/^-/, '');
      const name = { gross_sales: config?.dataset === 'sales_skus' ? '非取消商品销售额' : '非取消订单销售额', units_sold: '非取消商品销量', order_count: '订单数', total_sales: config?.dataset === 'sales_skus' ? '全部商品销售额' : '全部订单金额', refund_amount: '已完成退款金额', net_sales: '净销售额', store_name: '门店名称', sku: '商品编码', product_name: '商品名称', sales_amount: '销售额', currency: '币种', valid_order_count: '非取消订单数', average_price: '产品平均价格', total_units: '全部商品销量', refund_units: '已完成退款商品数', cancelled_amount: config?.dataset === 'sales_skus' ? '取消商品金额' : '取消订单金额', cancelled_units: '取消商品数量', cancelled_order_count: '取消订单数', average_order_value: '平均订单金额', refund_rate: '退款金额占比', refund_case_count: '退款售后单数', store_code: '门店编码', platform: '平台', region: '站点', source_updated_at: '来源更新时间' }[field];
      parts.push(`结果排序：${name || '所选字段'} · ${String(value).startsWith('-') ? '降序' : '升序'}`); continue;
    }
    const labels = dimensionLabels[key === 'store_ids' ? 'store_id' : key];
    const identity = labels && ['store_id', 'store_ids', 'warehouse_id'].includes(key)
      ? (Array.isArray(value) ? value : String(value).split(',')).map(id => labels[String(id)] ? `${labels[String(id)]}（${id}）` : String(id)).join('、') : null;
    const isBooleanFilter = ['exclude_cancelled', 'sku_exact', 'order_exact'].includes(key);
    const rendered = identity ?? (['sku_mode', 'fee_category', 'match_status', 'cost_status', 'inventory_type', 'status'].includes(key)
      ? displayReportValue(value, key) : isBooleanFilter && (value === true || value === 'true') ? '是' : isBooleanFilter && (value === false || value === 'false') ? '否' : Array.isArray(value) ? value.join('、') : String(value));
    parts.push(`${filterLabels[key] || '业务条件'}：${rendered}`);
  }
  if (config?.dataset?.startsWith('inventory')) parts.push(filters.include_virtual === true || filters.include_virtual === 'true' ? '包含虚拟商品' : '排除虚拟商品');
  parts.push(config?.dataset === 'inventory' ? '库存数量：件；商品数：个' : config?.dataset === 'inventory_value' ? '金额按成本币种分组' : '金额按来源币种分组');
  return parts;
}

export function reportScopeNote(dataset) {
  if (dataset?.startsWith('inventory')) return '快照日期按协调世界时；不是收发存流水。';
  if (['sales', 'sales_skus', 'refunds'].includes(dataset)) return '按门店当地业务日期；退款按申请日期归日。';
  if (dataset === 'advertising') return '按来源广告报表日期查询；归因窗口以平台口径为准。直接与广泛归因成交金额分别展示，不可相加。';
  if (dataset === 'finance') return '流水日期按协调世界时；净流水不是利润。';
  return '日期与指标以当前报表口径为准。';
}

export function reportUnitLabel(dataset) {
  return dataset === 'inventory' ? '库存数量（件）/ 商品数（个）' : dataset === 'inventory_value' ? '成本币种 / 数量' : '来源原币 / 数量';
}

export const accessFailure = failure => [401, 403].includes(failure?.response?.status) || /permission|forbidden|unauthori|无权|权限|授权|数据范围无效/i.test(String(failure?.message || ''));
export function reportResponseError(response, fallback = '读取失败，请重试。') {
  const error = new Error(response?.message || fallback);
  error.response = { status: response?.http_status };
  return error;
}

// Summaries use only the returned, scoped aggregate. Missing or truncated groups must not become complete totals.
export function reportQuality(result, dataset) {
  if (!result || result.truncated || !['finance', 'inventory_value'].includes(dataset)) return [];
  const keys = new Set(result.config?.metrics || []);
  const sum = key => {
    if (!keys.has(key) || result.rows?.some(row => row[key] == null || row[key] === '' || !Number.isFinite(Number(row[key])))) return null;
    return (result.rows || []).reduce((total, row) => total + Number(row[key]), 0);
  };
  const count = value => value == null ? '未提供' : value.toLocaleString('zh-CN');
  const ratio = (value, total) => value == null || !(total > 0) ? '—' : `${(value / total * 100).toFixed(1)}%`;
  if (dataset === 'finance') {
    const total = sum('transaction_count'), unknown = sum('unknown_count'), unmatched = sum('unmatched_count');
    return [
      { label: '流水记录', value: count(total), note: '当前已查询范围 · 条' },
      { label: '未分类流水', value: count(unknown), note: `占比 ${ratio(unknown, total)} · 收支方向需核查`, filter: { fee_category: 'other' } },
      { label: '未匹配或冲突流水', value: count(unmatched), note: `占比 ${ratio(unmatched, total)} · 包含匹配冲突；点击只筛未匹配记录`, filter: { match_status: 'unmatched' } }
    ];
  }
  const total = sum('sku_count'), confirmed = sum('valued_count');
  return [
    { label: '已确认成本覆盖率', value: ratio(confirmed, total), note: `${count(confirmed)} / ${count(total)} 条仓库商品记录` },
    { label: '缺少成本', value: count(sum('missing_cost_count')), note: '未知成本不计为零成本', filter: { cost_status: 'missing' } },
    { label: '零成本', value: count(sum('zero_cost_count')), note: '已确认的零成本记录', filter: { cost_status: 'zero' } }
  ];
}
