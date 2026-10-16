import { requestApi } from '../../api/request';

export const PERIOD_ANALYSIS_URL = '/api/report/analysis-jobs/';
export const MAX_POLL_MS = 120_000;
export const POLL_INTERVAL_MS = 1_000;

export const DATASET_METRICS = {
  sales: ['gross_sales', 'valid_order_count', 'cancelled_order_count', 'average_order_value'],
  finance: ['signed_amount', 'transaction_count', 'unmatched_count', 'unknown_count'],
  advertising: ['expense', 'impressions', 'clicks', 'direct_gmv', 'broad_gmv', 'record_count', 'ctr', 'cpc', 'direct_roas', 'broad_roas']
};

export const METRIC_LABELS = {
  gross_sales: '销售额', valid_order_count: '有效订单数', cancelled_order_count: '取消订单数', average_order_value: '客单价',
  signed_amount: '流水净额', transaction_count: '流水条数', unmatched_count: '未匹配流水', unknown_count: '未分类流水',
  expense: '广告消耗', impressions: '曝光', clicks: '点击', direct_gmv: '直接归因 GMV', broad_gmv: '广泛归因 GMV',
  record_count: '广告记录数', ctr: '点击率', cpc: '单次点击成本', direct_roas: '直接 ROAS', broad_roas: '广泛 ROAS'
};

export function analysisPayload({ dataset, mode, year, filters, dateFrom, dateTo }) {
  const payload = { dataset, mode, filters: cleanFilters(filters) };
  if (mode === 'period') {
    payload.date_from = dateFrom;
    payload.date_to = dateTo;
  } else payload.year = Number(year);
  return payload;
}

export function cleanFilters(filters = {}) {
  return Object.fromEntries(Object.entries(filters).filter(([, value]) => value != null && value !== ''));
}

export function chartDomain(points = [], metric, accessors = ['current']) {
  const values = points.flatMap(point => accessors.map(accessor => numeric(point?.[accessor]?.metrics?.[metric]))).filter(value => value != null);
  if (!values.length) return null;
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const spread = max - min || Math.abs(max) || 1;
  return [min - spread * 0.04, max + spread * 0.04];
}

export function chartSegments(points = [], metric, accessor = 'current', width = 900, height = 240, domain = null) {
  const values = points.map(point => numeric(point?.[accessor]?.metrics?.[metric]));
  const present = values.filter(value => value != null);
  if (!present.length) return [];
  const [min, max] = domain || [Math.min(0, ...present), Math.max(0, ...present)];
  const spread = max - min || Math.abs(max) || 1;
  const x = index => points.length <= 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = value => height - ((value - min) / spread) * height;
  const segments = [];
  let segment = [];
  values.forEach((value, index) => {
    if (value == null) {
      if (segment.length) segments.push(segment);
      segment = [];
    } else segment.push({ index, x: x(index), y: y(value), value });
  });
  if (segment.length) segments.push(segment);
  return segments;
}

export function metricNumber(value) {
  return numeric(value);
}

export function periodChange(point, metric, comparison) {
  const current = numeric(point?.current?.metrics?.[metric]);
  const previous = numeric(point?.[comparison]?.metrics?.[metric]);
  if (current == null || previous == null) return null;
  return {
    delta: point?.changes?.[metric]?.[comparison]?.delta ?? null,
    percent: point?.changes?.[metric]?.[comparison]?.percent ?? null
  };
}

export function isAccessFailure(response) {
  return [401, 403].includes(response?.http_status) || ['PERMISSION_DENIED', 'AUTH_REQUIRED', 'FORBIDDEN'].includes(response?.code);
}

export async function startAnalysisJob(payload, signal) {
  return requestApi({ method: 'post', url: PERIOD_ANALYSIS_URL, data: payload, signal, timeout: 30_000 });
}

export async function readAnalysisJob(id, signal) {
  return requestApi({ method: 'get', url: `${PERIOD_ANALYSIS_URL}${encodeURIComponent(id)}/`, signal, timeout: 15_000 });
}

export async function cancelAnalysisJob(id) {
  return requestApi({ method: 'delete', url: `${PERIOD_ANALYSIS_URL}${encodeURIComponent(id)}/`, timeout: 15_000 });
}

export function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const cleanup = () => signal?.removeEventListener('abort', onAbort);
    const timer = setTimeout(() => { cleanup(); resolve(); }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      cleanup();
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

export async function pollAnalysisJob(id, { signal, onJob, maxMs = MAX_POLL_MS, intervalMs = POLL_INTERVAL_MS } = {}) {
  const started = Date.now();
  while (Date.now() - started < maxMs) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const response = await readAnalysisJob(id, signal);
    if (!response?.success) return response;
    const job = response.data;
    onJob?.(job);
    if (['completed', 'failed', 'cancelled', 'expired'].includes(job?.status)) return response;
    await delay(Math.min(intervalMs, Math.max(0, maxMs - (Date.now() - started))), signal);
  }
  return { success: false, code: 'POLL_TIMEOUT', message: '任务仍在运行，可继续检查状态。', data: null };
}

export function drillReportConfig(dataset, filters) {
  const dimensions = dataset === 'finance'
    ? ['date', 'store_id', 'platform', 'currency', 'fee_category']
    : dataset === 'advertising'
      ? ['date', 'store_id', 'country', 'platform', 'currency']
      : ['date', 'store_id', 'region', 'platform', 'currency'];
  return {
    dataset,
    dimensions,
    metrics: DATASET_METRICS[dataset].filter(metric => !['average_order_value', 'ctr', 'cpc', 'direct_roas', 'broad_roas'].includes(metric)),
    filters: cleanFilters(filters),
    chart: 'table',
    chart_metric: DATASET_METRICS[dataset][0],
    pivot: '',
    ordering: ''
  };
}

export function rawDetailRoute(dataset, filters, metric) {
  const cleaned = cleanFilters(filters);
  const { date_from: dateFrom, date_to: dateTo, store_id, currency, region, platform } = cleaned;
  if (dataset === 'sales') {
    return {
      path: '/sales-management/orders',
      query: {
        date_from: dateFrom, date_to: dateTo, store_id, currency, region, platform,
        ...(metric === 'cancelled_order_count' ? { order_status: 'cancelled' } : { exclude_cancelled: 'true' })
      }
    };
  }
  if (dataset === 'finance') {
    return { path: '/finance/statements', query: { tab: 'transactions', period_start: dateFrom, period_end: dateTo, store_id, currency, platform } };
  }
  return {
    path: '/analytics/advertising-overview',
    query: { view: 'details', kind: 'shop_daily', date_from: dateFrom, date_to: dateTo, period_start: dateFrom, period_end: dateTo, store_id, currency,
      region: region || cleaned.country || cleaned.storecountry, platform,
      ...Object.fromEntries(['store_ids', 'platforms', 'country', 'storecountry'].filter(key => cleaned[key]).map(key => [key, cleaned[key]])) }
  };
}

function numeric(value) {
  if (value == null || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
