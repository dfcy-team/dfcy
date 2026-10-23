const key = 'saas-collab.feishu-approval-return.v1';
const datasets = new Set(['sales', 'sales_skus', 'inventory', 'inventory_value', 'refunds', 'finance', 'advertising']);
const reminderFilters = new Set([
  'date_from', 'date_to', 'platform', 'platforms', 'store_id', 'store_ids', 'region', 'country', 'currency',
  'status', 'order_status', 'refund_status', 'case_type', 'return_type', 'external_order_id', 'order_no', 'sku',
  'source_sku', 'sku_mode', 'mapping_as_of', 'sku_exact', 'order_exact', 'exclude_cancelled', 'unmapped_only',
  'has_refund_return'
]);
const approvalPath = (value) => /^\/workflow\/approvals\/[1-9]\d*$/.test(value);
const validDate = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
};
const reportPath = (value) => {
  if (value === '/reports/basic') return true;
  if (!value.startsWith('/reports/basic?') || value.includes('#') || /[\\\u0000-\u001f\u007f]/.test(value)) return false;
  const query = value.slice('/reports/basic?'.length);
  if (!query || query.startsWith('?')) return false;
  const entries = [...new URLSearchParams(query).entries()];
  const allowed = new Set(['tab', 'feishu_dataset', 'date_from', 'date_to', 'store_id', 'region', 'currency']);
  if (entries.length < 2 || entries.length > 7 || entries.some(([name]) => !allowed.has(name)) || new Set(entries.map(([name]) => name)).size !== entries.length) return false;
  const params = new URLSearchParams(query);
  if (params.get('tab') !== 'analysis' || !datasets.has(params.get('feishu_dataset'))) return false;
  const from = params.get('date_from');
  const to = params.get('date_to');
  const storeId = params.get('store_id');
  const region = params.get('region');
  const currency = params.get('currency');
  if ((from !== null && !validDate(from)) || (to !== null && !validDate(to))) return false;
  if ((storeId !== null && !/^[1-9][0-9]{0,18}$/.test(storeId))
      || (region !== null && !/^[A-Z]{2,3}$/.test(region))
      || (currency !== null && !/^[A-Z]{3}$/.test(currency))) return false;
  return from === null || to === null || from <= to;
};
const reminderPath = (value) => {
  const prefix = ['/sales-management/orders?', '/sales-management/returns?'].find((item) => value.startsWith(item));
  if (!prefix || value.length > 131072 || value.includes('#') || /[\\\u0000-\u001f\u007f]/.test(value)) return false;
  const query = value.slice(prefix.length);
  if (!query) return false;
  const entries = [...new URLSearchParams(query).entries()];
  if (entries.length < 2 || entries.length > reminderFilters.size + 2) return false;
  const names = entries.map(([name]) => name);
  if (new Set(names).size !== names.length) return false;
  const params = new URLSearchParams(query);
  const reminderId = params.get('reminder_id');
  const membership = params.get('reminder_membership');
  if (!/^[1-9][0-9]{0,18}$/.test(reminderId ?? '') || !/^(?:0|[1-9][0-9]{0,18})$/.test(membership ?? '')) return false;
  return entries.every(([name, rawValue]) => {
    if (name === 'reminder_id' || name === 'reminder_membership') return true;
    if (!reminderFilters.has(name) || rawValue.length > 1000 || Array.from(rawValue).length > 500 || /[\\\u0000-\u001f\u007f]/.test(rawValue)) return false;
    return true;
  });
};
const valid = (value) => typeof value === 'string' && (approvalPath(value) || reportPath(value) || reminderPath(value));

export function rememberApprovalReturn(value, storage = globalThis.sessionStorage, now = Date.now()) {
  try {
    storage.removeItem(key);
    if (valid(value)) storage.setItem(key, JSON.stringify({ path: value, expires: now + 300000 }));
  } catch { /* Browser storage is optional; normal password login remains available. */ }
}

export function takeApprovalReturn(storage = globalThis.sessionStorage, now = Date.now()) {
  try {
    const raw = storage.getItem(key); storage.removeItem(key);
    const value = JSON.parse(raw);
    return valid(value?.path) && Number.isFinite(value.expires) && value.expires > now && value.expires <= now + 300000 ? value.path : undefined;
  } catch { return undefined; }
}
