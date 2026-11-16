import { formatField } from '../views/sales-management/display';

export const orderTime = value => {
  if (value && !/(Z|[+-]\d{2}:?\d{2}|UTC)$/i.test(String(value))) return '未提供';
  const date = value ? new Date(value) : null;
  return !date || Number.isNaN(date.getTime()) ? '未提供' : new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(date);
};
export const orderMoney = value => value == null || value === '' ? '未提供' : formatField(value, { format: 'money' });
export function platformPackages(order) {
  const details = order.order_observations || {};
  const result = (details.packages || []).map(pack => ({ ...pack, package_number: pack.package_number || pack.package_id }));
  for (const trace of details.platform_logistics?.packages || []) {
    // Order-level tracking has no parcel identity and must not become a fictitious package.
    if (!trace.package_number && !trace.tracking_number) continue;
    const matches = result.filter(pack => trace.package_number
      ? pack.package_number === trace.package_number
      : trace.tracking_number && pack.tracking_number === trace.tracking_number);
    if (matches.length === 1) Object.assign(matches[0], Object.fromEntries(Object.entries(trace).filter(([, value]) => value != null && value !== '')));
    else result.push({ ...trace });
  }
  return result;
}
export const warehouseItems = order => (order.warehouse_summary?.snapshot?.packages || [])
  .flatMap((pack, packageIndex) => (pack.items || []).map((item, index) => ({ ...item, key: `${packageIndex}-${index}`, package_no: pack.package_no })));
export function matchWarehouseItem(order, line) {
  if (!line.seller_sku || order.warehouse_summary?.stale) return null;
  if ((order.items || []).filter(item => item.seller_sku === line.seller_sku).length !== 1) return null;
  const matches = warehouseItems(order).filter(item => (item.sku || item.warehouse_sku) === line.seller_sku);
  return matches.length === 1 ? matches[0] : null;
}
export function primaryOrderTime(order) {
  const status = String(order.normalized_status || '').toLowerCase();
  if (['cancelled', 'canceled'].includes(status)) return ['取消', order.cancelled_at_utc];
  if (status === 'completed') return ['完成', order.completed_at_utc];
  if (status === 'in_cancel' || String(order.raw_status || '').toUpperCase() === 'IN_CANCEL') return ['申请取消', order.cancel_requested_at_utc];
  if (order.order_observations?.platform_pickup_at_utc) return ['平台揽收', order.order_observations.platform_pickup_at_utc];
  const packages = order.order_observations?.platform_logistics?.packages || [];
  const pickup = packages.length === 1 ? logisticsEventTime(packages[0], 'pickup') : null;
  return pickup ? ['平台揽收（轨迹）', pickup] : ['揽收', null];
}

export function warehouseItemPairs(order) {
  const remaining = new Map(warehouseItems(order).map(item => [item.key, item]));
  const pairs = (order.items || []).map(line => {
    const matches = !order.warehouse_summary?.stale && line.seller_sku && (order.items || []).filter(item => item.seller_sku === line.seller_sku).length === 1
      ? [...remaining.values()].filter(item => (item.sku === line.seller_sku || item.warehouse_sku === line.seller_sku) && (order.items || []).filter(platformItem => platformItem.seller_sku && [item.sku, item.warehouse_sku].includes(platformItem.seller_sku)).length === 1) : [];
    matches.forEach(item => remaining.delete(item.key));
    const quantityKnown = matches.length && matches.every(item => item.quantity != null && Number.isFinite(Number(item.quantity)));
    return { line, matches, mismatch: !!quantityKnown && matches.reduce((sum, item) => sum + Number(item.quantity), 0) !== Number(line.quantity) };
  });
  return [...pairs, ...[...remaining.values()].map(item => ({ line: null, matches: [item], mismatch: false }))];
}
export const warehousePackages = order => order.warehouse_summary?.snapshot?.packages || [];
// Read explicit event descriptions, never treat a generic status code as a milestone.
export function logisticsEventTime(pack, kind) {
  const pattern = kind === 'pickup' ? /^Your package has been picked up by\b/i : /^Your (?:package|parcel) has been delivered(?:!| to buyer|\.|$)/i;
  const times = (pack.events || []).filter(event => pattern.test(String(event.description || '').trim()))
    .map(event => event.occurred_at_utc).filter(value => orderTime(value) !== '未提供');
  return times.sort((a,b) => Date.parse(a) - Date.parse(b))[0] || null;
}
export function extraOrderTimes(order) {
  const details = order.order_observations || {};
  const times = [['买家支付', order.paid_at_utc], ['平台揽收', details.platform_pickup_at_utc], ['平台妥投（非订单完成）', details.platform_delivered_at_utc]];
  const packages = details.platform_logistics?.packages || [];
  packages.forEach((pack,index) => {
    const suffix = packages.length > 1 ? ` · 包裹 ${pack.package_number || pack.tracking_number || index + 1}` : '';
    if (!details.platform_pickup_at_utc) times.push([`平台揽收（轨迹）${suffix}`, logisticsEventTime(pack, 'pickup')]);
    if (!details.platform_delivered_at_utc) times.push([`平台妥投（轨迹，非订单完成）${suffix}`, logisticsEventTime(pack, 'delivered')]);
  });
  if (!order.warehouse_summary?.stale) warehousePackages(order).forEach((pack,index) => {
    const suffix = warehousePackages(order).length > 1 ? ` · 履约 ${index + 1}` : '';
    times.push([`仓库发货${suffix}`, pack.shipped_at_utc], [`仓库揽收${suffix}`, pack.pickup_at_utc]);
  });
  return times.filter(([,value]) => value && orderTime(value) !== '未提供');
}
