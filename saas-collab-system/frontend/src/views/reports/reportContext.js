import { datasetFilters } from './biLayout';
import { filterLabels } from './reportPresentation';
import { displayReportValue } from './reportDisplay';
import { completedDateRange } from '../sales-management/overviewTrend';

export function defaultReportFilters(dataset, now = new Date()) {
  const supported = datasetFilters(dataset);
  let defaults = {};
  if (['sales', 'sales_skus', 'refunds'].includes(dataset?.id)) {
    const [date_from, date_to] = completedDateRange(30, now);
    defaults = { date_from, date_to };
  } else if (dataset?.id === 'finance') {
    const date_to = now.toISOString().slice(0, 10);
    defaults = { date_from: `${date_to.slice(0, 7)}-01`, date_to };
  } else if (dataset?.id?.startsWith('inventory')) defaults = { date_to: now.toISOString().slice(0, 10) };
  return Object.fromEntries(Object.entries(defaults).filter(([key]) => supported.includes(key)));
}

export function queryScope(config) {
  const filters = config?.filters || {};
  const parts = [];
  if (filters.date_from || filters.date_to) parts.push(`日期：${filters.date_from || '不限开始'} 至 ${filters.date_to || '不限结束'}`);
  else parts.push(config?.dataset?.startsWith('inventory') ? '快照：当前可用截止' : '日期：全部历史');
  for (const [key, value] of Object.entries(filters)) {
    if (['date_from', 'date_to', 'include_virtual'].includes(key) || value == null || value === '' || value === false) continue;
    const rendered = ['sku_mode', 'fee_category', 'match_status', 'cost_status', 'inventory_type'].includes(key)
      ? displayReportValue(value, key) : Array.isArray(value) ? value.join('、') : String(value);
    parts.push(`${filterLabels[key] || '业务条件'}：${rendered}`);
  }
  if (config?.dataset?.startsWith('inventory')) parts.push(filters.include_virtual === true || filters.include_virtual === 'true' ? '包含虚拟商品' : '排除虚拟商品');
  parts.push(config?.dataset === 'inventory_value' ? '金额按成本币种分组' : '金额按来源币种分组');
  return parts;
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
