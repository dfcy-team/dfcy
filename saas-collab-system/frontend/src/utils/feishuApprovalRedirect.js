const key = 'saas-collab.feishu-approval-return.v1';
const datasets = new Set(['sales', 'sales_skus', 'inventory', 'inventory_value', 'refunds', 'finance']);
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
  const allowed = new Set(['tab', 'feishu_dataset', 'date_from', 'date_to']);
  if (entries.length < 2 || entries.length > 4 || entries.some(([name]) => !allowed.has(name)) || new Set(entries.map(([name]) => name)).size !== entries.length) return false;
  const params = new URLSearchParams(query);
  if (params.get('tab') !== 'analysis' || !datasets.has(params.get('feishu_dataset'))) return false;
  const from = params.get('date_from');
  const to = params.get('date_to');
  if ((from !== null && !validDate(from)) || (to !== null && !validDate(to))) return false;
  return from === null || to === null || from <= to;
};
const valid = (value) => typeof value === 'string' && (approvalPath(value) || reportPath(value));

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
