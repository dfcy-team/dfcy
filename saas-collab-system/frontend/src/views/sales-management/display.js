const missing = value => value === null || value === undefined || value === '';
const labels = {
  pending: '待处理', processing: '处理中', running: '运行中', queued: '排队中',
  completed: '已完成', success: '成功', partial: '部分成功', failed: '失败',
  open: '待处理', resolved: '已解决', high: '高', medium: '中', low: '低',
  healthy: '正常', warning: '需关注', none: '无', confirmed: '已确认',
  fulfilled: '已履约', cancelled: '已取消', canceled: '已取消', rejected: '已拒绝',
  approved: '已通过', closed: '已关闭', mapped: '已关联', unmapped: '未关联',
  active: '已启用', disabled: '已停用', idle: '尚未运行', expired: '已过期',
  refund: '退款', refund_only: '仅退款', return: '退货', return_refund: '退货退款',
  orders: '订单汇总', order_lines: '订单商品明细', returns: '退款退货',
  store_sales: '门店销售', sku_sales: 'SKU 销售', sales_order: '销售订单',
  refund_return: '退款退货', platform_product: '平台商品', inventory_snapshot: '库存快照'
};

export function statusLabel(value) {
  if (missing(value)) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  return labels[value] || String(value);
}

export function statusType(value) {
  if (['completed', 'success', 'resolved', 'healthy', 'mapped', 'approved', 'active'].includes(value)) return 'success';
  if (['failed', 'high', 'rejected'].includes(value)) return 'danger';
  if (['partial', 'warning', 'pending', 'medium', 'unmapped', 'expired'].includes(value)) return 'warning';
  return 'info';
}

export function formatField(value, column = {}) {
  if (missing(value)) return column.empty || '—';
  if (column.status || column.format === 'enum') return statusLabel(value);
  if (column.format === 'platform') return ({ shopee: 'Shopee', tiktok: 'TikTok Shop', jifeng_wms: '极风 WMS' })[value] || String(value);
  if (column.format === 'datetime') {
    // Never interpret a timestamp without an offset in the viewer's timezone.
    if (!/(Z|[+-]\d{2}:?\d{2}|UTC)$/i.test(String(value))) return '—';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '—' : date.toISOString().slice(0, 19).replace('T', ' ');
  }
  if (column.numeric || ['money', 'ratio'].includes(column.format)) {
    const raw = String(value).replaceAll(',', '');
    if (!/^-?\d+(\.\d+)?$/.test(raw)) return String(value);
    const number = Number(raw);
    if (!Number.isFinite(number)) return '—';
    if (column.format === 'ratio') return `${(number * 100).toFixed(2)}%`;
    return number.toLocaleString('en-US', {
      minimumFractionDigits: column.format === 'money' ? 2 : 0,
      maximumFractionDigits: column.format === 'money' ? 2 : 4
    });
  }
  if (typeof value === 'object') return Array.isArray(value) ? value.map(item => formatField(item)).join('、') : '—';
  return String(value);
}

const metricLabels = {
  gross_sales: '销售额', net_sales: '净销售额', order_count: '订单数',
  valid_order_count: '非取消订单数', cancelled_order_count: '取消订单数',
  units_sold: '销售件数', average_order_value: '客单价', refund_amount: '退款金额', refund_rate: '退款金额占比'
};
const definitions = {
  gross_sales: '按来源币种汇总订单金额', net_sales: '销售额减退款事实金额',
  order_count: '按订单去重计数', valid_order_count: '不含已取消订单',
  cancelled_order_count: '已取消状态订单数', units_sold: '订单商品数量汇总',
  average_order_value: '净销售额 ÷ 订单数', refund_amount: '取退款事实金额，不由取消订单推算',
  refund_rate: '退款金额 ÷ 销售额'
};

export function formatMetric(metric) {
  const isRatio = metric.unit === 'ratio';
  const money = /^[A-Z]{3}$/.test(metric.unit || '');
  return {
    ...metric,
    label: metricLabels[metric.code] || metric.label || metric.code,
    definition: definitions[metric.code] || metric.definition || '当前筛选范围',
    display: formatField(metric.value, { numeric: true, format: isRatio ? 'ratio' : money ? 'money' : undefined }),
    unit: isRatio ? '' : ({ orders: '单', units: '件' }[metric.unit] || metric.unit || '')
  };
}

export function trendSeries(rows, defaultCurrency = '') {
  const groups = new Map();
  for (const row of rows || []) {
    const values = row.net_sales && typeof row.net_sales === 'object'
      ? Object.entries(row.net_sales)
      : [[row.currency || defaultCurrency, row.value ?? row.net_sales]];
    for (const [currency, value] of values) {
      if (missing(value) || !Number.isFinite(Number(value))) continue;
      if (!groups.has(currency)) groups.set(currency, []);
      groups.get(currency).push({ label: row.date || row.label, value });
    }
  }
  return [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([currency, points]) => ({
    currency, points: points.sort((a, b) => String(a.label).localeCompare(String(b.label))).slice(-7)
  }));
}
